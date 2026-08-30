# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""GROUP J -- two-way user<->agent file flow across the storage spine, fleet-only.

The finale proved the chat tool cycle; this group pins the FILE cycle between
the chat guest and the user's Files panel under the TWO-MOUNT guest layout
(PoC parity + ADR-0029: /mnt/user-data/uploads RO + /mnt/user-data/outputs RW):

  J1  agent-written /mnt/user-data/outputs file reaches the user: pane lists
      it and serves its exact bytes (agent -> outputs/ -> F9 north -> download)
  J2  user-uploaded file reaches the agent: a pane upload is readable, byte
      exact, from a fresh guest at /mnt/user-data/uploads (F9 create ->
      uploads/ -> south mount read)
  J3  the north egress gate survives both legs: an uploads-side object is
      still refused for download (not-downloadable), while the agent's
      outputs-side deliverable serves 200 - the asymmetry IS the control
  J4  the agent LISTS its own deliverable: a file written to outputs/ shows
      in the guest's own `ls /mnt/user-data/outputs` and cats back byte-exact
      (the list-own-writes keystone the flat single-mount era broke)
  J5  the uploads view refuses writes: a guest write into
      /mnt/user-data/uploads fails AND never surfaces in the pane list (the
      RO keystone - mount posture and engine lease agree)

It drives the REAL wires end to end: the gateway on 127.0.0.1:8080 with the
minted bearer (like groups H/I) for the guest side, and the embed-portal
(127.0.0.1:3003) + File Pane BFF (127.0.0.1:3000) for the user side. Writes
through the guest mount are ASYNC (VFS write-back, seconds); assertions poll
with a bounded deadline instead of sleeping blind. Skips loudly when a wire is
unreachable - never a fabricated green.

PoC counterpart: docker_manager.py binds /mnt/user-data/uploads (ro) +
/mnt/user-data/outputs (rw); this group pins the same guest contract on the
fleet spine. Scenario rows live in scenarios.yaml (J1..J5).
"""

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import pytest

GATEWAY_URL = "http://127.0.0.1:8080/"
PORTAL_TOKEN_URL = "http://127.0.0.1:3003/token"
PANE_URL = "http://127.0.0.1:3000"
_PROTO = "2025-06-18"

pytestmark = pytest.mark.fleet

from test_i_mcp_surface import _bash_body, _bearer, _call  # noqa: E402  (same wire)


# --- user-side (pane) wire helpers -----------------------------------------


def _curl_json(args, timeout=15):
    """Run curl, return (status:int, body:str). Transport failure raises."""
    out = subprocess.run(
        ["curl", "-sS", "--max-time", str(timeout), "-o", "-", "-w", "\n%{http_code}"]
        + args,
        capture_output=True,
        text=True,
        timeout=timeout + 10,
    )
    if out.returncode != 0:
        raise RuntimeError(f"curl transport failure rc={out.returncode}: {out.stderr[:200]}")
    text = out.stdout
    nl = text.rfind("\n")
    return int(text[nl + 1 :].strip()), text[:nl]


def _pane_session(tmp_path, chat_id=None):
    """Portal token -> pane bootstrap. Returns (cookie_jar_path, csrf_token).

    Skips loudly when the portal or the pane is down: the user leg cannot be
    proven without the real browser-facing wires, and is never mocked green.
    """
    # DECLARED expectation, distinct from an environment failure: on the
    # published-artifact path (the keystone runner sets OCU_PUBLISHED_PATH)
    # the canonical published webui image inlines the CLOSED
    # NEXT_PUBLIC_OCU_PARENT_ORIGIN default, so the pane bootstrap is dead BY
    # DESIGN - these legs are expected-closed there, never a mystery red and
    # never a silent green. The marker lifts when runtime parent-origin
    # config lands in ocu-webui.
    if os.environ.get("OCU_PUBLISHED_PATH"):
        pytest.skip(
            "expected-closed on the published path: the canonical published "
            "webui inlines the CLOSED parent-origin default, pane bootstrap "
            "cannot complete by design (lifts with runtime parent-origin "
            "config in ocu-webui)"
        )
    jar = str(tmp_path / "pane-cookies.txt")
    try:
        # A chat id binds the minted token to THAT chat's storage scope.
        # Without it the portal mints the base scope, and under per-chat
        # isolation a base-scope pane cannot see a chat's own objects.
        _url = PORTAL_TOKEN_URL + (f"?chat={chat_id}" if chat_id else "")
        status, body = _curl_json([_url])
    except RuntimeError:
        pytest.skip("embed-portal (127.0.0.1:3003) unreachable - user leg cannot run. LOUD SKIP, not a pass.")
    if status != 200:
        pytest.skip(f"embed-portal /token returned {status} - user leg cannot run. LOUD SKIP, not a pass.")
    token = json.loads(body)["token"]
    status, body = _curl_json(
        ["-c", jar, "-X", "POST", "-H", f"Authorization: Bearer {token}",
         f"{PANE_URL}/api/auth/embed-token"]
    )
    if status != 200:
        pytest.skip(f"pane bootstrap returned {status} - user leg cannot run. LOUD SKIP, not a pass.")
    payload = json.loads(body)
    csrf = payload.get("csrfToken", "")
    global _PANE_SCOPE
    _PANE_SCOPE = payload.get("chatScope", "")
    _unlock_secure_cookies_for_loopback(jar)
    return jar, csrf


# The chat scope the bootstrap attested. The pane names its session cookie
# per chat scope (ocu_webui_session_<hash(scope)>) and the gate derives the
# EXPECTED name from the x-ocu-chat-scope request header, so every authed
# pane call must carry the header or the gate looks up the wrong cookie and
# 401s. The pane's own client sends it on every call; the curl harness must
# do the same.
_PANE_SCOPE = ""


def _pane_scope_headers():
    return ["-H", f"x-ocu-chat-scope: {_PANE_SCOPE}"] if _PANE_SCOPE else []


def _unlock_secure_cookies_for_loopback(jar):
    """Replay the pane's Secure session cookie over plain-HTTP loopback.

    The pane sets its session cookie ``Secure; SameSite=None`` for the HTTPS
    iframe deployment. Browsers treat http://127.0.0.1 as a trustworthy
    origin and DO store+send Secure cookies there (the loopback exemption in
    the Secure Contexts spec); curl has no such exemption -- it stores the
    cookie in the jar but refuses to send it back over http://, so every
    authed pane call 401s as a pure transport artifact. Flipping the secure
    column for loopback entries in the Netscape jar reproduces the browser's
    documented policy, nothing more: the cookie value, session, and CSRF pair
    stay exactly what the pane minted.
    """
    p = Path(jar)
    lines = []
    for line in p.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) == 7 and "127.0.0.1" in fields[0] and fields[3] == "TRUE":
            fields[3] = "FALSE"
            line = "\t".join(fields)
        lines.append(line)
    p.write_text("\n".join(lines) + "\n")


def _pane_list(jar):
    status, body = _curl_json(
        ["-b", jar, *_pane_scope_headers(), f"{PANE_URL}/api/v1/files"]
    )
    assert status == 200, f"pane list status = {status}, want 200"
    return json.loads(body)["data"]


# Shared xfail reason for the J-group pane-list-reader tests blocked by defect #182
# (F9 list sorts ascending CreatedAt + the pane fetches page-1 only, so a
# just-written file is off page-1 once the scope holds >=100 objects). Mirrors the
# M-group's marker; j8 is the canonical J-group #182 keystone. When the order=desc
# fix ships (ADR-0031 amends 0028), these XPASS and strict=True forces removal.
_J182_XFAIL_REASON = (
    "task #182: the F9 list sorts ASCENDING CreatedAt and the pane fetches only "
    "page-1, so a just-written file (the newest) is off page-1 once the scope holds "
    ">=100 objects -- a positive pane-find of a new file never resolves. Fix: "
    "additive order=asc|desc param, pane sends desc (ADR-0031). XPASSes when that "
    "ships; strict=True then forces this marker's removal."
)


def _ensure_scope_saturated_for_182(jar, csrf):
    """Make the #182 condition DETERMINISTIC for the xfail-marked pane-list tests:
    the scope must hold >= 100 objects so a just-written file sorts onto page-2+ and
    the pane's page-1-only list never shows it. The shared fs-fleet scope usually
    already carries >=100 from accumulated runs; this pads only if under-populated.
    Without it the xfail could flake to XPASS on a rare under-100 scope and strict=
    True would (correctly) fail -- the guard keeps the marker honest. Mirrors j8."""
    PAGE = 100
    current = len(_pane_list(jar))
    need = max(0, (PAGE + 5) - current)
    for i in range(need):
        _pane_upload(jar, csrf, f"j182-pad-{i:03d}-{uuid.uuid4().hex[:8]}.txt", f"pad{i}")
    saturated = len(_pane_list(jar))
    assert saturated >= PAGE, (
        f"could not saturate the scope past {PAGE} objects (have {saturated}) -- the "
        "#182 blindness is only reachable at >=100; an under-populated scope would "
        "make the xfail vacuously XPASS"
    )


def _pane_find(jar, filename, deadline_s=45):
    """Poll the pane list until filename appears (guest writes are async
    VFS write-back) or the deadline passes; returns the FileObject or None."""
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        hit = [f for f in _pane_list(jar) if f.get("filename") == filename]
        if hit:
            return hit[0]
        time.sleep(3)
    return None


def _pane_content(jar, file_id):
    return _curl_json(
        ["-b", jar, *_pane_scope_headers(), f"{PANE_URL}/api/v1/files/{file_id}/content"]
    )


def _pane_upload(jar, csrf, filename, content, mime="text/plain"):
    status, body = _curl_json(
        ["-b", jar, "-X", "POST",
         *_pane_scope_headers(),
         "-H", f"x-csrf-token: {csrf}",
         "-H", f"x-filename: {filename}",
         "-H", f"Content-Type: {mime}",
         "--data-binary", content,
         f"{PANE_URL}/api/v1/files"]
    )
    assert status == 200, f"pane upload status = {status}, want 200: {body[:200]}"
    return json.loads(body)


# --- guest-side helper -------------------------------------------------------


def _require_gateway():
    if _bearer() is None:
        pytest.skip("boot-set/bearer not rendered - see README re-mint runbook. LOUD SKIP, not a pass.")
    try:
        status, _ = _call(f"j-probe-{uuid.uuid4().hex[:8]}", _bash_body("true"))
    except RuntimeError:
        pytest.skip("gateway (127.0.0.1:8080) unreachable - guest leg cannot run. LOUD SKIP, not a pass.")
    if status == 401:
        pytest.fail(
            "gateway (127.0.0.1:8080) returned 401 for the rendered bearer: the bearer "
            "does not match the running gateway's boot-set (run from the stage tree whose "
            "secrets the live stack mounts, or re-mint the boot-set). A reachable-but-401 "
            "gateway is a harness desync, not a skip - it silently hid the whole file-flow leg."
        )


def _guest_bash(chat_id, command, timeout=60):
    status, parsed = _call(chat_id, _bash_body(command), timeout=timeout)
    assert status == 200, f"bash_tool transport status = {status}, want 200"
    result = parsed["result"]
    text = "".join(b.get("text", "") for b in result.get("content", []))
    return result.get("isError", False), text


def _resolve_scope(chat_id, timeout=15):
    """Resolve a chat's effective storage scope via the gateway's synthetic
    resolve_scope MCP tool. This is a real tools/call on the SAME endpoint the
    guest bash tool uses (bearer + MCP-Protocol-Version + X-Chat-Id); the body is
    ACTUALLY sent (the earlier version built a JSON-RPC body then sent "{}"). The
    gateway ensures/creates the chat's session (the create hop lives INSIDE this
    call, so resolving chat B before B has run a guest command is fine) and
    returns a CallToolResult whose single text block is JSON
    {"effective_scope": "<base>-<hex>"}.

    Returns effective_scope (possibly "") or None on a transport/JSON-RPC/parse
    miss. This is what makes J6 non-vacuous: the two chats must resolve DISTINCT
    derived scopes, else "B does not see A" could be green for an unrelated reason.
    """
    bearer = _bearer()
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "resolve_scope", "arguments": {}},
        }
    )
    out = subprocess.run(
        ["curl", "-sS", "--max-time", str(timeout), "-o", "-", "-w", "\n%{http_code}",
         GATEWAY_URL,
         "-H", f"Authorization: Bearer {bearer}",
         "-H", f"MCP-Protocol-Version: {_PROTO}",
         "-H", f"X-Chat-Id: {chat_id}",
         "-H", "content-type: application/json",
         "-d", body],
        capture_output=True, text=True, timeout=timeout + 10,
    )
    if out.returncode != 0:
        return None
    text = out.stdout
    nl = text.rfind("\n")
    status = text[nl + 1:].strip()
    if status != "200":
        return None
    try:
        parsed = json.loads(text[:nl])
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict) or "error" in parsed:
        return None
    result = parsed.get("result")
    if not isinstance(result, dict):
        return None
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                inner = json.loads(item.get("text", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(inner, dict) and "effective_scope" in inner:
                sc = inner.get("effective_scope")
                if isinstance(sc, str):
                    return sc
    return None


_COMPOSE_FILE = (
    Path(__file__).resolve().parents[2] / "fleet" / "docker-compose.fleet.yml"
)


def _derivation_expected_on():
    """True when the CONTROL THE SUITE IS TALKING TO runs -derive-chat-scope on,
    so per-chat isolation is EXPECTED and equal/empty scopes are a FAILURE, not
    a skip. False in the degrade case (J7) or when the mode cannot be
    determined (unknown -> OFF so J6 skips loudly rather than false-fails).

    Truth ladder, most-authoritative first. A compose-file default is the LAST
    resort: the deployment .env overrides it on a real `up`, and asserting the
    file default against a live stand whose .env flipped the flag produced a
    false CROSS-CHAT-LEAK red (the write landed in the base scope because
    derivation was actually off).
      1. OCU_DERIVE_CHAT_SCOPE in this process's env (explicit override).
      2. The RUNNING control container's argv (docker inspect via the
         conftest fleet-exec routing) - the ground truth.
      3. OCU_DERIVE_CHAT_SCOPE in the deployment .env next to the compose file.
      4. The compose file's ${OCU_DERIVE_CHAT_SCOPE:-default}.
    """
    env = os.environ.get("OCU_DERIVE_CHAT_SCOPE")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")

    try:
        from conftest import _fleet_exec

        names = _fleet_exec(
            ["docker", "ps", "--format", "{{.Names}}", "--filter", "name=control"],
            timeout=15,
        ).stdout.split()
        cname = next((n for n in names if "control" in n and "db" not in n), None)
        if cname:
            argv = _fleet_exec(
                ["docker", "inspect", cname, "--format", "{{json .Args}}"],
                timeout=15,
            ).stdout
            m = re.search(r"-derive-chat-scope=(\w+)", argv)
            if m:
                return m.group(1).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        pass  # no docker reach from here: fall through to the file ladder

    env_file = _COMPOSE_FILE.parent / ".env"
    try:
        val = None
        # last assignment wins, mirroring compose env-file precedence
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OCU_DERIVE_CHAT_SCOPE="):
                val = line.split("=", 1)[1].strip()
        if val is not None:
            return val.lower() in ("1", "true", "yes", "on")
    except OSError:
        pass

    try:
        text = _COMPOSE_FILE.read_text(encoding="utf-8")
    except OSError:
        return False
    m = re.search(r"-derive-chat-scope=\$\{OCU_DERIVE_CHAT_SCOPE:-(\w+)\}", text)
    if m:
        return m.group(1).strip().lower() in ("1", "true", "yes", "on")
    # A bare `-derive-chat-scope=true` with no env indirection also counts as on.
    return bool(re.search(r"-derive-chat-scope=true\b", text))


# --- J1: agent deliverable reaches the user ---------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=_J182_XFAIL_REASON,
)
def test_j1_agent_write_reaches_pane_download(tmp_path):
    """Agent writes /mnt/user-data/outputs/<unique> -> pane lists it ->
    download 200 serves the exact bytes. Keystone: a never-written sibling
    name stays absent from the same listing window, so the green cannot come
    from a stale or over-matching list.

    xfail(strict) under #182: the entire flow is agent-write -> pane-find ->
    download; at >=100 objects the just-written file sorts off page-1 (ascending)
    and the positive pane-find never resolves, so the download leg is unreachable.
    Clears (XPASS -> remove marker) when order=desc ships (ADR-0031). The guest-FUSE
    read legs (j4) are #182-immune; only the pane-list positive-find is blocked."""
    _require_gateway()
    jar, csrf = _pane_session(tmp_path)
    _ensure_scope_saturated_for_182(jar, csrf)

    name = f"j1-{uuid.uuid4().hex[:10]}.txt"
    ghost = f"j1-ghost-{uuid.uuid4().hex[:10]}.txt"
    payload = f"J1-DELIVERABLE-{uuid.uuid4().hex}"

    is_err, text = _guest_bash(
        f"j1-{uuid.uuid4().hex[:8]}",
        f"printf %s '{payload}' > /mnt/user-data/outputs/{name} && echo WROTE",
    )
    assert not is_err and "WROTE" in text, f"guest write failed: {text[:200]}"

    obj = _pane_find(jar, name)
    assert obj is not None, f"pane never listed {name} within the write-back deadline"
    # Keystone: the ghost name must NOT appear - the list is real, not echoed.
    assert not [f for f in _pane_list(jar) if f.get("filename") == ghost]

    status, body = _pane_content(jar, obj["id"])
    assert status == 200, f"download of the agent deliverable = {status}, want 200"
    assert body == payload, "downloaded bytes differ from what the agent wrote"


# --- J2: user upload reaches the agent ---------------------------------------


def test_j2_pane_upload_readable_by_guest(tmp_path):
    """User uploads via the pane -> a FRESH guest reads the exact bytes at
    /mnt/user-data/uploads/<name>. Byte equality is the assertion; a
    stat-visible but empty read (the retired #143 failure mode, once pinned
    here as a strict xfail) must FAIL, never pass."""
    _require_gateway()

    # ONE chat id for BOTH halves. Under per-chat isolation the storage scope
    # is derived from the chat, so a pane opened with no chat uploads into the
    # BASE tree while a guest named for its own chat mounts fs-fleet-<hash> and
    # reads a different subtree. The bytes are stored correctly; they are just
    # not where this guest looks, and the read surfaces as "No such file or
    # directory" -- indistinguishable from an upload that never landed.
    chat = f"j2-{uuid.uuid4().hex[:8]}"
    jar, csrf = _pane_session(tmp_path, chat_id=chat)

    name = f"j2-{uuid.uuid4().hex[:10]}.txt"
    payload = f"J2-UPLOAD-{uuid.uuid4().hex}"
    _pane_upload(jar, csrf, name, payload)

    is_err, text = _guest_bash(
        chat,
        f"cat /mnt/user-data/uploads/{name}",
    )
    assert not is_err, f"guest read errored: {text[:200]}"
    assert text.strip() == payload, (
        f"guest read {len(text.strip())} bytes, want {len(payload)} - "
        "stat-visible-but-empty is the #143 failure mode"
    )


# --- J3: the north egress gate survives both legs ----------------------------


def test_j3_download_gate_asymmetry(tmp_path):
    """The uploads-side object refuses download (403 not-downloadable) -- the
    security keystone: if a fix for the south read path ever loosens the NORTH
    content-egress gate, this reddens. This assertion is #182-INDEPENDENT (the
    object id comes from the upload RESPONSE, not a pane-list find), so it stays
    live at any scope size. The outputs-side 200 half moved to j3b, which needs a
    positive pane-find and is #182-blocked at >=100 objects."""
    _require_gateway()
    jar, csrf = _pane_session(tmp_path)

    up_name = f"j3-up-{uuid.uuid4().hex[:10]}.txt"
    up_obj = _pane_upload(jar, csrf, up_name, "J3-UPLOAD-SIDE")
    status, _ = _pane_content(jar, up_obj["id"])
    assert status == 403, (
        f"download of an uploads-side object = {status}, want 403 "
        "(NFR-SEC-73 stored-tag gate on the north content egress)"
    )


@pytest.mark.xfail(
    strict=True,
    reason=_J182_XFAIL_REASON,
)
def test_j3b_outputs_side_deliverable_downloads(tmp_path):
    """The #182-fragile half split out of j3 (per the M2 precedent): the agent's
    outputs-side deliverable serves 200 byte-exact via the pane. This needs a
    positive pane-find of the just-written file to get its id for the content
    fetch; at >=100 objects the file is off page-1 (ascending) and the find never
    resolves -- so this is xfail(strict) under #182. j3 keeps the #182-independent
    403 security keystone live; only this 200 leg is blocked. Clears when order=
    desc ships (ADR-0031)."""
    _require_gateway()
    jar, csrf = _pane_session(tmp_path)
    _ensure_scope_saturated_for_182(jar, csrf)

    out_name = f"j3b-out-{uuid.uuid4().hex[:10]}.txt"
    is_err, text = _guest_bash(
        f"j3b-{uuid.uuid4().hex[:8]}",
        f"printf %s J3-OUTPUT-SIDE > /mnt/user-data/outputs/{out_name} && echo WROTE",
    )
    assert not is_err and "WROTE" in text
    obj = _pane_find(jar, out_name)
    assert obj is not None, f"pane never listed {out_name} within the write-back deadline"
    status, body = _pane_content(jar, obj["id"])
    assert status == 200 and body == "J3-OUTPUT-SIDE", (
        f"outputs-side deliverable download = {status}, want 200 byte-exact"
    )


# --- J4: the agent lists its own deliverable ---------------------------------


def test_j4_guest_lists_own_written_output():
    """Guest writes /mnt/user-data/outputs/<unique>, then the SAME session
    lists outputs/ and sees the name, and cats it back byte-exact. This is the
    list-own-writes keystone: under the flat single-mount era every read-class
    op resolved to the uploads subtree, so a written file vanished from the
    writer's own view. Ghost negative keeps the listing assertion non-vacuous."""
    _require_gateway()

    name = f"j4-{uuid.uuid4().hex[:10]}.txt"
    ghost = f"j4-ghost-{uuid.uuid4().hex[:10]}.txt"
    payload = f"J4-SELF-VIEW-{uuid.uuid4().hex}"
    chat = f"j4-{uuid.uuid4().hex[:8]}"

    is_err, text = _guest_bash(
        chat,
        f"printf %s '{payload}' > /mnt/user-data/outputs/{name} && echo WROTE",
    )
    assert not is_err and "WROTE" in text, f"guest write failed: {text[:200]}"

    is_err, listing = _guest_bash(chat, "ls /mnt/user-data/outputs")
    assert not is_err, f"guest ls of outputs errored: {listing[:200]}"
    assert name in listing, (
        "written file absent from the writer's own outputs listing - "
        "the flat-era list-own-writes defect"
    )
    assert ghost not in listing, "ghost name present - listing is not real"

    is_err, back = _guest_bash(chat, f"cat /mnt/user-data/outputs/{name}")
    assert not is_err and back.strip() == payload, (
        "written file does not cat back byte-exact through the outputs mount"
    )


# --- J5: the uploads view refuses writes --------------------------------------


def test_j5_uploads_mount_refuses_guest_write(tmp_path):
    """A guest write into /mnt/user-data/uploads FAILS (RO mount posture +
    engine-enforced read lease, NFR-SEC-49/ADR-0029), and the attempted name
    never surfaces in the pane list - so the refusal is real on both the
    mount and the spine, not a cosmetic mount option."""
    _require_gateway()
    jar, _csrf = _pane_session(tmp_path)

    name = f"j5-{uuid.uuid4().hex[:10]}.txt"

    is_err, text = _guest_bash(
        f"j5-{uuid.uuid4().hex[:8]}",
        f"printf %s J5-MUST-NOT-LAND > /mnt/user-data/uploads/{name} && echo WROTE",
    )
    assert is_err or "WROTE" not in text, (
        f"write into the uploads view SUCCEEDED - RO is a mirage: {text[:200]}"
    )

    # The refused name must not appear on the spine either (bounded window).
    end = time.monotonic() + 12
    while time.monotonic() < end:
        assert not [f for f in _pane_list(jar) if f.get("filename") == name], (
            "refused uploads-write surfaced in the pane list - engine accepted it"
        )
        time.sleep(3)


def test_j5b_guest_cannot_tamper_existing_upload(tmp_path):
    """The tamper keystone: a guest CANNOT overwrite the bytes of a file the
    user actually uploaded. J5 covers a guest CREATE into the RO uploads view;
    this covers the more dangerous vector -- overwriting an EXISTING uploaded
    object with attacker content. The user's original bytes must survive both
    the guest re-read and the pane download.

    The write may return exit 0 (the RO surface accepts the open then drops the
    flush -- a known DX gap, see the O_TRUNC platform ticket), so this asserts
    the SECURITY invariant (original bytes intact) rather than a non-zero exit.
    """
    _require_gateway()

    # ONE chat for BOTH halves: the scope is derived from the chat, so a pane
    # opened with no chat uploads into the BASE tree while this guest mounts
    # its own. The tamper keystone would then run against a file the guest
    # cannot see, and the test fails on its own precondition instead of on
    # the security property it exists to guard.
    chat = f"j5b-{uuid.uuid4().hex[:8]}"
    jar, csrf = _pane_session(tmp_path, chat_id=chat)

    name = f"j5b-{uuid.uuid4().hex[:10]}.txt"
    original = b"ORIGINAL_USER_BYTES_" + uuid.uuid4().hex[:8].encode()
    _pane_upload(jar, csrf, name, original, mime="text/plain")

    gpath = f"/mnt/user-data/uploads/{name}"

    # The guest must first SEE the user's real upload (bounded write-back).
    end = time.monotonic() + 30
    seen = False
    while time.monotonic() < end:
        is_err, text = _guest_bash(chat, f"cat {gpath} 2>&1")
        if not is_err and original.decode() in text:
            seen = True
            break
        time.sleep(2)
    assert seen, (
        f"the guest never read the user's upload at {gpath} -- cannot run the "
        "tamper keystone if the input is not visible"
    )

    # TAMPER: the guest tries all three mutation verbs against the RO upload --
    # overwrite (O_TRUNC), append (O_APPEND), and unlink. A read-only mount must
    # refuse all three; each may still exit 0 because bash swallows the EROFS at
    # close on a redirect (python/touch surface it loudly -- see the O_TRUNC
    # platform ticket), so the assertion is on the surviving bytes, not the exit.
    _guest_bash(chat, f"printf TAMPERED_BY_GUEST > {gpath} 2>&1; echo rc=$?")
    _guest_bash(chat, f"printf APPENDED_BY_GUEST >> {gpath} 2>&1; echo rc=$?")
    _guest_bash(chat, f"rm -f {gpath} 2>&1; echo rc=$?")

    # KEYSTONE 1: a fresh guest read (a LATER exec, so it cannot be a same-exec
    # write-back cache echo) still returns the ORIGINAL bytes, and none of the
    # tamper markers, and the file still exists (the unlink was refused).
    is_err, text = _guest_bash(chat, f"cat {gpath} 2>&1")
    assert (
        not is_err
        and original.decode() in text
        and "TAMPERED_BY_GUEST" not in text
        and "APPENDED_BY_GUEST" not in text
    ), (
        f"a guest MUTATED the user's uploaded file -- RO tamper protection is "
        f"broken (overwrite/append/unlink must all no-op): read-back {text[:200]!r}"
    )

    # KEYSTONE 2 (defense-in-depth, #182-aware): the pane content path never
    # serves the guest's tampered bytes. Uploads are read-in-place, not pane-
    # downloadable (NFR-SEC-73), so the content endpoint legitimately refuses with
    # 403; if it DOES serve content it must be the original. This is the SAME
    # security property KEYSTONE 1 already proved via the guest re-read; here it is
    # checked through the pane. A positive pane-find is #182-fragile: at >=100
    # objects the file sorts off page-1 and _pane_find returns None -- but a file
    # the pane cannot even list also cannot serve tampered bytes through the pane,
    # so #182-hidden is a SAFE outcome for this invariant, not a failure. Only run
    # the content assertion when the file is findable; the security core is
    # KEYSTONE 1 (always run). j8/j1/j3b carry the #182 ordering signal.
    obj = _pane_find(jar, name, deadline_s=15)
    if obj is not None:
        status, body = _pane_content(jar, obj["id"])
        assert "TAMPERED_BY_GUEST" not in (body or ""), (
            f"the pane content path served the guest's tampered bytes: {body[:200]!r}"
        )
        assert status == 403 or (status == 200 and original.decode() in body), (
            f"unexpected pane content for an uploaded file: status={status} "
            f"body={body[:200]!r} (want 403 not-downloadable, or 200 with the "
            "original bytes)"
        )


# --- J6: cross-chat file isolation (D5 acceptance keystone) -------------------


def test_j6_cross_chat_file_isolation():
    """Chat A writes /mnt/user-data/outputs/<secret>; chat B (a DIFFERENT
    X-Chat-Id -> a different control-derived storage scope) must NOT see it in
    its own outputs listing, nor cat it back. This is the D5 per-chat storage
    isolation acceptance gate (ADR-0030).

    Non-vacuity guard (two-sided): the two chats MUST resolve DISTINCT
    effective_scope via the gateway's resolve_scope MCP tool - else "B does not
    see A" could be green because the scopes collapsed to one base for an
    unrelated reason. The compose preflight decides which branch is correct:

      - derivation ON (the shipped default, -derive-chat-scope=${...:-true}):
        distinct non-empty scopes are REQUIRED. Equal/None/empty scopes are a
        FAILURE, never a skip - a degrade under derive-on is exactly the D5
        regression this gate exists to catch.
      - derivation OFF (OCU_DERIVE_CHAT_SCOPE=false, J7's world): equal/base
        scopes are EXPECTED and isolation is not in force -> LOUD SKIP, deferring
        to J7 for the degrade path.

    Ordering: resolving chat B's scope is what CREATES/ensures B's session (the
    gateway create hop lives inside the resolve_scope call), so calling
    _resolve_scope(chat_b) before B has run any guest command is intentional and
    safe - it is the act that gives B a session at all.

    Red-probe: flip control -derive-chat-scope=false WITHOUT touching the compose
    default (i.e. leave derive-on expected) -> both chats share fs-fleet -> the
    "distinct non-empty scopes" precondition FAILS the test (derive-on regressed);
    OR, with derive genuinely on, break isolation so chat B sees A's file -> the
    absence assertion REDs.
    """
    _require_gateway()

    derive_on = _derivation_expected_on()

    chat_a = f"j6a-{uuid.uuid4().hex[:8]}"
    chat_b = f"j6b-{uuid.uuid4().hex[:8]}"
    secret = f"j6-secret-{uuid.uuid4().hex[:10]}.txt"
    payload = f"J6-CHAT-A-ONLY-{uuid.uuid4().hex}"

    # Chat A writes its deliverable and confirms it sees its own file.
    is_err, text = _guest_bash(
        chat_a,
        f"printf %s '{payload}' > /mnt/user-data/outputs/{secret} && echo WROTE",
    )
    assert not is_err and "WROTE" in text, f"chat A write failed: {text[:200]}"
    is_err, own = _guest_bash(chat_a, "ls /mnt/user-data/outputs")
    assert not is_err and secret in own, (
        f"chat A cannot see its own deliverable: {own[:200]}"
    )

    # Resolve both scopes via the resolve_scope tool. Resolving B here is what
    # ensures B's session (the create hop is inside the call).
    scope_a = _resolve_scope(chat_a)
    scope_b = _resolve_scope(chat_b)

    if not derive_on:
        # J7's world: no per-chat derivation, so equal/base scopes are correct and
        # cross-chat isolation is NOT in force. Do not assert a false isolation green.
        pytest.skip(
            "compose preflight says -derive-chat-scope is OFF (or the compose file "
            "is unreadable): per-chat isolation is not expected here. LOUD SKIP - "
            "J7 covers the single-scope degrade path."
        )

    # Derivation is ON: distinct, non-empty scopes are REQUIRED. A degrade here is
    # the exact D5 regression this gate catches - FAIL, do not skip.
    assert scope_a and scope_b, (
        "derive-chat-scope is ON per the compose preflight, but resolve_scope "
        f"returned empty/None scopes (a={scope_a!r}, b={scope_b!r}) - the derivation "
        "path regressed to a degrade. This is a FAILURE under derive-on, not a skip."
    )
    assert scope_a != scope_b, (
        "derive-chat-scope is ON, but chat A and chat B resolved the SAME scope "
        f"{scope_a!r} - the derivation collapsed to a single base and the isolation "
        "assertion would be vacuous. FAILURE under derive-on."
    )

    # The isolation assertion: chat B's own outputs listing must NOT carry A's file,
    # and a direct cat must not read A's bytes.
    is_err, b_listing = _guest_bash(chat_b, "ls /mnt/user-data/outputs 2>&1 || true")
    assert not is_err or "No such" in b_listing or b_listing.strip() == "", (
        f"chat B ls errored unexpectedly: {b_listing[:200]}"
    )
    assert secret not in b_listing, (
        f"CROSS-CHAT LEAK: chat B ({scope_b}) sees chat A's ({scope_a}) file "
        f"{secret} in its own outputs listing - per-chat isolation broken"
    )
    is_err, b_cat = _guest_bash(chat_b, f"cat /mnt/user-data/outputs/{secret} 2>&1 || true")
    assert payload not in b_cat, (
        f"CROSS-CHAT LEAK: chat B read chat A's secret bytes via a direct cat: {b_cat[:200]}"
    )


def test_j6b_pane_view_omits_other_chats_secret(tmp_path):
    """The NORTH/pane half of D5 (D5-BUILD-SPEC required it): the user-facing
    File Pane for one chat must not surface another chat's outputs.

    Chat A writes a secret to /mnt/user-data/outputs; then the pane (bootstrapped
    for the DEFAULT/base scope) must not list that secret, and a pane content
    read of a never-existing id 404s (the negative that keeps the omission
    non-vacuous - the pane really answers 404 for an absent object, it does not
    blanket-200 or blanket-list).

    Scaffold limit, stated LOUDLY not faked: this demo portal mints one base
    scope (the pane is per-portal, not per-chat here), so we cannot prove a
    per-chat pane token against A's DERIVED scope. What IS provable - that a
    base-scope pane does not enumerate a chat-derived secret, and that a bogus id
    404s - is asserted; the per-chat pane token leg is skipped with a named
    reason when derivation is on and the two scopes differ.
    """
    _require_gateway()
    jar, _csrf = _pane_session(tmp_path)

    chat_a = f"j6b-a-{uuid.uuid4().hex[:8]}"
    secret = f"j6b-secret-{uuid.uuid4().hex[:10]}.txt"
    payload = f"J6B-CHAT-A-ONLY-{uuid.uuid4().hex}"

    is_err, text = _guest_bash(
        chat_a,
        f"printf %s '{payload}' > /mnt/user-data/outputs/{secret} && echo WROTE",
    )
    assert not is_err and "WROTE" in text, f"chat A write failed: {text[:200]}"

    # Negative keeps the pane read honest: a never-minted file id must 404, so a
    # blanket-200 content handler cannot make the omission look green.
    bogus_id = f"nonexistent-{uuid.uuid4().hex}"
    status, _ = _pane_content(jar, bogus_id)
    assert status == 404, (
        f"pane content of a bogus id = {status}, want 404 - the pane must not "
        "blanket-serve, or the omission assertion below is vacuous"
    )

    if not _derivation_expected_on():
        pytest.skip(
            "compose preflight says -derive-chat-scope is OFF: the base-scope pane "
            "shares chat A's scope, so cross-chat pane omission is not in force. "
            "LOUD SKIP - J7 covers the single-scope world."
        )

    # Derivation ON: the pane here holds the BASE scope, chat A wrote under a
    # DERIVED scope. A bounded window must never surface A's secret in the base
    # pane list. (The per-chat pane token against A's own derived scope is the
    # leg this demo scaffold cannot mint - stated, not faked.)
    end = time.monotonic() + 12
    while time.monotonic() < end:
        assert not [f for f in _pane_list(jar) if f.get("filename") == secret], (
            f"CROSS-CHAT LEAK: the base-scope pane lists chat A's derived-scope "
            f"secret {secret} - per-chat north isolation broken"
        )
        time.sleep(3)


# --- J7: single-scope degrade keeps the two-way flow (backward compat) --------


def test_j7_single_scope_degrades_to_two_way_flow():
    """With per-chat derivation OFF (or a single-chat deployment), the base
    scope is shared and the ordinary two-way flow (agent writes -> its own
    listing sees it) still works. This proves D5 does not break the single-scope
    deployment. When derivation is ON and a chat resolves a derived scope, this
    still holds within that chat's own scope - so the assertion is scope-agnostic.

    Division of labour vs J6: the derive-OFF case (both chats resolve None/equal,
    the base is shared) is J7's world - here the two-way flow within one scope
    must stay green. The derive-ON case (distinct scopes REQUIRED) is J6's; there
    equal/None scopes are a FAILURE, not this compat proof. Red-probe for J7: if
    the two-way flow itself broke (a chat cannot see its own write in its own
    scope) this test REDs regardless of the derivation flag.
    """
    _require_gateway()

    chat = f"j7-{uuid.uuid4().hex[:8]}"
    name = f"j7-{uuid.uuid4().hex[:10]}.txt"
    payload = f"J7-DEGRADE-{uuid.uuid4().hex}"

    is_err, text = _guest_bash(
        chat, f"printf %s '{payload}' > /mnt/user-data/outputs/{name} && echo WROTE",
    )
    assert not is_err and "WROTE" in text, f"guest write failed: {text[:200]}"
    is_err, listing = _guest_bash(chat, "ls /mnt/user-data/outputs")
    assert not is_err and name in listing, (
        "a chat cannot see its own deliverable in its own scope - the two-way "
        "flow broke under D5"
    )
    is_err, back = _guest_bash(chat, f"cat /mnt/user-data/outputs/{name}")
    assert not is_err and back.strip() == payload, (
        "own-scope deliverable does not cat back byte-exact"
    )


@pytest.mark.xfail(
    strict=True,
    reason="task #182: the F9 list sorts ASCENDING CreatedAt (oldest-first) and "
    "the pane fetches only page-1 (no cursor-follow), so a just-created file is "
    "the NEWEST -> sorts LAST -> is off page-1 once the scope holds >=100 objects. "
    "The pane never shows it, breaking the owner's 'created file appears in the "
    "preview' bar. Fable-ruled fix (owner-gated): additive order=asc|desc param, "
    "default asc, the pane sends order=desc (ADR-0031 amends 0028). When that "
    "lands this XPASSes and strict=True forces this marker's removal.",
)
def test_j8_newest_file_visible_in_pane_first_page(tmp_path):
    """K2 acceptance keystone for task #182: in a scope holding >=100 objects, a
    file the guest writes LAST must appear in the pane's FIRST-page list (the exact
    GET /v1/files the pane issues on mount: no ?after, no ?limit). The owner's bar
    is that the just-created file is visible in the pane; a user does not page a
    file panel.

    Non-vacuous: this asserts the NEWEST file, and only after the scope is padded
    past the 100-object page boundary -- the exact condition M1/M5/M6 miss by
    under-population (their scopes stay small, so their new file is trivially on
    page-1 and they are blind to the ordering defect). This test is xfail(strict)
    today because the ordering defect is live; it XPASSes when the order=desc fix
    ships, and strict=True then turns the XPASS into a failure that forces the
    marker off (a self-clearing acceptance gate).
    """
    _require_gateway()
    jar, csrf = _pane_session(tmp_path)

    # 1. Ensure the scope is saturated past the 100-object first-page boundary, so
    # a fresh file cannot trivially land on page-1. Pad only as many as needed
    # (the shared fs-fleet scope usually already carries >=100 from prior runs).
    PAGE = 100
    current = len(_pane_list(jar))
    need = max(0, (PAGE + 5) - current)
    for i in range(need):
        _pane_upload(jar, csrf, f"j8-pad-{i:03d}-{uuid.uuid4().hex[:8]}.txt", f"pad{i}")
    saturated = len(_pane_list(jar))
    assert saturated >= PAGE, (
        f"could not saturate the scope past {PAGE} objects (have {saturated}); the "
        "ordering defect is only reachable at >=100 -- an under-populated scope "
        "would make this test vacuously pass"
    )

    # 2. The guest writes the NEWEST file (latest CreatedAt) via the real P-A path.
    chat = f"j8-{uuid.uuid4().hex[:8]}"
    newest = f"j8-newest-{uuid.uuid4().hex[:10]}.txt"
    payload = f"J8-NEWEST-{uuid.uuid4().hex}"
    is_err, text = _guest_bash(
        chat, f"printf %s '{payload}' > /mnt/user-data/outputs/{newest} && echo WROTE"
    )
    assert not is_err and "WROTE" in text, f"guest write of the newest file failed: {text[:200]}"

    # 3. The newest file must be on the pane's FIRST-page fetch. Poll for the
    # write-back lag, but ONLY the first page (what the pane actually renders) --
    # NOT a cursor-followed full walk, because the pane does not follow the cursor.
    import time as _time

    deadline = _time.monotonic() + 45
    seen = False
    while _time.monotonic() < deadline:
        page1 = _pane_list(jar)  # GET /v1/files, no after/limit -- the pane's call
        if any(f.get("filename") == newest for f in page1):
            seen = True
            break
        _time.sleep(3)
    assert seen, (
        f"the just-written newest file {newest!r} is NOT on the pane's first-page "
        f"list (scope has {saturated}+ objects). It exists (the guest wrote it) but "
        "sorts LAST under ascending CreatedAt, so the page-1-only pane never shows "
        "it -- the owner's 'created file appears in the preview' bar is broken. "
        "This is task #182; it clears when order=desc ships."
    )
