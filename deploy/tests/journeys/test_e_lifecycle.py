# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""GROUP E — Auto-disconnect / lifecycle / kill-switch (E1..E8).

Paired PoC-vs-fleet journeys for session lifecycle: idle reaping, the operator
kill-switch (revoke/all + resume/all over the SO_PEERCRED operator UDS),
control-restart durability + boot-reconcile (orphan-row reclaim, stray-container
kill), the concurrency quota ceiling, and mid-journey session-JWT expiry.

One test per scenario. Each drives the real backend verbs (no mocks), asserts
the real observable end state, and carries the scenario's KEYSTONE as an
explicit sub-check so the green is reproducibly reddable.

Binding the scaffold to live surfaces
--------------------------------------
Two fleet surfaces are left as ``NotImplementedError`` stubs in
``backends/fleet.py`` on purpose — the docstrings say the lifecycle group test
binds them to the real wire rather than faking a toggle:

  * the operator kill-switch (``revoke_all`` / ``resume_all``) over the host UDS
    ``/run/ocu-control/operator.sock`` (SO_PEERCRED-gated);
  * control-restart / reconcile ops (E4/E5/E6), which are container operations,
    not a backend verb.

This module binds those to the real host surface: the operator UDS via
``curl --unix-socket`` and control restarts via ``docker`` addressed by the
compose service label. Where a required host surface is not reachable from the
test env (no operator sock, no docker), the test SKIPS loudly or xfails with a
reason — it never fabricates a green. Where a contract is still TBD (idle-TTL is
unspecified per backlog #91; post-restart lifecycle is envelope-only), the test
asserts the STATUS CLASS / released-state, not an invented timeout or body, and
says so in a comment.

Browser-driven hops (E8's embed-token re-auth surface) drive real Playwright
fill+click — never ``page.evaluate(fetch)``. Playwright is imported behind
``pytest.importorskip`` so the sub-check is an honest skip where the browser
harness is not wired, not a silent pass.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Optional

import pytest

from backends.base import (
    Backend,
    PocHoleNotEnforced,
    SessionRef,
)
from conftest import (
    _reclaim_fleet_concurrency_leak,
    await_fleet_exec_ready,
    real_finding,
)

# The operator UDS the fleet host mounts (kill-switch / resume ingress). Matches
# FLEET_OPERATOR_SOCK in backends/fleet.py; overridable for a non-default host.
_OPERATOR_SOCK = os.getenv("FLEET_OPERATOR_SOCK", "/run/ocu-control/operator.sock")
# The compose service label control runs under (no container_name is pinned in
# docker-compose.fleet.yml, so address it by label, not a guessed name).
_CONTROL_SERVICE = os.getenv("FLEET_CONTROL_SERVICE", "control")
# A short settle window after a restart for boot-reconcile to run before we probe.
_RECONCILE_SETTLE_S = float(os.getenv("FLEET_RECONCILE_SETTLE_S", "8"))


# =====================================================================
# Local bindings to real host surfaces (operator UDS + control container).
# These are the "bind to the real wire" the fleet scaffold defers to this
# group test. None of them mocks a result: an unreachable surface raises so
# the caller can skip/xfail honestly.
# =====================================================================


def _require_docker() -> str:
    docker = shutil.which("docker")
    if not docker:
        pytest.skip(
            "docker CLI not found; E4/E5/E6 need it to restart control and "
            "manage the guest container. This is a SKIP, not a pass."
        )
    return docker


# The operator UDS is SO_PEERCRED-gated and root-owned (0700 dir): a non-root
# test process cannot even stat it, so reaching it needs the same privilege
# `occ` runs with. We drive it via `sudo -n` (non-interactive) — the fleet host
# grants the test runner passwordless sudo exactly so the E-group can exercise
# the real kill-switch. FLEET_OPERATOR_SUDO=0 opts out (e.g. a host where the
# runner IS root or sudo is unavailable), falling back to a direct connect.
_OPERATOR_SUDO = os.getenv("FLEET_OPERATOR_SUDO", "1") not in ("0", "", "false")


def _sudo_prefix() -> list[str]:
    """`sudo -n` prefix when configured and available, else empty.

    `-n` never prompts: if sudo would need a password the call fails fast and
    the caller skips loudly, rather than hanging the suite on a TTY prompt.
    """
    if not _OPERATOR_SUDO:
        return []
    sudo = shutil.which("sudo")
    return [sudo, "-n"] if sudo else []


def _operator_sock_reachable() -> bool:
    """True iff the operator UDS is a socket we can address (via sudo if needed).

    A non-root ``os.path.exists`` on a 0700-root dir returns False even when the
    sock is present, so probe with ``[sudo] test -S`` — the same privilege the
    POST uses. Never raises; a missing sudo/curl surfaces as False -> loud skip.
    """
    try:
        # `_OPERATOR_SOCK` is a module constant and `_sudo_prefix()` returns
        # either [] or ["sudo"]; the only env-derived part is whether sudo is
        # used at all, decided by the operator running the suite on their own
        # host. List argv, no shell.
        probe = subprocess.run(
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
            _sudo_prefix() + ["test", "-S", _OPERATOR_SOCK],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


# ---------------------------------------------------------------------------
# Control-DB white-box helpers for the quota keystone (E7). These read/arrange
# the concurrent-sessions counter directly — legitimate for a sudo-tier ops test
# that already drives the operator UDS and docker. See the KNOWN-BUG note in
# conftest for why the counter must be reclaimed between fleet tests.
# ---------------------------------------------------------------------------
def _discover_control_db() -> str:
    """The control-DB container name. Prefer an explicit env override; else
    discover the running control-db container so the seed does not silently
    no-op on a compose project whose name is not the hardcoded default (the
    stand runs `ocu-donegate-control-db-1`, not `ocu-fleet-control-db-1`; a
    `docker exec` on the wrong name fails and _psql swallows it to None, so the
    counter seed never lands and a cap test reads a false `active`)."""
    override = os.getenv("FLEET_CONTROL_DB_CONTAINER")
    if override:
        return override
    docker = shutil.which("docker")
    if docker:
        try:
            proc = subprocess.run(
                [docker, "ps", "--filter", "name=control-db", "--format", "{{.Names}}"],
                capture_output=True,
                timeout=10,
            )
            names = [n for n in proc.stdout.decode().split() if n.endswith("control-db-1")]
            if names:
                return names[0]
        except (OSError, subprocess.SubprocessError):
            pass
    return "ocu-fleet-control-db-1"


_CONTROL_DB = _discover_control_db()
_DB_USER = os.getenv("FLEET_CONTROL_DB_USER", "ocu")
_DB_NAME = os.getenv("FLEET_CONTROL_DB_NAME", "ocu_control")
_CONCURRENT_DIM = os.getenv("FLEET_CONCURRENT_DIM", "0")
# The deployed compile-time cap (state.QuotaKey limit for internal_workforce).
_FLEET_TIER_CAP = int(os.getenv("FLEET_TIER_CAP", "64"))


def _fleet_tier_cap() -> int:
    return _FLEET_TIER_CAP


def _psql(sql: str) -> Optional[str]:
    """Run one SQL against the control DB via `docker exec`; None on any failure."""
    docker = shutil.which("docker")
    if not docker:
        return None
    try:
        # `sql` comes from this file only: literals, plus one f-string whose
        # interpolations are `int(value)` and a module constant. `_CONTROL_DB`,
        # `_DB_USER` and `_DB_NAME` are stand config from the operator's env.
        # Each reaches psql as one argv element — `docker exec` execs directly
        # rather than through /bin/sh — so nothing is re-parsed. Would NOT hold
        # if `sql` were ever built from a fixture the caller controls.
        proc = subprocess.run(
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
            [
                docker, "exec", _CONTROL_DB,
                "psql", "-U", _DB_USER, "-d", _DB_NAME, "-t", "-A", "-c", sql,
            ],
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace").strip()


def _set_fleet_concurrent_counter(value: int) -> None:
    """Seed the DimConcurrentSessions counter to ``value`` (env-state arrangement)."""
    _psql(
        f"update quota_counters set value={int(value)} where dim={_CONCURRENT_DIM};"
    )


def _fleet_concurrent_counter_vs_rows() -> tuple[Optional[int], int]:
    """Return (counter, live_row_count) for the concurrent-sessions dimension."""
    counter_raw = _psql(
        f"select coalesce(max(value),0) from quota_counters where dim={_CONCURRENT_DIM};"
    )
    rows_raw = _psql("select count(*) from sessions where state in (0,1);")
    counter = int(counter_raw) if counter_raw and counter_raw.lstrip("-").isdigit() else None
    live_rows = int(rows_raw) if rows_raw and rows_raw.isdigit() else 0
    return counter, live_rows


def _heal_concurrent_counter_to_live() -> None:
    """Model boot Reconcile Direction 3 (ReconcileConcurrent): heal the
    DimConcurrentSessions counter DOWN to the true live-row count. Control's boot
    reconciler recomputes this cell from the durable session rows on restart; this
    reproduces that heal without a full control restart, so the arranged-to-cap
    counter (no real rows behind it) returns to reality and admission resumes.
    Operator revoke/all is NOT the healer here -- it refunds per KILLED ROW and
    cannot reconcile a counter value that has no rows behind it."""
    _, live_rows = _fleet_concurrent_counter_vs_rows()
    _set_fleet_concurrent_counter(live_rows)


def _operator_post(path: str) -> int:
    """POST to the operator UDS over curl --unix-socket; return the HTTP status.

    This is the real kill-switch / resume ingress (SO_PEERCRED-gated). The test
    process reaches it with the operator privilege (`sudo -n` by default, same
    as `occ`). Skips loudly when curl is missing or the socket is not reachable
    — never a fabricated 200.
    """
    curl = shutil.which("curl")
    if not curl:
        pytest.skip("curl not found; cannot reach the operator UDS. SKIP, not a pass.")
    if not _operator_sock_reachable():
        pytest.skip(
            f"operator UDS {_OPERATOR_SOCK} not reachable (fleet host mount absent, "
            "or sudo -n unavailable to address the SO_PEERCRED sock). SKIP, not a pass."
        )
    try:
        proc = subprocess.run(
            # `curl`, `_OPERATOR_SOCK` and the URL path are harness constants;
            # `_sudo_prefix()` returns [] or ["sudo"]. curl receives the socket path as
            # one argv element with no shell in between.
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
            _sudo_prefix() + [
                curl, "-sS", "--max-time", "15",
                "--unix-socket", _OPERATOR_SOCK,
                "-o", os.devnull, "-w", "%{http_code}",
                "-X", "POST", f"http://localhost{path}",
            ],
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"operator UDS unreachable at {path}: {exc}. SKIP, not a pass.")
    code = proc.stdout.decode("utf-8", "replace").strip()
    if not code.isdigit():
        pytest.skip(
            f"operator UDS returned no HTTP status for {path} "
            f"(rc={proc.returncode}); cannot assert a toggle. SKIP, not a pass."
        )
    return int(code)


def _control_container_id(docker: str) -> Optional[str]:
    """Resolve the running control container by its compose service label."""
    try:
        proc = subprocess.run(
            # `docker` is the resolved binary and `_CONTROL_SERVICE` is stand config from
            # the operator's own env, passed as one argv element to a `--filter` flag.
            # No shell parses it.
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
            [
                docker, "ps", "--filter",
                f"label=com.docker.compose.service={_CONTROL_SERVICE}",
                "--format", "{{.ID}}",
            ],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    ids = proc.stdout.decode("utf-8", "replace").split()
    return ids[0] if ids else None


def _restart_control() -> None:
    """Restart the control container and let boot-reconcile settle.

    A real restart (not a mock) exercises the Postgres-durable state + the #93
    boot-reconcile sweep. Skips loudly if control cannot be addressed.
    """
    docker = _require_docker()
    cid = _control_container_id(docker)
    if cid is None:
        pytest.skip(
            f"no running control container (label service={_CONTROL_SERVICE}); "
            "fleet compose not up here. SKIP, not a pass."
        )
    try:
        proc = subprocess.run(
            [docker, "restart", cid], capture_output=True, timeout=90
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"could not restart control ({cid}): {exc}. SKIP, not a pass.")
    if proc.returncode != 0:
        pytest.skip(
            f"docker restart control failed rc={proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace')}. SKIP, not a pass."
        )
    # Give boot-reconcile a moment; the subsequent GET drives the real assertion.
    time.sleep(_RECONCILE_SETTLE_S)


def _guest_container_id(docker: str, key: str) -> Optional[str]:
    """Resolve the guest container control derives for a session key (ocu-sess-{key})."""
    cname = f"ocu-sess-{key}"
    try:
        proc = subprocess.run(
            [docker, "ps", "-a", "--filter", f"name={cname}", "--format", "{{.ID}}"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    ids = proc.stdout.decode("utf-8", "replace").split()
    return ids[0] if ids else None


def _fleet_only(backend: Backend) -> None:
    """Require the fleet backend for an ops scenario with no PoC analogue.

    E5/E6 are operator-restart mechanics that the PoC does not model at all. On
    the PoC side we assert the recorded absence via the PocHoleNotEnforced /
    in-memory-map contrast in the body, so this is only used where the scenario
    is exclusively a fleet mechanism.
    """
    if backend.name != "fleet":
        pytest.skip("ops-restart mechanic has no PoC analogue; fleet-only scenario body.")


# =====================================================================
# E1 — idle reaper / TTL releases the session
# =====================================================================


def test_e1_idle_reaper_releases_session(backend: Backend, expect) -> None:
    """E1 | Idle reaper / TTL releases the session (HARDENED).

    Invariant: an idle session is released and its next op returns a deny
    status — keyed on the REPORTED released-state, never a hardcoded timeout.
    idle-TTL is unspecified (backlog #91), so this asserts the ENVELOPE: release
    is driven through the operator surface that DOES exist and the released
    state + deny status are asserted, with the idle-TTL timing left
    envelope-until-contract-pins. KEYSTONE: an ACTIVE session is NOT reaped —
    the release keys on idleness / operator action, not a blanket kill.
    """
    sc = expect("E1")
    assert sc["bucket"] == "HARDENED"

    if backend.name == "poc":
        # PoC "reaper per backlog #91" is not a server-enforced boundary here;
        # a session is the chat itself and its state tracks the container. The
        # finding is the ABSENCE of an operator-driven released state, recorded
        # as a PoC-HOLE contrast rather than faked green.
        sess = backend.create_session()
        assert sess.status == "active"
        # No idle-release surface on the PoC: the session stays active until the
        # container is gone. That absence is the E1 contrast; we do not invent a
        # reaper here.
        return

    # Fleet: drive release via the operator surface that exists (revoke/all),
    # since idle-TTL timing is not yet contract-pinned. Assert released-state +
    # deny status on the NEXT op, not a timeout.
    active = backend.create_session()
    assert active.status == "active", f"expected an active session, got {active.status}"
    assert active.key, "control must return a session key"

    # KEYSTONE (idleness/operator-keyed, not a blanket timer): immediately after
    # create, before any release action, the session is still active — it is not
    # reaped just for existing.
    still_active = backend.get_session(active.key)
    assert still_active.status not in ("released", "denied", "not_found"), (
        "an ACTIVE, un-idle session must not be reaped; got "
        f"{still_active.status} (keystone: reaper keys on idleness, not existence)"
    )

    # Drive the released state through the operator surface (the release path
    # that DOES exist while idle-TTL is unspecified).
    status = _operator_post("/v1alpha/revoke/all")
    assert status in (200, 204), f"revoke/all should accept, got {status}"

    # Assert the released/deny envelope on the next op — status class, not a
    # specific reaped-at time (idle-TTL is envelope-until-contract-pins).
    after = backend.exec_sh("true")
    assert after.denied, "post-release exec must be denied (released-state envelope)"

    # Restore so a later test's create is not blocked by the deny latch.
    _operator_post("/v1alpha/resume/all")


# =====================================================================
# E2 — operator kill-switch revoke/all denies everyone
# =====================================================================


def test_e2_kill_switch_revoke_all_denies_everyone(backend: Backend, expect) -> None:
    """E2 | The kill-switch revoke/all denies everyone (PoC-HOLE).

    PoC has no kill-switch (the hole). Fleet: revoke/all over the SO_PEERCRED
    operator UDS denies every existing exec AND every new create. KEYSTONE:
    resume/all clears it — a toggle, not a one-way crash.
    """
    sc = expect("E2")
    assert sc["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # [PoC-HOLE] side: the boundary is absent. The backend signals it with
        # PocHoleNotEnforced; catching that IS the finding this scenario records.
        with pytest.raises(PocHoleNotEnforced):
            backend.revoke_all()
        return

    # Fleet side: create a live session, then revoke/all and assert BOTH arms.
    sess = backend.create_session()
    assert sess.status == "active", f"expected active session, got {sess.status}"

    revoke_status = _operator_post("/v1alpha/revoke/all")
    assert revoke_status in (200, 204), f"revoke/all should accept, got {revoke_status}"

    # Arm 1: the existing session's exec is denied.
    denied_exec = backend.exec_sh("echo should-be-denied")
    assert denied_exec.denied, "existing exec must be denied after revoke/all"

    # Arm 2: a new create is denied too (not just existing sessions).
    new_create = backend.create_session()
    assert new_create.status != "active", (
        f"new create must be denied under revoke/all, got {new_create.status}"
    )
    assert new_create.status.startswith("denied"), (
        f"expected a denied status class, got {new_create.status}"
    )

    # KEYSTONE: resume/all clears the latch (toggle, not a crash). After resume,
    # a fresh create must succeed again.
    resume_status = _operator_post("/v1alpha/resume/all")
    assert resume_status in (200, 204), f"resume/all should accept, got {resume_status}"
    cleared = backend.create_session()
    assert cleared.status == "active", (
        "resume/all must clear the kill-switch (keystone: it is a toggle); "
        f"post-resume create was {cleared.status}"
    )


# =====================================================================
# E3 — resume/all restores new sessions; pre-revoke stay denied
# =====================================================================


def test_e3_resume_restores_new_but_keeps_revoked_denied(backend: Backend, expect) -> None:
    """E3 | resume/all restores new sessions (HARDENED).

    Fleet: after revoke/all then resume/all, a NEW create succeeds, but a
    session that was killed before the resume stays denied. KEYSTONE: resume
    does NOT un-revoke an already-killed session.
    """
    sc = expect("E3")
    assert sc["bucket"] == "HARDENED"

    if backend.name == "poc":
        # No kill-switch, so nothing to resume — the recorded absence.
        with pytest.raises(PocHoleNotEnforced):
            backend.resume_all()
        return

    # Create a session that will be killed by revoke/all (pre-revoke session).
    pre = backend.create_session()
    assert pre.status == "active", f"expected active session, got {pre.status}"
    pre_key = pre.key
    assert pre_key, "control must return a key for the pre-revoke session"

    assert _operator_post("/v1alpha/revoke/all") in (200, 204)
    # The pre-revoke session is now denied.
    assert backend.exec_sh("true").denied, "pre-revoke session must be denied after revoke/all"

    assert _operator_post("/v1alpha/resume/all") in (200, 204)

    # A NEW create after resume succeeds (the HARDENED restore).
    fresh = backend.create_session()
    assert fresh.status == "active", (
        f"post-resume new create must succeed, got {fresh.status}"
    )

    # KEYSTONE: resume did NOT un-revoke the already-killed session. Its state
    # must still read denied/released/not_found — resume is not an un-revoke.
    revoked_state = backend.get_session(pre_key)
    assert revoked_state.status in ("denied", "released", "revoked", "not_found"), (
        "resume/all must NOT un-revoke an already-killed session "
        f"(keystone); {pre_key} reads {revoked_state.status}"
    )


# =====================================================================
# E4 — state durability / boot-reconcile across a control restart
# =====================================================================


def test_e4_state_survives_control_restart(backend: Backend, expect) -> None:
    """E4 | State durability / boot-reconcile (HARDENED).

    Fleet: a created session's row is durable in Postgres and survives a control
    restart. PoC: the container map is in-memory and lost on restart (the
    contrast). KEYSTONE: a never-created key still 404s after the restart —
    durability is not a blanket 200 that swallows unknown keys.
    """
    sc = expect("E4")
    assert sc["bucket"] == "HARDENED"

    if backend.name == "poc":
        # PoC contrast: session state is the in-memory container map. We do not
        # restart the PoC server here (that is an ops action outside the chat
        # scope); the recorded finding is the absence of a durable row. Assert
        # the observable in-memory nature: a created session reads active while
        # its container runs, and an unknown scope reads released (no durable
        # row that would answer otherwise).
        sess = backend.create_session()
        assert sess.status == "active"
        never = backend.get_session("never-created-poc-key")
        assert never.status == "released", (
            "PoC has no durable row; an unknown key reads released (in-memory), "
            f"got {never.status}"
        )
        return

    # Fleet: create, restart control, then GET must still return the row.
    sess = backend.create_session()
    assert sess.status == "active", f"expected active session, got {sess.status}"
    key = sess.key
    assert key, "control must return a session key"

    # A never-created key BEFORE the restart is 404 — capture the baseline so the
    # keystone shows durability is scoped, not a blanket 200.
    unknown_key = f"never-created-{int(time.time() * 1000)}"
    assert backend.get_session(unknown_key).status == "not_found"

    _restart_control()

    # The durable row survives the restart.
    after = backend.get_session(key)
    assert after.status not in ("not_found", "error"), (
        f"session {key} must survive a control restart (Postgres-durable); "
        f"post-restart status was {after.status}"
    )

    # KEYSTONE: the never-created key still 404s after the restart. Durability
    # answers real rows only; it does not manufacture a 200 for unknown keys.
    assert backend.get_session(unknown_key).status == "not_found", (
        "a never-created key must still 404 after the restart "
        "(keystone: durability is not a blanket 200)"
    )


# =====================================================================
# E5 — orphan row does not leak a quota slot (reconcile reclaim)
# =====================================================================


def test_e5_orphan_row_reclaimed_no_slot_leak(backend: Backend, expect) -> None:
    """E5 | An orphan row does not leak a quota slot (PoC-HOLE).

    Fleet: a container-less row (the guest crashed / was removed) is reconciled
    to released and its quota slot is returned; a fresh create then 201s WITHOUT
    a manual RevokeAll (the #93 self-heal). KEYSTONE: a LIVE session matched to
    its row is NOT killed by the reconcile.
    """
    sc = expect("E5")
    assert sc["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # [PoC-HOLE] side: there is no quota / reservation model to leak. The
        # finding is the absence of a row-vs-container reconciliation. A PoC
        # session is unbounded docker run; killing its container leaves no
        # leaked slot because there is no slot. Drive a REAL observable — the
        # docker-derived get_session() state, which runs `docker ps` on the
        # per-chat container — not the frozen create_session() "active" literal
        # (that constant never touches Docker, so an assert on it is vacuous).
        docker = _require_docker()
        sess = backend.create_session()
        # get_session probes `docker ps` for owui-chat-{key}: this is the real
        # container-state read the fleet reclaim is contrasted against. Whether
        # it reads active (container up) or released (no container), there is no
        # RESERVATION distinct from the container — the row-vs-container split
        # the fleet reconcile relies on does not exist on the PoC.
        observed = backend.get_session(sess.key)
        assert observed.status in ("active", "released"), (
            "PoC session state IS the container state (docker ps), with no "
            "reservation row that could leak a slot; this absence IS the E5 "
            f"finding recorded against the fleet reclaim, got {observed.status}"
        )
        # A subsequent create is unbounded (no cap to hit): the same container
        # state is observable, never a quota 409, because nothing was reserved.
        backend.create_session()
        again_observed = backend.get_session(sess.key)
        assert again_observed.status in ("active", "released"), (
            "PoC create is unbounded (no reservation to leak); a re-create reads "
            "the same container state, never a reclaim, "
            f"got {again_observed.status}"
        )
        return

    docker = _require_docker()

    # A live session whose row we will KEEP intact (the keystone: this must
    # survive reconcile untouched).
    live = backend.create_session()
    assert live.status == "active", f"expected active, got {live.status}"
    live_key = live.key
    assert live_key, "control must return a key for the live session"

    # An orphan-to-be: create a session, then remove its guest container out from
    # under control so its row is container-less. Address the guest by the
    # control-derived name ocu-sess-{key}.
    orphan = backend.create_session()
    assert orphan.status == "active", f"expected active, got {orphan.status}"
    orphan_key = orphan.key
    assert orphan_key, "control must return a key for the orphan session"

    orphan_cid = _guest_container_id(docker, orphan_key)
    if orphan_cid is None:
        pytest.skip(
            f"no guest container ocu-sess-{orphan_key} to remove "
            "(guest naming differs or not yet up). SKIP, not a pass."
        )
    rm = subprocess.run([docker, "rm", "-f", orphan_cid], capture_output=True, timeout=60)
    if rm.returncode != 0:
        pytest.skip(
            f"could not remove orphan guest {orphan_cid}: "
            f"{rm.stderr.decode('utf-8', 'replace')}. SKIP, not a pass."
        )

    _restart_control()

    # The orphan row is reclaimed to a released state (active -> released), and
    # its slot is returned. Assert the released end state (status class), not an
    # invented reclaim-at time.
    orphan_after = backend.get_session(orphan_key)
    assert orphan_after.status in ("released", "not_found"), (
        f"container-less orphan row must be reclaimed to released; got "
        f"{orphan_after.status}"
    )

    # Slot returned: a fresh create 201s WITHOUT a manual RevokeAll (the #93
    # self-heal). If the slot had leaked, this would 409 at the cap.
    fresh = backend.create_session()
    assert fresh.status == "active", (
        "a fresh create must 201 without a manual RevokeAll once the orphan slot "
        f"is reclaimed (#93 self-heal); got {fresh.status}"
    )

    # KEYSTONE: the LIVE session, matched to its row, is NOT killed by reconcile.
    live_after = backend.get_session(live_key)
    assert live_after.status not in ("released", "not_found", "denied"), (
        "a LIVE session matched to its row must survive reconcile "
        f"(keystone: reconcile reclaims orphans, not live rows); {live_key} "
        f"reads {live_after.status}"
    )


# =====================================================================
# E6 — a row-less container is killed on reconcile
# =====================================================================


def test_e6_rowless_container_killed_valid_row_survives(backend: Backend, expect) -> None:
    """E6 | A row-less container is killed (HARDENED).

    Fleet: a container with no owning row is killed on boot-reconcile. KEYSTONE:
    a container WITH a valid row survives the reconcile. No PoC analogue (no
    reconcile), so this is a fleet-only mechanic.
    """
    sc = expect("E6")
    assert sc["bucket"] == "HARDENED"
    _fleet_only(backend)

    docker = _require_docker()

    # Keystone anchor: a legitimate session whose container HAS a valid row.
    legit = backend.create_session()
    assert legit.status == "active", f"expected active, got {legit.status}"
    legit_key = legit.key
    assert legit_key, "control must return a key for the legit session"
    legit_cid = _guest_container_id(docker, legit_key)
    if legit_cid is None:
        pytest.skip(
            f"no guest container ocu-sess-{legit_key} to anchor the keystone. "
            "SKIP, not a pass."
        )

    # A stray, row-less MANAGED container: control's boot-reconcile lists only
    # the containers IT owns — filtered on the managed label ocu-session=true and
    # keyed by the ocu-session-name label, NOT by a name pattern (reconcile does
    # not kill arbitrary containers that merely share the ocu-sess- name shape).
    # So a genuine row-less orphan must carry BOTH labels with a session-name
    # control never issued a row for. Without the labels the container is
    # invisible to the sweep and this keystone would pass for the wrong reason.
    stray_key = f"stray-{int(time.time() * 1000)}"
    stray_name = f"ocu-sess-{stray_key}"
    run = subprocess.run(
        # `docker` and `stray_name` are harness-controlled: the name is built from a
        # literal prefix in this file. Stand config (`_SESSION_IMAGE`) is a single
        # argv element that docker execs directly, never through /bin/sh.
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
        [
            docker, "run", "-d", "--name", stray_name,
            "--label", "ocu-session=true",
            "--label", f"ocu-session-name={stray_key}",
            os.getenv("FLEET_STRAY_IMAGE", "busybox:latest"),
            "sh", "-c", "sleep 3600",
        ],
        capture_output=True,
        timeout=60,
    )
    if run.returncode != 0:
        pytest.skip(
            f"could not start a stray row-less container: "
            f"{run.stderr.decode('utf-8', 'replace')}. SKIP, not a pass."
        )
    stray_cid = run.stdout.decode("utf-8", "replace").strip()

    try:
        _restart_control()

        # The row-less container is killed on reconcile: it must no longer be
        # among the running containers.
        ps = subprocess.run(
            [docker, "ps", "--filter", f"name={stray_name}", "--format", "{{.ID}}"],
            capture_output=True,
            timeout=15,
        )
        still_running = ps.stdout.decode("utf-8", "replace").strip()
        assert not still_running, (
            f"a row-less container {stray_name} must be killed on reconcile; it "
            "is still running"
        )

        # KEYSTONE: the container WITH a valid row survives.
        legit_ps = subprocess.run(
            [docker, "ps", "--filter", f"id={legit_cid}", "--format", "{{.ID}}"],
            capture_output=True,
            timeout=15,
        )
        assert legit_ps.stdout.decode("utf-8", "replace").strip(), (
            "a container WITH a valid row must survive reconcile "
            "(keystone: reconcile kills row-less strays, not owned guests)"
        )
    finally:
        # Clean up the stray if it somehow survived (so a re-run is idempotent).
        # `docker` is the resolved binary path and `stray_cid` is a container id this
        # test itself created moments earlier. List argv, no shell.
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
        subprocess.run([docker, "rm", "-f", stray_cid], capture_output=True, timeout=30)


# =====================================================================
# E7 — concurrency is actually capped at the tier quota
# =====================================================================


def test_e7_quota_ceiling_capped_then_released(backend: Backend, expect) -> None:
    """E7 | Concurrency is actually capped (PoC-HOLE).

    Fleet: N sessions succeed, the N+1th 409s at the tier cap. KEYSTONE: after
    releasing one, a new create 201s again — a live counter, not a permanent
    wall. PoC: unbounded docker run (the hole).

    The cap value is deployment config; this reads it from FLEET_TIER_CAP
    (default 2, matching the demo tier) rather than inventing a number, and
    asserts the STATUS CLASS transition (all-ok up to cap, 409 at cap+1), not a
    specific N.
    """
    sc = expect("E7")
    assert sc["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # [PoC-HOLE] side: docker run is unbounded. The finding is the absence
        # of a cap — assert it through a REAL observable, not the frozen
        # create_session() "active" literal (that constant never touches Docker
        # and never carries a quota status, so an assert on it is vacuous). The
        # reddable observable is: NO create ever returns a quota-refusal status
        # class (denied:409), and the container-state read stays a real docker
        # ps result. On the fleet, the cap+1 create DOES return denied:409; its
        # absence here is the E7 finding.
        docker = _require_docker()
        beyond_cap = int(os.getenv("FLEET_TIER_CAP", "2")) + 1
        for i in range(beyond_cap):
            s = backend.create_session()
            # A quota-refusal status class must NEVER appear on the PoC — that
            # is the whole finding. This reds if create_session ever grew a cap.
            assert not s.status.startswith("denied"), (
                "PoC create is unbounded (no tier cap): create "
                f"#{i + 1} must not be refused for quota, got {s.status}"
            )
            # The observable session state is the docker ps container state, not
            # a reservation counter — read it to prove nothing was reserved.
            observed = backend.get_session(s.key)
            assert observed.status in ("active", "released"), (
                "PoC session state IS the container state (docker ps), with no "
                f"quota counter; got {observed.status}"
            )
        return

    # The deployed tier cap is a compile-time value (DimConcurrentSessions == 64
    # on this internal_workforce profile), not a small demo number, so a
    # fill-to-cap test would need 64 live gVisor guests — which would likely fail
    # on host memory before quota and give a false 409. Instead we arrange the
    # counter STATE and let the REAL admission code run against it: seeding the
    # counter to the cap is env-state arrangement (the create path still charges
    # and refuses through unmodified control code), not a mock.
    cap = _fleet_tier_cap()

    # Ensure a clean slate: resume any prior latch so a leftover deny does not
    # masquerade as a quota 409.
    if _operator_sock_reachable():
        _operator_post("/v1alpha/resume/all")

    # --- Cap enforcement: the counter AT the cap refuses the next create. ---
    _set_fleet_concurrent_counter(cap)
    overflow = backend.create_session()
    assert overflow.status == "denied:409", (
        f"a create with the concurrent-sessions counter AT the tier cap ({cap}) "
        f"must 409 at the ceiling, got {overflow.status}"
    )

    # --- Live counter: heal to the true live count, a fresh create 201s. ---
    # This proves the cap is a live counter, not a permanent wall: once the
    # counter reflects reality again, admission resumes. The counter was ARRANGED
    # to the cap above (no real rows behind that value), so the healer is boot
    # Reconcile Direction 3 (ReconcileConcurrent: heal the cell DOWN to the true
    # live-row count), NOT operator revoke/all -- revoke/all refunds PER KILLED
    # ROW and cannot reconcile a value that has no rows behind it. Model that
    # heal by resetting the counter to the live-row count the reconciler computes.
    _heal_concurrent_counter_to_live()
    freed = backend.create_session()
    assert freed.status == "active", (
        "after the counter is healed to the true live count a fresh create "
        f"must 201 again (live counter, not a permanent wall); got {freed.status}"
    )

    # --- KEYSTONE (the release-one invariant, asserted as counter parity). ---
    # "release one -> a slot frees" is exactly the operation the concurrent
    # counter must track. At the deployed cap of 64 a leak of 1 is invisible to a
    # create (1 < 64), so a create-based probe is vacuous here; assert the
    # counter itself instead. Drive the operator revoke/all (which releases every
    # row) and require the counter to fall to the true live-row count. The refund
    # LANDED (killswitch forceKillRow calls RefundConcurrent per killed row, canon
    # #53 d6d9b78), so this GREENS: after revoke/all with every row killed the
    # counter tracks the live-row count. It reds via real_finding only if the
    # counter drifts ABOVE the live rows (the leak regresses).
    if not _operator_sock_reachable():
        pytest.skip(
            "operator UDS not reachable: cannot drive the release keystone. "
            "SKIP, not a pass."
        )
    assert _operator_post("/v1alpha/revoke/all") in (200, 204)
    assert _operator_post("/v1alpha/resume/all") in (200, 204)
    counter, live_rows = _fleet_concurrent_counter_vs_rows()
    if counter is None:
        pytest.skip(
            "cannot read the concurrent-sessions counter from the control DB "
            "to assert the release keystone. SKIP, not a pass."
        )
    if counter <= live_rows:
        # Counter tracks reality after a release -> the invariant holds (fixed).
        return
    real_finding(
        "concurrency-counter-leak",
        f"operator revoke/all released every row but the DimConcurrentSessions "
        f"counter stayed at {counter} while only {live_rows} rows are live: "
        "RevokeAll/forceKillRow releases the row but never calls "
        "ReleaseConcurrency, so the concurrent counter leaks and a revoke/all "
        "permanently wedges the deployment at the tier cap. (Boot reconcile also "
        "misses this: it treats an EXITED-but-present container as live "
        "substrate, so it never reclaims the exited session's slot.)",
    )


# =====================================================================
# E8 — session-JWT expires mid-journey: clean 401, not a hang
# =====================================================================


def test_e8_session_jwt_expiry_surfaces_cleanly(backend: Backend, expect) -> None:
    """E8 | Expiry surfaces cleanly, not as a hang (HARDENED).

    Fleet: a mid-download the egress edge validates the weak session-JWT against
    control JWKS; an expired token yields a 401 envelope (not a hang / 500). The
    UI re-auths when the embed token's exp<=120s passes. KEYSTONE: within-exp the
    same download completes; an embed token past 120s drives a UI re-auth
    surface, not a blank frame.

    createFile write remains 501 until #304, and the full byte-download path is
    a browser hop (real Playwright click, never page.evaluate(fetch)). Where the
    live download / UI harness is not wired in this scaffold, the sub-check
    xfails with a reason — an honest recorded gap, not a silent pass. The
    non-browser envelope assertion (expired session-JWT -> 401 class at the edge)
    is asserted here directly.
    """
    sc = expect("E8")
    assert sc["bucket"] == "HARDENED"

    if backend.name == "poc":
        # PoC has no token: a download streams bytes with no expiry semantics.
        # The finding is the ABSENCE of an expiry envelope. Assert the observable
        # no-token behavior: a download of a non-existent file yields an HTTP
        # status (not a hang), and there is no 401-on-expiry path to exercise.
        result = backend.download("does-not-exist.docx")
        # PoC returns whatever the FastAPI route yields (e.g. 404); the point is
        # a clean HTTP status, never a hang. No token means no 401-on-expiry.
        assert result.status >= 200, "PoC download must return an HTTP status, not hang"
        assert result.refused is False, "PoC has no downloadable/expiry axis to refuse on"
        return

    # Fleet: assert the expiry ENVELOPE at the edge. A session whose JWT has
    # expired mid-journey must surface a 401 class (not a 500 / hang) when the
    # next exec / download-triggering op crosses the edge.
    #
    # Forcing a short-exp JWT is control-config (FLEET_SHORT_EXP_S); when that
    # knob is not wired into this env we cannot drive real expiry, so the
    # download-path expiry assertion is a recorded xfail rather than a fabricated
    # 401. The within-exp keystone (a fresh JWT completes) is asserted via a live
    # session's exec succeeding, proving the same path is not blanket-401.
    live = backend.create_session()
    assert live.status == "active", f"expected active session, got {live.status}"

    # The guest exec plane comes up asynchronously after create returns; an exec
    # issued before it is ready is denied (a boot race, not an expiry). Wait for
    # readiness so the keystone below measures the JWT path, not the race.
    await_fleet_exec_ready(backend)

    # KEYSTONE (within-exp path works): a fresh, currently-valid session exec
    # completes — the edge/exec path is not a blanket 401, so a later expiry-401
    # is attributable to expiry, not to the path being broken.
    within = backend.exec_sh("true")
    assert not within.denied, "a within-exp session op must complete (keystone)"

    short_exp = os.getenv("FLEET_SHORT_EXP_S")
    if not short_exp:
        # No short-exp knob wired: the expiry-401 envelope is a recorded gap, not
        # a silent pass. The within-exp keystone above IS asserted.
        pytest.xfail(
            "FLEET_SHORT_EXP_S not set: cannot mint a mid-journey-expiring "
            "session-JWT in this env. The within-exp keystone is asserted; the "
            "expired -> 401 envelope is a recorded gap (assert-envelope-until "
            "the short-exp knob is wired), not a fake green."
        )

    # With a short-exp JWT wired, wait past expiry then assert the 401 envelope
    # on the next edge-crossing op. Assert the STATUS CLASS (denied), not an
    # invented body — the 401 BoundedReason body is TBD-shaped at this layer.
    time.sleep(float(short_exp) + 1.0)
    expired = backend.exec_sh("true")
    assert expired.denied, (
        "an expired session-JWT must surface a deny (401 class) at the edge, "
        "not a hang or 500"
    )

    # -- Embed-token re-auth surface (browser hop) --------------------------
    # The UI re-auths when the embed token exp<=120s passes. This is a REAL
    # browser fill+click (Playwright), never page.evaluate(fetch). Playwright is
    # imported behind importorskip so an unwired browser harness is an honest
    # skip, not a silent pass.
    pytest.importorskip(
        "playwright.sync_api",
        reason=(
            "Playwright not installed: the embed-token re-auth surface is a real "
            "browser fill+click hop, driven in the browser journey. This is a "
            "SKIP of the browser sub-check, not a pass."
        ),
    )
    # The live browser harness (page navigation to the embed URL, waiting past
    # 120s, asserting a re-auth prompt renders rather than a blank frame) is
    # bound by the browser group test against the live UI. It is intentionally
    # not driven via page.evaluate(fetch); when the browser fixture lands here it
    # performs a real fill+click on the re-auth surface.
    pytest.xfail(
        "embed-token re-auth is a browser fill+click hop bound by the browser "
        "group test against the live web UI; asserted there with a real "
        "Playwright click, not here. Recorded gap, not a silent pass."
    )
