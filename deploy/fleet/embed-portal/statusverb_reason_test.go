// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// Copyright (c) 2025 Open Computer Use Contributors

package main

import (
	"bytes"
	"context"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// Each refusal of the status verb must name itself in the log.
//
// Before this, four branches returned a bare false and the only line the caller
// wrote was "scope pending", which says where and never why: a 403 from
// control, a body that did not parse, and a 200 carrying an empty scope were
// one indistinguishable silence. These cases turn on the REASON text, so a
// version that logs nothing (or logs only the transport error) fails them for
// that reason and not for a general one.
func TestStatusVerbNamesTheRefusal(t *testing.T) {
	cases := []struct {
		name    string
		handler http.HandlerFunc
		want    []string // every fragment must appear in the logged line
	}{
		{
			name: "a refusal carries the status code and control's reason",
			handler: func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(http.StatusForbidden)
				_, _ = w.Write([]byte("caller not permitted for this session_hint"))
			},
			want: []string{"403", "caller not permitted"},
		},
		{
			name: "a body that does not parse says so, and is not read as a miss",
			handler: func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte("{this is not json"))
			},
			want: []string{"decoding"},
		},
		{
			name: "a 200 with no effective_scope is distinguished from a refusal",
			handler: func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(`{"effective_scope":""}`))
			},
			want: []string{"200", "no effective_scope"},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(tc.handler)
			defer srv.Close()

			var logged bytes.Buffer
			prev := log.Writer()
			log.SetOutput(&logged)
			defer log.SetOutput(prev)

			c := config{}
			scope, ok := c.resolveScopeViaStatusVerbURL(context.Background(), srv.URL, "chat-1")
			if ok || scope != "" {
				t.Fatalf("refusal resolved a scope: %q, ok=%v", scope, ok)
			}

			line := logged.String()
			if strings.TrimSpace(line) == "" {
				t.Fatalf("the refusal was silent; the caller can only report "+
					"%q, which is the defect this guards", "scope pending")
			}
			for _, want := range tc.want {
				if !strings.Contains(line, want) {
					t.Errorf("logged line does not name %q: %s", want, strings.TrimSpace(line))
				}
			}
			if !strings.Contains(line, "chat-1") {
				t.Errorf("logged line does not say which chat: %s", strings.TrimSpace(line))
			}
		})
	}
}

// The echoed reason is bounded: a refusal body is short, and an unbounded copy
// would let one refusal pad the operator's log.
func TestStatusVerbReasonIsBounded(t *testing.T) {
	huge := strings.Repeat("x", statusVerbSnippetBytes*8)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(huge))
	}))
	defer srv.Close()

	var logged bytes.Buffer
	prev := log.Writer()
	log.SetOutput(&logged)
	defer log.SetOutput(prev)

	c := config{}
	if _, ok := c.resolveScopeViaStatusVerbURL(context.Background(), srv.URL, "chat-1"); ok {
		t.Fatal("a 500 resolved a scope")
	}

	if got := strings.Count(logged.String(), "x"); got > statusVerbSnippetBytes {
		t.Errorf("logged %d reason bytes, cap is %d", got, statusVerbSnippetBytes)
	}
}
