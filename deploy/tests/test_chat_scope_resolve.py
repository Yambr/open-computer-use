# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""D5 per-chat scope-resolve keystone (openwebui tool).

The OpenWebUI tool resolves its chat's storage scope by calling the gateway's
synthetic `resolve_scope` MCP tool (a JSON-RPC tools/call on the SAME /mcp
endpoint the bash tool uses, with bearer + MCP-Protocol-Version + X-Chat-Id).
The gateway returns a CallToolResult whose single text block is JSON
{"effective_scope": "<base>-<hex>"}. The tool reads that value; it NEVER derives
the scope handle locally - the attested owner form is control-only (ADR-0030, D5).

These tests drive the REAL _resolve_chat_scope path with a mocked HTTP transport:
- two chats whose resolve_scope tool returns distinct derived scopes resolve to
  DISTINCT scopes (the load-bearing isolation property);
- an EXPLICIT empty effective_scope (control ran without -derive-chat-scope)
  degrades to the base OCU_FILESYSTEM_ID (today's behaviour);
- a 202/empty body (the dead-wire fake-green the Fable review found) degrades to
  the base but is FLAGGED as a miss, never treated as a resolved base scope.

Red-probe (per keystone):
- feed the OLD REST-path 202/empty shape -> the tool must DEGRADE-WITH-FLAG, not
  silently succeed; the debug flag proves it went down the miss path;
- feed a real {"effective_scope": "fs-fleet-abc..."} CallToolResult -> the tool
  returns THAT scope, not the base. If _resolve_chat_scope ignored the response
  and always returned the base, the distinct-scope assertion REDs.
"""

import asyncio
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

_TOOLS_DIR = Path(__file__).resolve().parents[2] / "openwebui" / "tools"
sys.path.insert(0, str(_TOOLS_DIR))

import computer_use_tools as m  # noqa: E402


class _FakeResp:
    """Minimal urlopen context-manager stand-in over a raw body string."""

    def __init__(self, status, raw):
        self.status = status
        self._body = raw.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _call_tool_result(effective_scope):
    """A resolve_scope CallToolResult: result.content = one text block whose text
    is JSON carrying effective_scope (the exact wire the gateway emits)."""
    inner = json.dumps({"effective_scope": effective_scope})
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": inner}], "isError": False},
        }
    )


@contextmanager
def _resolve_verb(by_chat):
    """Patch urlopen so each tools/call resolve_scope POST returns the raw body
    keyed by the request's X-Chat-Id. Verifies the tool actually speaks the MCP
    wire: hits /mcp, sends a resolve_scope tools/call body, carries X-Chat-Id and
    the MCP-Protocol-Version header."""

    def fake_urlopen(req, timeout=None):
        assert req.full_url.endswith("/mcp"), f"must POST the MCP endpoint, got {req.full_url}"
        assert req.get_header("Mcp-protocol-version"), "MCP-Protocol-Version header required"
        body = json.loads(req.data.decode("utf-8"))
        assert body["method"] == "tools/call", "must be a tools/call"
        assert body["params"]["name"] == "resolve_scope", "must call resolve_scope"
        chat = req.get_header("X-chat-id")  # urllib title-cases header keys
        status, raw = by_chat[chat]
        return _FakeResp(status, raw)

    with mock.patch.object(m.urllib.request, "urlopen", fake_urlopen):
        yield


def _new_tool(base="fs-fleet"):
    t = m.Tools()
    t.valves.OCU_FILESYSTEM_ID = base
    t.valves.ORCHESTRATOR_URL = "http://mcp-gateway:8080"
    t.valves.MCP_API_KEY = "sk-ocu-test"
    t.valves.DEBUG_LOGGING = True
    return t


def test_two_chats_resolve_distinct_derived_scopes():
    t = _new_tool()
    responses = {
        "chat-a": (200, _call_tool_result("fs-fleet-aaaa000011112222")),
        "chat-b": (200, _call_tool_result("fs-fleet-bbbb333344445555")),
    }
    with _resolve_verb(responses):
        scope_a = asyncio.run(t._resolve_chat_scope("chat-a"))
        scope_b = asyncio.run(t._resolve_chat_scope("chat-b"))

    assert scope_a == "fs-fleet-aaaa000011112222"
    assert scope_b == "fs-fleet-bbbb333344445555"
    # The load-bearing property: two chats -> two distinct resolved scopes.
    assert scope_a != scope_b, "per-chat scopes must be distinct"
    # And neither is the bare base (derivation is on).
    assert scope_a != "fs-fleet" and scope_b != "fs-fleet"


def test_explicit_empty_scope_degrades_to_base_with_flag(capsys):
    """control ran WITHOUT -derive-chat-scope: the CallToolResult carries an
    EXPLICIT empty effective_scope. That degrades to the base, and the debug
    flag proves the miss path ran (not a silent success)."""
    t = _new_tool()
    responses = {"chat-x": (200, _call_tool_result(""))}
    with _resolve_verb(responses):
        scope = asyncio.run(t._resolve_chat_scope("chat-x"))
    assert scope == "fs-fleet", "an explicit empty effective_scope must degrade to the base"
    out = capsys.readouterr().out
    assert "[SCOPE]" in out and "explicitly empty" in out, (
        "the explicit-empty degrade must be FLAGGED in debug, not silent"
    )


def test_dead_wire_202_empty_body_degrades_with_flag_not_silent(capsys):
    """The Fable-review fake-green: the OLD REST path returned a 202 with an
    EMPTY body. That must degrade to the base but be FLAGGED as a miss - NOT
    treated as a resolved base scope. The debug flag naming 'empty body' is the
    proof it went down the miss path, not a success path that happened to equal
    the base."""
    t = _new_tool()

    def fake_urlopen(req, timeout=None):
        return _FakeResp(202, "")  # 202, no CallToolResult - the dead wire

    with mock.patch.object(m.urllib.request, "urlopen", fake_urlopen):
        scope = asyncio.run(t._resolve_chat_scope("chat-dead"))
    assert scope == "fs-fleet", "a 202/empty must degrade to the base"
    out = capsys.readouterr().out
    assert "[SCOPE]" in out and "empty body" in out, (
        "a 202/empty must be FLAGGED as a miss (dead wire), never a silent base"
    )


def test_jsonrpc_error_degrades_with_flag(capsys):
    t = _new_tool()
    err = json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "no such tool"}})

    def fake_urlopen(req, timeout=None):
        return _FakeResp(200, err)

    with mock.patch.object(m.urllib.request, "urlopen", fake_urlopen):
        scope = asyncio.run(t._resolve_chat_scope("chat-jr"))
    assert scope == "fs-fleet"
    out = capsys.readouterr().out
    assert "[SCOPE]" in out, "a JSON-RPC error must be flagged, not silent"


def test_transport_error_degrades_to_base():
    t = _new_tool()

    def boom(req, timeout=None):
        raise OSError("connection refused")

    with mock.patch.object(m.urllib.request, "urlopen", boom):
        scope = asyncio.run(t._resolve_chat_scope("chat-err"))
    assert scope == "fs-fleet", "a resolve miss must not break the upload path"


def test_scope_is_cached_per_chat():
    t = _new_tool()
    calls = {"n": 0}

    def counting(req, timeout=None):
        calls["n"] += 1
        return _FakeResp(200, _call_tool_result("fs-fleet-deadbeefdeadbeef"))

    with mock.patch.object(m.urllib.request, "urlopen", counting):
        first = asyncio.run(t._resolve_chat_scope("chat-c"))
        second = asyncio.run(t._resolve_chat_scope("chat-c"))
    assert first == second == "fs-fleet-deadbeefdeadbeef"
    assert calls["n"] == 1, "the resolve verb is hit once per chat, then cached"
