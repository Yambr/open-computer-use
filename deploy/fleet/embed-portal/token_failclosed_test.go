// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// Copyright (c) 2025 Open Computer Use Contributors

package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// A named chat whose scope does not resolve must be refused, not answered with a
// base-scope token.
//
// The base scope is every chat's objects at once. Handing it back for a NAMED
// chat answers "the files for this chat" with somebody else's -- measured on the
// stand: 923 objects from every chat and every past test run, under a panel
// titled for the chat in front of the user. These cases turn on the refusal, so
// the previous behaviour (mint the base, flag it in a claim nobody reads) fails
// them for that and not for a general reason.

func failClosedConfig(statusURL string) config {
	return config{
		listen:           ":0",
		paneOrigin:       "http://pane.invalid",
		embedSecret:      strings.Repeat("k", 32),
		audience:         "ocu-webui",
		subject:          "demo-user",
		filesystemID:     "fs-fleet",
		intent:           "write",
		tokenTTL:         60 * time.Second,
		controlStatusURL: statusURL,
	}
}

func TestTokenRouteRefusesAnUnresolvedChat(t *testing.T) {
	// No status URL: every chat is a miss, which is exactly the stand's state
	// while the scope question is unresolved.
	srv := httptest.NewServer(newMux(failClosedConfig("")))
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/token?chat=chat-a")
	if err != nil {
		t.Fatalf("GET /token: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusOK {
		var body map[string]string
		_ = json.NewDecoder(resp.Body).Decode(&body)
		if body["token"] != "" {
			t.Fatalf("a named chat with no resolved scope was handed a token; "+
				"that token carries the base scope, which is every chat's files "+
				"(status %d)", resp.StatusCode)
		}
	}
	if resp.StatusCode != http.StatusConflict {
		t.Errorf("status = %d, want %d", resp.StatusCode, http.StatusConflict)
	}

	var body map[string]string
	_ = json.NewDecoder(resp.Body).Decode(&body)
	if body["error"] != "scope_pending" {
		t.Errorf("refusal does not name itself: %+v", body)
	}
}

func TestTokenRouteStillServesWithNoChatContext(t *testing.T) {
	// Known-positive control: with no chat named, the base IS the correct answer
	// and the route must keep working. Without this, a refusal that fired on
	// everything would pass the case above while breaking the portal.
	srv := httptest.NewServer(newMux(failClosedConfig("")))
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/token")
	if err != nil {
		t.Fatalf("GET /token: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	var body map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body["token"] == "" {
		t.Error("no token minted for a chatless embed")
	}
}

func TestTokenRouteServesAResolvedChat(t *testing.T) {
	// The other known-positive: when control DOES resolve the chat, the route
	// must mint. A refusal that fired regardless would make the fix useless the
	// day the scope question is settled.
	cfg := failClosedConfig("")
	cfg.resolveOverride = func(_ context.Context, _ string) (string, bool) {
		return "fs-fleet-0123456789abcdef", true
	}

	srv := httptest.NewServer(newMux(cfg))
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/token?chat=chat-a")
	if err != nil {
		t.Fatalf("GET /token: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("a resolved chat was refused: status %d", resp.StatusCode)
	}
}
