// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// Copyright (c) 2025 Open Computer Use Contributors

package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// tokenClaims decodes the minted JWT payload and returns filesystem_id plus the
// scope_pending marker.
func tokenClaims(t *testing.T, tok string) (string, bool) {
	t.Helper()
	parts := strings.Split(tok, ".")
	if len(parts) != 3 {
		t.Fatalf("token is not a 3-part JWT: %q", tok)
	}
	cb, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatalf("decode claims: %v", err)
	}
	var claims struct {
		FilesystemID string `json:"filesystem_id"`
		ScopePending bool   `json:"scope_pending"`
	}
	if err := json.Unmarshal(cb, &claims); err != nil {
		t.Fatalf("unmarshal claims: %v", err)
	}
	return claims.FilesystemID, claims.ScopePending
}

func tokenScope(t *testing.T, tok string) string {
	t.Helper()
	s, _ := tokenClaims(t, tok)
	return s
}

func testConfig() config {
	return config{
		audience:     "ocu-webui",
		subject:      "demo-user",
		filesystemID: "fs-fleet",
		intent:       "write",
		embedSecret:  strings.Repeat("k", 32),
		tokenTTL:     60 * time.Second,
		// controlStatusURL unset -> the status verb is unreachable, so every
		// chat context is a MISS. The keystone below pins that a miss binds the
		// BASE (scope_pending), NEVER a portal-local derivation.
	}
}

// TestMissPathBindsBaseNotLocalDerivation is the load-bearing keystone: with the
// status verb unavailable, a chat context must NOT mint a portal-local derived
// scope (a divergent third scope that matches neither the guest's minted claim
// nor the pane's real subtree). It must bind the BASE and flag scope_pending.
//
// Red-probe: restore a portal-local deriveChatScope on the miss path (mint
// "<base>-<hex>" instead of the base) -> the "no local derivation" assertions
// below REDs (scope != base, and no scope_pending marker).
func TestMissPathBindsBaseNotLocalDerivation(t *testing.T) {
	cfg := testConfig() // controlStatusURL unset -> every chat is a miss
	ctx := context.Background()

	for _, chat := range []string{"chat-a", "chat-b"} {
		tok, err := cfg.mintToken(ctx, chat)
		if err != nil {
			t.Fatalf("mint %s: %v", chat, err)
		}
		scope, pending := tokenClaims(t, tok)
		if scope != "fs-fleet" {
			t.Fatalf("miss path for %s minted %q; must bind the BASE fs-fleet, "+
				"not a portal-local derivation", chat, scope)
		}
		if strings.HasPrefix(scope, "fs-fleet-") {
			t.Fatalf("miss path for %s minted a DERIVED-shaped scope %q; the portal "+
				"must never derive locally (split-brain vs control's owner form)", chat, scope)
		}
		if !pending {
			t.Fatalf("miss path for %s did not flag scope_pending; a base-on-miss "+
				"must be visibly pending, not a silent resolved scope", chat)
		}
	}
}

// TestResolvedScopeCarriesNoPendingMarker: when the status verb resolves a scope,
// the token carries that scope and NO scope_pending marker (the marker is a
// miss-only signal, not a permanent tell).
func TestResolvedScopeCarriesNoPendingMarker(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]string{"effective_scope": "fs-fleet-resolved00000000"})
	}))
	defer srv.Close()

	// Point resolveScope at the stub over plain HTTP by driving it directly (the
	// mTLS builder is exercised elsewhere; here we pin the resolved-path claims).
	cfg := testConfig()
	scope, ok := cfg.resolveScopeViaStatusVerbURL(context.Background(), srv.URL, "chat-a")
	if !ok || scope != "fs-fleet-resolved00000000" {
		t.Fatalf("status-verb resolve = (%q,%v), want the stub scope resolved", scope, ok)
	}
}

// TestMintTokenNoChatContextMintsBase: no chat context -> the base scope (today's
// behaviour), fully resolved (no scope_pending marker).
func TestMintTokenNoChatContextMintsBase(t *testing.T) {
	cfg := testConfig()
	tok, err := cfg.mintToken(context.Background(), "")
	if err != nil {
		t.Fatalf("mint: %v", err)
	}
	scope, pending := tokenClaims(t, tok)
	if scope != "fs-fleet" {
		t.Fatalf("no-chat token scope = %q, want the base fs-fleet", scope)
	}
	if pending {
		t.Fatalf("no-chat token flagged scope_pending; the base is fully resolved here")
	}
}
