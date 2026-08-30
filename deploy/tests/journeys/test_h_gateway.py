# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""GROUP H — MCP gateway north auth-edge (H1..H4), fleet-only.

The A..G journey groups enter control's ingress plane directly (127.0.0.1:9466)
because exec and the file-op data path do not flow through the MCP gateway —
architecturally the gateway mints a session (F5 create/destroy/status) and the
exec/data planes are separate. That leaves the ADR-0027 north auth edge — the
sk-ocu- keyed create over the real MCP wire (tools/call, JSON-RPC 2.0,
MCP-Protocol-Version) — uncovered by the journey backend, which srcs control.

This group closes that gap. It drives the REAL gateway on 127.0.0.1:8080 with a
real bearer minted into the boot-set (deploy/fleet/secrets/gateway/boot-set.json
by scripts/mint_boot_set.py) and asserts the four keyed-create boundaries the
gateway enforces before it will forward to control:

  H1  a forged sk-ocu- key   -> 401 at ingress, BEFORE any forward (invariant #9)
  H2  a missing bearer       -> 401 (same unauthenticated class, no leak)
  H3  missing proto-version  -> 400 BEFORE auth (the protocol-version guard)
  H4  a VALID key            -> auth PASSES: the request reaches the F10 audit
                               emit. Without a live audit-bus that emit
                               fail-closes 500 "audit write failed" (NFR-SEC-03:
                               a forward cannot ack without a durable record) —
                               a 500 here PROVES auth passed (a 401 would mean it
                               did not). With an audit-bus up it is a 201. Either
                               is a pass for "the valid key authenticated"; a 401
                               is the only failure.

No poc counterpart: the PoC has no gateway and no keyed auth (chat_id is the
only scoping), so this group is fleet-only and skips loudly on the poc backend
and whenever the gateway is not reachable. It never fabricates a green.
"""

import base64
import json
import subprocess
import uuid
from pathlib import Path

import pytest

# The gateway's north listener, host-mapped in the fleet compose.
GATEWAY_URL = "http://127.0.0.1:8080/"
# The rendered boot-set + the bearer that hashes into it. mint_boot_set.py writes
# boot-set.json and prints the plaintext bearer. _BOOT_SET / _BEARER_FILE come from
# the i-suite, which resolves them from the RUNNING gateway container's mounted
# secrets dir (falling back to this checkout's fleet/secrets/gateway). Reusing that
# resolution means H4 reads the bearer the live stack accepts even when the suite is
# run from a sibling checkout, instead of failing on a stale sibling bearer.
from test_i_mcp_surface import _BOOT_SET, _BEARER_FILE  # noqa: E402  (shared secrets resolution)

_PROTO = "2025-06-18"
_BODY = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {}},
    }
)


def _curl(headers, body=_BODY, timeout=10):
    """POST to the gateway, return (http_status:int, body:str).

    Uses curl (not requests) to match the exact wire the gateway sees and to
    keep this group dependency-free like the demo scripts. Raises for a
    transport failure so an unreachable gateway becomes a loud skip, never a
    silent pass.
    """
    args = ["curl", "-sS", "--max-time", str(timeout), "-o", "-", "-w", "\n%{http_code}", GATEWAY_URL]
    for h in headers:
        args += ["-H", h]
    args += ["-H", "content-type: application/json", "-d", body]
    out = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 5)
    if out.returncode != 0:
        raise RuntimeError(f"curl transport failure rc={out.returncode}: {out.stderr[:200]}")
    text = out.stdout
    nl = text.rfind("\n")
    return int(text[nl + 1 :].strip()), text[:nl]


def _gateway_live():
    """True iff the gateway answers at all (any HTTP status on a bare probe)."""
    try:
        _curl(["MCP-Protocol-Version: " + _PROTO], timeout=5)
        return True
    except Exception:
        return False


def _bearer():
    """The valid minted bearer, or None if the fixture was not rendered."""
    if _BEARER_FILE.exists():
        b = _BEARER_FILE.read_text().strip()
        return b or None
    return None


pytestmark = pytest.mark.fleet


@pytest.fixture(autouse=True)
def _require_gateway():
    if not _BOOT_SET.exists():
        pytest.skip(
            f"gateway boot-set not rendered at {_BOOT_SET} "
            "(run scripts/mint_boot_set.py) — SKIP, not a pass."
        )
    if not _gateway_live():
        pytest.skip(
            f"MCP gateway not reachable at {GATEWAY_URL} "
            "(bring up the mcp-gateway service) — SKIP, not a pass."
        )


def test_h1_forged_key_401_pre_forward():
    """A forged sk-ocu- key is refused 401 at ingress, before any forward."""
    status, body = _curl(
        [
            "MCP-Protocol-Version: " + _PROTO,
            "Authorization: Bearer sk-ocu-wrong-forged-key-not-in-the-boot-set",
        ]
    )
    assert status == 401, f"forged key must 401 at ingress, got {status}: {body[:200]}"
    assert "unauthenticated" in body, f"401 must be the stable unauthenticated class, got {body[:200]}"


def test_h2_missing_key_401():
    """A request with no bearer is refused 401 (same unauthenticated class)."""
    status, body = _curl(["MCP-Protocol-Version: " + _PROTO])
    assert status == 401, f"missing key must 401, got {status}: {body[:200]}"
    assert "unauthenticated" in body, f"401 must be the unauthenticated class, got {body[:200]}"


def test_h3_missing_protocol_version_400_pre_auth():
    """A missing MCP-Protocol-Version is refused 400 BEFORE auth runs.

    The guard sits ahead of auth, so even a valid bearer without the header is
    a 400 — proving the protocol-version gate is pre-auth, not post-auth.
    """
    bearer = _bearer()
    headers = []
    if bearer:
        headers.append("Authorization: Bearer " + bearer)
    status, body = _curl(headers)
    assert status == 400, f"missing proto-version must 400 pre-auth, got {status}: {body[:200]}"


def test_h4_valid_key_authenticates_reaches_forward_or_audit():
    """A VALID key authenticates: the request passes auth and reaches forward.

    Proof: NOT a 401. The only failure is a 401 — that would mean the key did
    not authenticate. Every other status proves auth PASSED and the request
    reached the forward/audit path:
      - 200: a full JSON-RPC result (the fleet is up and the forward returned).
      - 201: create acknowledged with a live audit-bus.
      - 500: audit fail-closed AFTER a successful auth (NFR-SEC-03).
      - 502: forward refused downstream (still post-auth).
    """
    bearer = _bearer()
    if not bearer:
        pytest.skip(
            f"no minted bearer at {_BEARER_FILE} "
            "(mint_boot_set.py prints it; write it there) — SKIP, not a pass."
        )
    status, body = _curl(
        [
            "MCP-Protocol-Version: " + _PROTO,
            "Authorization: Bearer " + bearer,
        ]
    )
    assert status != 401, (
        f"valid key must authenticate (not 401), got 401: {body[:200]}"
    )
    assert status in (200, 201, 500, 502), (
        f"valid key should authenticate and reach forward/audit (200 JSON-RPC "
        f"result, 201 create-ack, 500 audit fail-closed, or 502 forward-refused), "
        f"got {status}: {body[:200]}"
    )


def _bash_tool_body(chat_id, command):
    """A tools/call bash_tool JSON-RPC body — the exact shape the browser sends."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "bash_tool", "arguments": {"command": command}},
        }
    )


def _decode_tool_text(body):
    """Return the decoded content[0].text of an MCP tools/call result, or None.

    The gateway projects the guest's stdout into a CallToolResult; the text is
    already UTF-8 in content[0].text (not base64 at the MCP layer). Returns None
    if the body is a JSON-RPC error (forward refused) or has no text content, so
    the caller distinguishes a real result from a refusal.
    """
    try:
        doc = json.loads(body)
    except (ValueError, TypeError):
        return None
    if "error" in doc:
        return None
    content = doc.get("result", {}).get("content") or []
    for item in content:
        if item.get("type") == "text":
            return item.get("text")
    return None


def test_h5_cold_bash_tool_first_call_returns_output():
    """A COLD bash_tool call — fresh chat, no pre-existing session — succeeds on
    the FIRST forward with real decoded stdout.

    This is the cycle a user drives from the browser: open a NEW chat, type a
    command, get output. It is cold BY CONSTRUCTION — a random chat-id the
    gateway has never keyed a session_hint from, and the conftest per-test
    teardown (revoke/all + docker rm ocu-sess-* + resume/all) guarantees no row
    or guest container survives into this test. So the gateway's create hop
    materializes a fresh guest, and the exec hop runs against a guest whose
    exec.sock is still coming up (FUSE mount + boot-child, ~0.5-0.7s cold).

    The bug this pins: the gateway fires the exec hop ~immediately after create
    returns, before the guest is exec-ready; control answers a transient 409;
    the gateway maps it to "forward refused" (-32603). Every FIRST call fails; a
    warm retry (same chat resumes an already-booted guest) succeeds — which is
    exactly how a warm-guest false-green hid this. The fix makes control wait for
    the sock on an ACTIVE-and-owned row instead of an instant 409.

    Freshness-by-construction (random chat-id + no-pre-existing precondition) is
    what makes a warm false-green structurally impossible: a reused hint is how
    the earlier "proven live" lied. ZERO warm-up, ONE call, assert first-call
    success with the unique marker in the decoded output.
    """
    bearer = _bearer()
    if not bearer:
        pytest.skip(
            f"no minted bearer at {_BEARER_FILE} "
            "(mint_boot_set.py prints it; write it there) — SKIP, not a pass."
        )

    # A chat-id the gateway has never seen: the session_hint it derives is unique
    # to this run, so the create hop cannot resume a pre-warmed guest.
    chat_id = "cold-h5-" + uuid.uuid4().hex
    marker = "OCU_COLD_H5_" + uuid.uuid4().hex[:12]
    command = f"echo {marker}"

    status, body = _curl(
        [
            "MCP-Protocol-Version: " + _PROTO,
            "Authorization: Bearer " + bearer,
            "X-Chat-Id: " + chat_id,
        ],
        body=_bash_tool_body(chat_id, command),
        # Generous transport budget so a slow cold boot is a real result, never a
        # curl timeout masquerading as a failure — the assertion is about the
        # FIRST forward's outcome, not the wall-clock.
        timeout=30,
    )

    text = _decode_tool_text(body)
    assert status == 200 and text is not None, (
        "cold first-call bash_tool must return a tool result on the FIRST forward "
        f"(no warm-up), got HTTP {status}: {body[:300]}. A 'forward refused' here "
        "is the cold-exec race: control 409s while the guest's exec.sock is still "
        "coming up, and the gateway does not wait/retry."
    )
    assert marker in text, (
        f"decoded stdout must carry the unique marker {marker!r} (proving the real "
        f"guest ran the command, not a fabricated green), got: {text!r}"
    )
    # Guard against a base64-echo false-green: the marker must be the LITERAL
    # command output, not the command string reflected back encoded.
    assert base64.b64encode(marker.encode()).decode() not in text, (
        "marker appears only base64-encoded — that is an echo of the request, "
        "not decoded guest stdout"
    )
