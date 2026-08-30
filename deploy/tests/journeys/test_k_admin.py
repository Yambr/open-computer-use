# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""GROUP K — admin operator read surface (K1..K3), fleet-only.

The A..J journey groups drive the caller-facing planes (control's gateway
mTLS ingress, the MCP gateway, the file data path). None of them reach the
OPERATOR read surface: ocu-admin (component-08's operator console) is a
separate BFF that dials control's operator Unix socket directly and projects
the frozen ADR-0022 read contract (GET /v1alpha/sessions,
/v1alpha/sessions/{key}, /v1alpha/deployment, /metrics) behind its own
bcrypt + session-cookie gate. Wiring it into the fleet compose (the admin
service block in docker-compose.fleet.yml) closed a real gap: the read
surface existed in the ocu-admin repo but was never assembled into the fleet
and never exercised by this suite.

This group closes that gap. It drives the REAL admin BFF on
127.0.0.1:3004 with the fleet-compose demo operator credential
(OCU_ADMIN_OPERATOR_USER / a bcrypt hash of a known demo password, both set
in deploy/fleet/.env.example) and asserts:

  K1  an unauthenticated GET of the read surface -> 401 (the middleware.ts
      session-cookie gate, before any control dial)
  K2  wrong login credentials -> 401 at the login route itself (no cookie
      minted, so K1's gate is not bypassable by a forged/guessed session)
  K3  a session created via the fleet gateway (the SAME session the other
      groups create) is VISIBLE through the admin read surface once
      authenticated — proves the shared operator-socket wiring is live, not
      just present in the compose file

No poc counterpart: the PoC has no control plane, no operator socket, and no
admin console, so this group is fleet-only and skips loudly whenever the
fleet is not reachable or the demo operator credential is not the one the
compose actually booted with. It never fabricates a green.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from backends.fleet import FleetBackend

# The admin BFF's host-mapped port (docker-compose.fleet.yml "127.0.0.1:3004:3000").
ADMIN_URL = os.getenv("ADMIN_URL", "http://127.0.0.1:3004")
# The demo operator credential the fleet compose's .env.example documents.
# OCU_ADMIN_OPERATOR_BCRYPT_HASH there is bcrypt(cost=12) of this literal
# password; a deployment that overrides the hash also overrides this suite's
# env so K2/K3 log in with the credential the running admin container was
# actually booted with, never a hardcoded guess.
ADMIN_OPERATOR_USER = os.getenv("ADMIN_OPERATOR_USER", "demo-operator")
ADMIN_OPERATOR_PASSWORD = os.getenv("ADMIN_OPERATOR_PASSWORD", "ocu-fleet-demo-password")

_COOKIE_JAR = Path(__file__).resolve().parent / ".admin-cookie-jar.txt"


def _curl(
    method: str,
    path: str,
    headers: list[str] | None = None,
    body: str | None = None,
    use_cookies: bool = False,
    timeout: int = 15,
) -> tuple[int, str]:
    """Issue an HTTP request against the admin BFF, return (status, body).

    Uses curl (not requests/httpx) to match the exact wire a browser sends and
    to stay dependency-free, mirroring test_h_gateway.py's _curl. Raises on a
    transport failure so an unreachable admin becomes a loud skip, never a
    silent pass. ``use_cookies`` reads/writes a shared cookie jar file so a
    login's Set-Cookie survives into the following authenticated GET, the
    same two-step flow a real browser does.
    """
    args = [
        "curl", "-sS", "--max-time", str(timeout),
        "-o", "-", "-w", "\n__HTTP_%{http_code}__",
        "-X", method, f"{ADMIN_URL}{path}",
    ]
    if use_cookies:
        args += ["-b", str(_COOKIE_JAR), "-c", str(_COOKIE_JAR)]
    for h in headers or []:
        args += ["-H", h]
    if body is not None:
        args += ["-H", "content-type: application/json", "-d", body]
    try:
        # `args` is assembled above from literals, `ADMIN_URL` and the operator
        # credentials (all stand config from the operator's own env), plus this
        # function's parameters — `body` carries the env-derived credentials via
        # `_login`, so this is env-sourced data, not literals. It is safe because
        # curl gets each value as ONE argv element with no shell in between, not
        # because the values are constants.
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 5)
    except subprocess.SubprocessError as exc:
        raise RuntimeError(f"curl transport failure on {path}: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"curl transport failure rc={proc.returncode} on {path}: {proc.stderr[:200]}")
    out = proc.stdout
    marker = "\n__HTTP_"
    idx = out.rfind(marker)
    if idx == -1:
        raise RuntimeError(f"no HTTP status marker in curl output for {path}: {out[:200]}")
    status_str = out[idx + len(marker):].rstrip("_\n")
    return int(status_str), out[:idx]


def _admin_live() -> bool:
    """True iff the admin BFF answers at all (any HTTP status, unauthenticated)."""
    try:
        status, _ = _curl("GET", "/", timeout=5)
        return status > 0
    except Exception:
        return False


def _login(user: str, password: str) -> int:
    """POST the login route with a fresh cookie jar. Returns the HTTP status.

    A 204 mints the session cookie into the jar (curl -c writes Set-Cookie);
    a 401 mints nothing, leaving the jar absent/stale from a prior run.
    """
    if _COOKIE_JAR.exists():
        _COOKIE_JAR.unlink()
    status, _ = _curl(
        "POST", "/api/auth/login",
        body=json.dumps({"username": user, "password": password}),
        use_cookies=True,
    )
    return status


pytestmark = pytest.mark.fleet


@pytest.fixture(autouse=True)
def _require_admin():
    if not _admin_live():
        pytest.skip(
            f"admin BFF not reachable at {ADMIN_URL} (bring up the fleet compose's "
            "admin service) — SKIP, not a pass."
        )


@pytest.fixture(autouse=True)
def _clean_cookie_jar():
    yield
    if _COOKIE_JAR.exists():
        _COOKIE_JAR.unlink()


def test_k1_unauthenticated_read_401():
    """An unauthenticated GET of the read surface is refused 401.

    Hits the rewritten path (/v1alpha/sessions -> /api/read/sessions per
    next.config.ts) with no cookie at all. middleware.ts gates every route but
    /api/auth/login, so this must 401 before the request ever reaches
    control's operator socket.
    """
    status, body = _curl("GET", "/v1alpha/sessions")
    assert status == 401, (
        f"unauthenticated read must 401 at the BFF gate, got {status}: {body[:200]}"
    )


def test_k2_login_wrong_credentials_401():
    """A wrong password is refused 401 at the login route, mints no cookie.

    This is the keystone for K1: if login accepted a forged/guessed
    credential, the "unauthenticated" 401 in K1 would be meaningless (any
    caller could just log in). Proves the gate is a REAL credential check,
    not a rubber stamp.
    """
    status = _login(ADMIN_OPERATOR_USER, "definitely-not-the-real-password")
    assert status == 401, f"wrong password must 401 at login, got {status}"
    # No cookie minted: a following read must still be unauthenticated.
    read_status, _ = _curl("GET", "/v1alpha/sessions", use_cookies=True)
    assert read_status == 401, (
        "a failed login must not leave a usable session cookie behind "
        f"(follow-up read got {read_status}, want 401)"
    )


def test_k3_live_session_visible_through_admin_read_surface():
    """A gateway-created session is visible through admin's read surface.

    Once authenticated, the shared-operator-socket wiring
    (docker-compose.fleet.yml: admin bind-mounts the SAME host path control
    writes -operator-listen to) is exercised live, not just present in the
    compose file. Fails closed at three points, each distinguishable in the
    assertion message: (a) login itself fails -> the demo credential in
    .env.example does not match what the running container booted with; (b)
    the read 401s post-login -> the session cookie / gate is broken; (c) the
    read succeeds but the created session's key is absent from the listing ->
    admin is not actually reading control's live state (stale/mocked/wrong
    socket).
    """
    fleet = FleetBackend()
    if not fleet.live():
        pytest.skip("fleet control plane not live — SKIP, not a pass.")
    session = fleet.create_storage_session()
    assert session.key, f"fleet session create failed (status={session.status}); cannot probe admin visibility"
    try:
        login_status = _login(ADMIN_OPERATOR_USER, ADMIN_OPERATOR_PASSWORD)
        assert login_status == 204, (
            f"admin login failed (got {login_status}); the demo credential in "
            "deploy/fleet/.env.example may not match OCU_ADMIN_OPERATOR_USER/"
            "OCU_ADMIN_OPERATOR_BCRYPT_HASH the admin container actually booted "
            "with — override ADMIN_OPERATOR_USER/ADMIN_OPERATOR_PASSWORD env for "
            "this suite if the fleet uses non-demo values."
        )

        # A newly created row can lag a beat behind the write that reserved it
        # reaching control's read path; poll briefly rather than assume
        # instant consistency.
        deadline = time.monotonic() + 10
        found = False
        status, body = 0, ""
        while time.monotonic() < deadline:
            status, body = _curl("GET", "/v1alpha/sessions", use_cookies=True)
            if status == 200 and session.key in body:
                found = True
                break
            time.sleep(0.5)

        assert status == 200, (
            f"authenticated read of the admin surface must succeed, got {status}: {body[:200]}"
        )
        assert found, (
            f"session {session.key!r} created via the fleet gateway did not appear "
            f"in the admin read surface within 10s — the shared operator-socket "
            f"wiring (admin's OCU_ADMIN_CONTROL_SOCKET bind mount) is not reaching "
            f"the same control instance. Listing body: {body[:500]}"
        )
    finally:
        fleet.destroy_all_sessions()
