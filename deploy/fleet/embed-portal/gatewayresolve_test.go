// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// Copyright (c) 2025 Open Computer Use Contributors

package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The portal must reach a per-chat scope through the session's OWNER.
//
// Control's status verb is caller-scoped: it answers 404 for a session the caller
// does not own, so a portal that owns nothing gets a miss on every chat and binds
// the base scope -- every chat's objects at once, under a panel titled for one
// chat. The gateway owns the session and answers the same question through
// resolve_scope. These cases turn on that second source being consulted and
// believed; without it the portal is correct only when it has nothing to resolve.

// gatewayStub answers one tools/call the way the gateway does: a JSON-RPC result
// whose CallToolResult carries a single text block of {"effective_scope": ...}.
// It records the request so a case can assert what actually crossed the boundary.
type gatewayStub struct {
	scope      string
	isError    bool
	status     int
	gotAuth    string
	gotChatID  string
	gotToolRaw string
	calls      int
}

func (g *gatewayStub) server(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		g.calls++
		g.gotAuth = r.Header.Get("Authorization")
		g.gotChatID = r.Header.Get("X-Chat-Id")
		var body struct {
			Params struct {
				Name string `json:"name"`
			} `json:"params"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		g.gotToolRaw = body.Params.Name

		if g.status != 0 && g.status != http.StatusOK {
			w.WriteHeader(g.status)
			return
		}
		inner, _ := json.Marshal(map[string]string{"effective_scope": g.scope})
		_ = json.NewEncoder(w).Encode(map[string]any{
			"jsonrpc": "2.0",
			"id":      1,
			"result": map[string]any{
				"content": []map[string]string{{"type": "text", "text": string(inner)}},
				"isError": g.isError,
			},
		})
	}))
}

// bearerFile writes a bearer to a temp file and returns its path. The portal
// reads the credential from a PATH, never from the environment, so the test
// exercises the same seam production uses.
func bearerFile(t *testing.T, value string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "bearer.txt")
	if err := os.WriteFile(p, []byte(value+"\n"), 0o600); err != nil {
		t.Fatalf("write bearer file: %v", err)
	}
	return p
}

func TestGatewayResolveReturnsTheChatsScope(t *testing.T) {
	stub := &gatewayStub{scope: "fs-fleet-735aab67ab56ebb9"}
	srv := stub.server(t)
	defer srv.Close()

	cfg := failClosedConfig("")
	cfg.gatewayURL = srv.URL
	cfg.gatewayBearerFile = bearerFile(t, "sk-ocu-portal-resolve-only")

	got, ok := cfg.resolveScope(context.Background(), "chat-a")
	if !ok {
		t.Fatalf("chat did not resolve; scope=%q", got)
	}
	if got != "fs-fleet-735aab67ab56ebb9" {
		t.Errorf("scope = %q, want the gateway's effective_scope", got)
	}

	// What crossed the boundary matters as much as the answer: the chat must
	// travel as the session hint, and the tool asked for must be the resolve-only
	// one. A portal that asked for anything else could not hold a restricted
	// credential.
	if stub.gotChatID != "chat-a" {
		t.Errorf("X-Chat-Id = %q, want the chat", stub.gotChatID)
	}
	if stub.gotToolRaw != "resolve_scope" {
		t.Errorf("tool asked for = %q, want resolve_scope", stub.gotToolRaw)
	}
	if !strings.HasPrefix(stub.gotAuth, "Bearer ") {
		t.Errorf("Authorization = %q, want a bearer", stub.gotAuth)
	}
	if strings.Contains(stub.gotAuth, "\n") {
		t.Error("the bearer carried the file's trailing newline into the header")
	}
}

func TestGatewayResolveIsReachedOnlyAfterTheStatusVerbMisses(t *testing.T) {
	// The status verb stays the first source: where it answers, the gateway must
	// not be consulted at all. Without this the change would silently reroute a
	// working deployment onto a second credential.
	stub := &gatewayStub{scope: "fs-fleet-fromgateway"}
	srv := stub.server(t)
	defer srv.Close()

	cfg := failClosedConfig("")
	cfg.gatewayURL = srv.URL
	cfg.gatewayBearerFile = bearerFile(t, "sk-ocu-portal-resolve-only")
	cfg.resolveOverride = func(_ context.Context, _ string) (string, bool) {
		return "fs-fleet-fromstatusverb", true
	}

	got, ok := cfg.resolveScope(context.Background(), "chat-a")
	if !ok || got != "fs-fleet-fromstatusverb" {
		t.Errorf("scope = %q (resolved=%v), want the status verb's answer", got, ok)
	}
	if stub.calls != 0 {
		t.Errorf("gateway was called %d times though the status verb answered", stub.calls)
	}
}

func TestGatewayResolveFailsClosedOnAnErrorResult(t *testing.T) {
	// A tool result flagged isError carries no scope worth binding. Falling back
	// to the flagged base is correct; binding whatever string came back is not.
	stub := &gatewayStub{scope: "fs-fleet-should-not-be-used", isError: true}
	srv := stub.server(t)
	defer srv.Close()

	cfg := failClosedConfig("")
	cfg.gatewayURL = srv.URL
	cfg.gatewayBearerFile = bearerFile(t, "sk-ocu-portal-resolve-only")

	got, ok := cfg.resolveScope(context.Background(), "chat-a")
	if ok {
		t.Errorf("an error result resolved to %q", got)
	}
	if got != cfg.filesystemID {
		t.Errorf("fallback scope = %q, want the base %q", got, cfg.filesystemID)
	}
}

func TestGatewayResolveFailsClosedOnARefusedCredential(t *testing.T) {
	// The shape a restricted credential produces when the restriction is wrong:
	// the gateway refuses. The portal must degrade to the flagged base, never
	// raise and never invent a scope.
	stub := &gatewayStub{status: http.StatusForbidden}
	srv := stub.server(t)
	defer srv.Close()

	cfg := failClosedConfig("")
	cfg.gatewayURL = srv.URL
	cfg.gatewayBearerFile = bearerFile(t, "sk-ocu-portal-resolve-only")

	got, ok := cfg.resolveScope(context.Background(), "chat-a")
	if ok {
		t.Errorf("a refused credential resolved to %q", got)
	}
	if got != cfg.filesystemID {
		t.Errorf("fallback scope = %q, want the base %q", got, cfg.filesystemID)
	}
}

func TestGatewayResolveIsNotAttemptedWithoutABearer(t *testing.T) {
	// Known-positive control on the credential seam: with no bearer file the
	// portal must not call the gateway at all. Without this, a build that sent an
	// empty Authorization header would still pass the cases above by falling back.
	stub := &gatewayStub{scope: "fs-fleet-unreachable"}
	srv := stub.server(t)
	defer srv.Close()

	cfg := failClosedConfig("")
	cfg.gatewayURL = srv.URL // configured, but no credential

	if _, ok := cfg.resolveScope(context.Background(), "chat-a"); ok {
		t.Error("resolved a chat with no credential configured")
	}
	if stub.calls != 0 {
		t.Errorf("gateway was called %d times with no credential", stub.calls)
	}
}

func TestChatlessEmbedNeverConsultsTheGateway(t *testing.T) {
	// Known-positive control on the chat seam: with no chat named, the base IS the
	// resolved answer and no resolution is needed. A build that called the gateway
	// unconditionally would burn a request per chatless embed.
	stub := &gatewayStub{scope: "fs-fleet-unreachable"}
	srv := stub.server(t)
	defer srv.Close()

	cfg := failClosedConfig("")
	cfg.gatewayURL = srv.URL
	cfg.gatewayBearerFile = bearerFile(t, "sk-ocu-portal-resolve-only")

	got, ok := cfg.resolveScope(context.Background(), "")
	if !ok || got != cfg.filesystemID {
		t.Errorf("chatless embed = (%q,%v), want the base resolved", got, ok)
	}
	if stub.calls != 0 {
		t.Errorf("gateway was called %d times for a chatless embed", stub.calls)
	}
}

func TestTokenRouteServesAChatTheGatewayResolves(t *testing.T) {
	// The whole point, at the route: a named chat that only the gateway can
	// resolve must now mint rather than answer 409 scope_pending.
	stub := &gatewayStub{scope: "fs-fleet-735aab67ab56ebb9"}
	srv := stub.server(t)
	defer srv.Close()

	cfg := failClosedConfig("")
	cfg.gatewayURL = srv.URL
	cfg.gatewayBearerFile = bearerFile(t, "sk-ocu-portal-resolve-only")

	portal := httptest.NewServer(newMux(cfg))
	defer portal.Close()

	resp, err := http.Get(portal.URL + "/token?chat=chat-a")
	if err != nil {
		t.Fatalf("GET /token: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200 — the gateway resolved this chat", resp.StatusCode)
	}
	var body map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body["token"] == "" {
		t.Error("no token minted for a gateway-resolved chat")
	}
}
