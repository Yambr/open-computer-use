// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// Copyright (c) 2025 Open Computer Use Contributors

// Command g7-proxy is the visualizer demo sidecar: it is the single holder of the
// gateway mTLS client-cert and translates same-origin browser HTTP/JSON into real
// mTLS calls to the control gateway plane (:9466). Every button on the visualizer
// page drives the REAL create/exec/destroy chain through this proxy — no mock. A
// browser cannot present an Ed25519 client-cert, so the honest boundary is this
// sidecar, mirroring how a real MCP caller holds its credential.
//
// It also keeps an in-memory registry of the sessions IT created (the gateway
// plane exposes create/exec/destroy/status but no list — a session list is an
// operator-plane privilege), so the visualizer can show a live session list, and
// it maps the PoC MCP tool catalog (bash/create_file/str_replace/view/list_dir)
// onto exec with a fixed argv — the same five tools the PoC exposed, driven over
// the real exec channel into the live gVisor guest.
package main

import (
	"bytes"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sort"
	"sync"
	"time"
)

// sessionReg is the in-memory registry of sessions this proxy created. Keyed by
// hint; the gateway has no list route (operator-plane privilege), so the
// visualizer's session list is what this proxy remembers creating.
type sessionReg struct {
	mu   sync.Mutex
	rows map[string]*sessRow
}
type sessRow struct {
	Hint    string `json:"hint"`
	Key     string `json:"key"`
	Image   string `json:"image"`
	Created string `json:"created"` // stamped by the caller (browser) — proxy has no clock authority worth trusting for demo
	Last    string `json:"last"`    // last tool/exec activity (client-supplied label)
}

func (s *sessionReg) put(hint, key, image, now string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.rows[hint] = &sessRow{Hint: hint, Key: key, Image: image, Created: now, Last: now}
}
func (s *sessionReg) touch(hint, now string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if r, ok := s.rows[hint]; ok {
		r.Last = now
	}
}
func (s *sessionReg) drop(hint string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.rows, hint)
}
func (s *sessionReg) list() []*sessRow {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]*sessRow, 0, len(s.rows))
	for _, r := range s.rows {
		out = append(out, r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Created > out[j].Created })
	return out
}

// gatewayClient is the mTLS http.Client dialing control :9466 with the client-cert.
func gatewayClient(certPath, keyPath, caPath string) (*http.Client, error) {
	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, fmt.Errorf("load client cert: %w", err)
	}
	caPEM, err := os.ReadFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("read ca: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("ca pem not parsed")
	}
	return &http.Client{
		Timeout: 60 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{
				Certificates: []tls.Certificate{cert},
				RootCAs:      pool,
				MinVersion:   tls.VersionTLS13,
			},
		},
	}, nil
}

// gw posts a JSON body to a gateway route and returns status + raw bytes.
func gw(client *http.Client, base, route string, body []byte) (int, []byte) {
	req, _ := http.NewRequest(http.MethodPost, base+route, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return http.StatusBadGateway, []byte(fmt.Sprintf(`{"error":%q}`, err.Error()))
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	return resp.StatusCode, raw
}

func main() {
	base := envOr("GATEWAY_URL", "https://control:9466")
	client, err := gatewayClient(
		envOr("CLIENT_CERT", "/pki/client.pem"),
		envOr("CLIENT_KEY", "/pki/client.key"),
		envOr("CA_CERT", "/pki/ca.pem"),
	)
	if err != nil {
		log.Fatalf("g7-proxy: %v", err)
	}
	reg := &sessionReg{rows: map[string]*sessRow{}}
	writeJSON := func(w http.ResponseWriter, code int, raw []byte) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(code)
		_, _ = w.Write(raw)
	}

	mux := http.NewServeMux()

	// /api/create — create a session AND register it locally for the session list.
	mux.HandleFunc("/api/create", func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(io.LimitReader(r.Body, 64*1024))
		// Parse into a map so we can strip proxy-only fields ("now") before the
		// forward: control strict-decodes createBody (DisallowUnknownFields), so an
		// extra field is rejected. Keep only the schema fields control accepts.
		var m map[string]any
		_ = json.Unmarshal(body, &m)
		now, _ := m["now"].(string)
		delete(m, "now")
		hint, _ := m["session_hint"].(string)
		image, _ := m["image"].(string)
		clean, _ := json.Marshal(m)
		code, raw := gw(client, base, "/v1alpha/sessions", clean)
		if code == http.StatusCreated {
			var out struct {
				Key string `json:"key"`
			}
			_ = json.Unmarshal(raw, &out)
			reg.put(hint, out.Key, image, now)
		}
		writeJSON(w, code, raw)
	})

	// /api/exec — run an arbitrary argv (the raw exec verb).
	mux.HandleFunc("/api/exec", func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(io.LimitReader(r.Body, 64*1024))
		var m map[string]any
		_ = json.Unmarshal(body, &m)
		hint, _ := m["session_hint"].(string)
		now, _ := m["now"].(string)
		delete(m, "now")
		reg.touch(hint, now)
		clean, _ := json.Marshal(m)
		code, raw := gw(client, base, "/v1alpha/sessions/exec", clean)
		writeJSON(w, code, raw)
	})

	// /api/tool — the PoC MCP tool catalog mapped onto exec with a fixed argv.
	// {session_hint, tool, args:{...}} -> exec argv. Same five tools the PoC had:
	// bash, create_file, str_replace, view, list_dir. Every tool is a real exec in
	// the live gVisor guest via busybox (demo image); no mock.
	mux.HandleFunc("/api/tool", func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(io.LimitReader(r.Body, 256*1024))
		var in struct {
			SessionHint string            `json:"session_hint"`
			Tool        string            `json:"tool"`
			Args        map[string]string `json:"args"`
			Now         string            `json:"now"`
		}
		if err := json.Unmarshal(body, &in); err != nil {
			writeJSON(w, http.StatusBadRequest, []byte(`{"error":"bad tool body"}`))
			return
		}
		argv, refusal, badReq := toolArgv(in.Tool, in.Args)
		if badReq != "" {
			writeJSON(w, http.StatusBadRequest, []byte(fmt.Sprintf(`{"error":%q}`, badReq)))
			return
		}
		if refusal != "" {
			// Honest tool-not-available answer — no exec, a clear reason.
			writeJSON(w, http.StatusOK, []byte(fmt.Sprintf(`{"exit_code":0,"stdout_b64":"","refusal":%q}`, refusal)))
			return
		}
		reg.touch(in.SessionHint, in.Now)
		execBody, _ := json.Marshal(map[string]any{"session_hint": in.SessionHint, "argv": argv})
		code, raw := gw(client, base, "/v1alpha/sessions/exec", execBody)
		writeJSON(w, code, raw)
	})

	// /api/destroy — destroy and de-register.
	mux.HandleFunc("/api/destroy", func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(io.LimitReader(r.Body, 64*1024))
		var in struct {
			SessionHint string `json:"session_hint"`
		}
		_ = json.Unmarshal(body, &in)
		code, raw := gw(client, base, "/v1alpha/sessions/destroy", body)
		if code == http.StatusOK {
			reg.drop(in.SessionHint)
		}
		writeJSON(w, code, raw)
	})

	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(io.LimitReader(r.Body, 64*1024))
		code, raw := gw(client, base, "/v1alpha/sessions/status", body)
		writeJSON(w, code, raw)
	})

	// /api/sessions — the live session list this proxy created (GET).
	mux.HandleFunc("/api/sessions", func(w http.ResponseWriter, r *http.Request) {
		out, _ := json.Marshal(reg.list())
		writeJSON(w, http.StatusOK, out)
	})

	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte("ok")) })
	mux.Handle("/", http.FileServer(http.Dir(envOr("WEB_ROOT", "/web"))))

	addr := envOr("LISTEN", ":8099")
	log.Printf("g7-proxy: listening on %s → %s", addr, base)
	// Plain HTTP on this listener, and what actually contains it.
	//
	// Do not read this as "it is only a visualiser": `/api/create`, `/api/exec`,
	// `/api/tool` and `/api/destroy` take no inbound credential and drive the
	// real chain through the gateway mTLS client cert this process holds. Anything
	// that can open a socket here acts with that cert and none of its own.
	//
	// Two compose properties contain it, and `deploy/tests/test_fleet_g7_isolation.py`
	// reds if either is lost:
	//   - the port publishes as `127.0.0.1:8099:8099`, so it is not offered off-box;
	//   - the service shares a bridge with control ALONE. A `ports:` publish does
	//     not restrict in-network callers, so sharing the frontend bridge would
	//     hand these routes to the web tier, which processes untrusted input.
	//
	// TLS on this hop would encrypt a channel whose real exposure is authorisation,
	// not eavesdropping; the containment above is what the rule cannot see.
	// nosemgrep: go.lang.security.audit.net.use-tls.use-tls
	log.Fatal(http.ListenAndServe(addr, mux))
}

// toolArgv maps a PoC MCP tool name + args to an argv run in the guest. The five
// tools mirror the PoC catalog EXACTLY (computer-use-server/mcp_tools.py): bash_tool,
// str_replace, create_file, view, sub_agent. `view` handles BOTH a file (numbered
// lines) and a directory listing, per the PoC view docstring — there is no separate
// list tool. sub_agent launches a full CLI agent inside the container and needs an
// agent binary in the image; the scratch+busybox demo image has none, so it returns
// a clear "needs a tooling image" refusal rather than a fake result.
//
// Returns (argv, ok, refusal): ok=false + a refusal string means do NOT exec —
// answer the browser directly (used by sub_agent on the demo image).
func toolArgv(tool string, a map[string]string) (argv []string, refusal string, badReq string) {
	switch tool {
	case "bash":
		if a["command"] == "" {
			return nil, "", "bash: command required"
		}
		return []string{"/bin/busybox", "sh", "-c", a["command"]}, "", ""
	case "create_file":
		if a["path"] == "" {
			return nil, "", "create_file: path required"
		}
		cmd := fmt.Sprintf("mkdir -p \"$(dirname %q)\" && printf '%%s' %q > %q && echo wrote %q",
			a["path"], a["content"], a["path"], a["path"])
		return []string{"/bin/busybox", "sh", "-c", cmd}, "", ""
	case "str_replace":
		if a["path"] == "" || a["old"] == "" {
			return nil, "", "str_replace: path and old required"
		}
		cmd := fmt.Sprintf("sed -i 's|%s|%s|' %q && echo replaced in %q",
			a["old"], a["new"], a["path"], a["path"])
		return []string{"/bin/busybox", "sh", "-c", cmd}, "", ""
	case "view":
		// view lists a directory OR shows a file, matching the PoC view tool.
		if a["path"] == "" {
			return nil, "", "view: path required"
		}
		// -d on a dir would show the dir entry; use a test to pick ls (dir) vs cat (file).
		cmd := fmt.Sprintf("if [ -d %q ]; then ls -la %q; else cat %q; fi", a["path"], a["path"], a["path"])
		return []string{"/bin/busybox", "sh", "-c", cmd}, "", ""
	case "sub_agent":
		// sub_agent runs a full CLI agent (Claude Code/Codex) in the container with
		// working_directory=/home/assistant. The demo image is scratch+busybox and
		// carries no agent CLI, so this is an HONEST refusal, not a fake dispatch —
		// it lights up when a full-tooling sandbox image is wired in.
		return nil, "sub_agent needs a full-tooling sandbox image (agent CLI + /home/assistant); the demo image is scratch+busybox. Wire the tooling image to enable it.", ""
	default:
		return nil, "", "unknown tool: " + tool
	}
}


func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}
