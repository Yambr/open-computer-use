# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""Pytest fixtures for the PoC-vs-fleet journey suite.

The core fixture is ``backend``, parametrized over ["poc", "fleet"]. It
instantiates the right backend and SKIPS — loudly — when that backend's
live() is False. It never xpasses, never stubs, never substitutes a mock for
a down stack.

Honesty rules encoded here (non-negotiable):
  * skip-if-inapplicable != skip-green. A skipped backend is reported skipped
    with a reason; it is not counted as a pass.
  * A mechanism that is inactive in the current env is an xfail(reason), not a
    silent pass. Use the ``inactive_mechanism`` helper to mark it.
  * A backend that has no analogue for an authz boundary raises
    PocHoleNotEnforced; the paired [PoC-HOLE] test catches that as the finding.
    That is distinct from a skip (the stack is up; the boundary is absent).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from backends.base import Backend, BackendUnavailable
from backends.fleet import FleetBackend
from backends.poc import PocBackend

_SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.yaml"


def pytest_configure(config):
    """Register the backend markers so a fleet-only group (e.g. the gateway
    north-edge group H) does not emit an unknown-mark warning."""
    config.addinivalue_line("markers", "fleet: fleet-backend-only test (no PoC counterpart)")
    config.addinivalue_line("markers", "poc: poc-backend-only test")

# Loud skip reasons — a reader scanning `pytest -rs` output sees exactly why a
# backend did not run. Never a bare "skipped".
_POC_DOWN = (
    "PoC backend not live: local Docker daemon unreachable. "
    "Bring up docker-compose.yml + docker-compose.webui.yml, then re-run. "
    "This is a SKIP, not a pass — do not read it as green."
)
_FLEET_DOWN = (
    "Fleet backend not live: Lima + runsc not detected (FUSE/runsc cannot run "
    "on a Darwin host) or the fleet compose is down. Run inside Lima (ocu-linux) "
    "with `deploy/fleet/docker-compose.fleet.yml` up. This is a LOUD SKIP, not a "
    "pass — the fleet is never mocked green."
)

_BACKEND_FACTORIES: dict[str, Callable[[], Backend]] = {
    "poc": PocBackend,
    "fleet": FleetBackend,
}
_BACKEND_DOWN_REASON: dict[str, str] = {"poc": _POC_DOWN, "fleet": _FLEET_DOWN}


def _load_scenarios() -> dict[str, dict[str, Any]]:
    with _SCENARIOS_PATH.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    by_id: dict[str, dict[str, Any]] = {}
    for entry in doc.get("scenarios", []):
        sid = entry["id"]
        if sid in by_id:
            raise ValueError(f"duplicate scenario id in scenarios.yaml: {sid}")
        by_id[sid] = entry
    return by_id


@pytest.fixture(scope="session")
def scenarios() -> dict[str, dict[str, Any]]:
    """All scenarios from scenarios.yaml, keyed by id (A1..G6)."""
    return _load_scenarios()


@pytest.fixture(params=["poc", "fleet"])
def backend(request: pytest.FixtureRequest) -> Backend:
    """The system under test, parametrized over both backends.

    Instantiates the requested backend and skips loudly if its live() is
    False. A live() probe that itself raises (a broken substrate) is also a
    skip with the same loud reason — never an error that masquerades as a pass.
    """
    name = request.param
    factory = _BACKEND_FACTORIES[name]
    impl = factory()
    try:
        is_live = impl.live()
    except BackendUnavailable as exc:
        pytest.skip(f"{_BACKEND_DOWN_REASON[name]} ({exc})")
    if not is_live:
        pytest.skip(_BACKEND_DOWN_REASON[name])
    yield impl
    # Per-test teardown: return every slot this test occupied via REAL verbs, so
    # the suite does not accumulate live sessions and trip the tier cap
    # order-dependently. A live session legitimately holds its slot until it is
    # ended (an exec exit does not end it -- the guest is a long-lived service).
    # The control plane reclaims abandoned sessions on its own only at the
    # idle-TTL (-session-idle-ttl, 15m on the stand) -- far longer than a suite
    # run, so a suite that bursts creates without destroying them exhausts the
    # tier cap (64) and every later create 409s, order-dependently. That is a
    # HARNESS obligation, not a product leak: the kill-switch refund and the
    # boot-reconcile counter recompute are both in the control build (verified
    # behaviorally: revoke-one decrements the live quota cell). So the test
    # client ends its own sessions the way a disconnecting client would: first
    # the per-session destroy verb for the hints it tracked, then the operator
    # revoke-all + resume-all sweep for any session this test created that the
    # hint-addressed destroy cannot reach (untracked per-chat sessions, rows a
    # lifecycle test already revoked). Both are REAL operator/gateway verbs --
    # never a DB-counter poke. resume-all lifts the deny so the next test's
    # create is admitted.
    if name == "fleet":
        destroy = getattr(impl, "destroy_all_sessions", None)
        if callable(destroy):
            try:
                destroy()
            except Exception:
                pass
        _fleet_operator_reclaim_slots()


# HARNESS SLOT HYGIENE (the [concurrency-counter-leak] this block once tracked
# is FIXED in the control build and verified behaviorally: the kill-switch
# refunds the DimConcurrentSessions slot on revoke -- a revoke-one decrements the
# live quota cell and tombstones the row -- and boot reconcile recomputes the
# counter from actual state. E7's counter-parity keystone witnesses the refund.)
#
# What remains is a HARNESS obligation: a live session legitimately holds its
# slot until destroyed or idle-reaped (-session-idle-ttl, 15m on the stand), and
# a suite run is shorter than the idle-TTL, so bursting creates without per-test
# reap exhausts the tier cap (64) and cascades 409s into unrelated tests. The
# sweep below returns the slots through the REAL operator verbs after each fleet
# test; it never pokes the DB counter.
_FLEET_CONTROL_DB = os.getenv("FLEET_CONTROL_DB_CONTAINER", "ocu-fleet-control-db-1")
_FLEET_DB_USER = os.getenv("FLEET_CONTROL_DB_USER", "ocu")
_FLEET_DB_NAME = os.getenv("FLEET_CONTROL_DB_NAME", "ocu_control")
_FLEET_RECLAIM = os.getenv("FLEET_RECLAIM_COUNTER_LEAK", "1") not in ("0", "", "false")
# The concurrent-sessions quota dimension id (state.DimConcurrentSessions == 0).
_FLEET_CONCURRENT_DIM = os.getenv("FLEET_CONCURRENT_DIM", "0")


_FLEET_OPERATOR_SOCK = os.getenv("FLEET_OPERATOR_SOCK", "/run/ocu-control/operator.sock")


def _fleet_operator_reclaim_slots() -> None:
    """Return every occupied slot via REAL operator verbs, then reap dead guests.

    The belt-and-suspenders half of the per-test teardown. It does NOT poke the
    DB counter — it drives the operator kill-switch the same way an incident
    responder would:

      1. POST /v1alpha/revoke/all  — force-releases every session ROW (and, on
         the @c978045 fix, ReleaseConcurrency returns the slot: F-1). Reaches
         sessions the hint-addressed destroy could not (already-revoked rows).
      2. docker rm -f any ocu-sess-* container left behind -- faster than
         waiting out the control idle-reaper (-session-idle-ttl, 15m on the
         stand); a lingering stopped guest holds its network endpoint.
      3. POST /v1alpha/resume/all  — lift the deny so the NEXT test's create is
         admitted (revoke-all engages deny-all; without resume every later
         create is refused).

    No-op (never fails a test) when docker / the operator socket is unreachable
    or when FLEET_RECLAIM_COUNTER_LEAK=0. All three are real verbs; the socket
    is the operator credential (0700 SO_PEERCRED), reached with sudo.

    The socket and the guest containers live where control runs. When the suite
    runs OUTSIDE that host (e.g. pytest on the workstation against a Lima VM),
    set FLEET_LIMA_INSTANCE to the Lima instance name: the sweep then executes
    its verbs inside the VM via ``limactl shell``. Without it, a socket path
    that does not exist locally makes every verb a silent no-op -- the exact
    failure mode that let a full-suite run leak dozens of sessions into the
    tier cap.
    """
    if not _FLEET_RECLAIM:
        return
    import shutil
    import subprocess

    if not _fleet_is_remote() and not shutil.which("curl"):
        return

    def _op(path: str) -> None:
        try:
            _fleet_exec(
                [
                    "sudo", "curl", "-sS", "--max-time", "10",
                    "--unix-socket", _FLEET_OPERATOR_SOCK,
                    "-X", "POST", f"http://localhost{path}",
                    "-H", "content-type: application/json",
                    "-d", '{"reason":"journey-suite per-test teardown"}',
                ],
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    _op("/v1alpha/revoke/all")
    try:
        ids = _fleet_exec(
            ["docker", "ps", "-aq", "--filter", "name=ocu-sess-"], timeout=20,
        ).stdout.split()
        if ids:
            _fleet_exec(["docker", "rm", "-f", *ids], timeout=40)
    except (OSError, subprocess.SubprocessError):
        pass
    _op("/v1alpha/resume/all")


def _fleet_is_remote() -> bool:
    """True when the operator socket lives in a Lima VM rather than this host."""
    return bool(os.getenv("FLEET_LIMA_INSTANCE", "")) and not os.path.exists(
        _FLEET_OPERATOR_SOCK
    )


def _fleet_exec(argv: list[str], timeout: float):
    """Run a sweep verb on the host that owns the operator socket.

    Local by default; routed through ``limactl shell $FLEET_LIMA_INSTANCE``
    when the socket is not present on this host (suite on the workstation,
    control in a Lima VM).
    """
    import shutil
    import subprocess

    if _fleet_is_remote():
        limactl = shutil.which("limactl")
        if not limactl:
            raise OSError("limactl not found for FLEET_LIMA_INSTANCE")
        argv = [limactl, "shell", os.environ["FLEET_LIMA_INSTANCE"], "--", *argv]
    # FLEET_LIMA_INSTANCE is operator-supplied stand configuration, set by whoever
    # already owns the Lima VM this shells into — same trust domain, no privilege
    # boundary crossed. Worth stating the sharp edge rather than hiding it: the
    # `limactl shell ... -- argv` leg rides ssh semantics, which JOIN argv into a
    # command line the VM's shell re-parses, so metacharacters in that value would
    # execute there. That is a real mechanism; it is acceptable only because the
    # value's author already has shell on that VM. It would NOT be acceptable for
    # a value reaching this from CI metadata or any untrusted source.
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _fleet_guests_present() -> bool:
    """Cheap guard: does any ocu-sess-* guest container exist right now?"""
    import subprocess

    try:
        out = _fleet_exec(
            ["docker", "ps", "-aq", "--filter", "name=ocu-sess-"], timeout=15,
        )
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.fixture(autouse=True)
def _fleet_slot_hygiene():
    """Reap fleet guest sessions after EVERY test, backend fixture or not.

    The direct-gateway tests (the I-group and friends) drive the fleet MCP
    endpoint with plain curl and never request the ``backend`` fixture, so its
    teardown sweep cannot cover them -- a full-module run used to leave every
    created guest holding its concurrency slot until the idle-TTL, wedging the
    tier cap for whatever ran next. This autouse fixture closes that class: it
    sweeps only when a guest container actually exists, so tests that created
    nothing pay one cheap docker-ps probe and no operator round-trips.
    """
    yield
    if _FLEET_RECLAIM and _fleet_guests_present():
        _fleet_operator_reclaim_slots()


# Back-compat alias: the E7 counter-parity keystone imports this name to reclaim
# the slots it deliberately filled to the cap. It now routes through the real
# operator kill-switch verbs (revoke-all + resume-all), never the DB counter.
_reclaim_fleet_concurrency_leak = _fleet_operator_reclaim_slots


@pytest.fixture
def expect(scenarios: dict[str, dict[str, Any]], backend: Backend) -> Callable[[str], dict[str, Any]]:
    """Look up a scenario's per-backend expectation by id.

    Returns a callable ``expect(scenario_id)`` -> a dict with:
        id, group, story, proves, bucket, keystone,
        expect       the poc_expect or fleet_expect string for THIS backend,
        backend      the backend name ("poc"/"fleet").

    A paired test uses this to assert the outcome its running backend is
    supposed to produce, so one test body reads correctly on both sides.
    """
    key = "poc_expect" if backend.name == "poc" else "fleet_expect"

    def _lookup(scenario_id: str) -> dict[str, Any]:
        sc = scenarios.get(scenario_id)
        if sc is None:
            raise KeyError(f"unknown scenario id: {scenario_id}")
        return {
            "id": sc["id"],
            "group": sc["group"],
            "story": sc["story"],
            "proves": sc["proves"],
            "bucket": sc["bucket"],
            "keystone": sc["keystone"],
            "expect": sc[key],
            "backend": backend.name,
        }

    return _lookup


def inactive_mechanism(reason: str) -> None:
    """Mark the current test as xfail because a mechanism is inactive here.

    Use when the invariant is real but the substrate cannot exercise it in
    this env (e.g. a read-only cgroupfs disables a leaf-kill, or a :ro bind is
    unenforced under a given driver). This is an xfail with a reason — a
    RECORDED gap — never a silent pass. If the mechanism is genuinely absent
    (a boundary that does not exist), that is a PoC-HOLE finding, not this.
    """
    pytest.xfail(f"mechanism inactive in this environment: {reason}")


def real_finding(issue: str, reason: str) -> None:
    """Mark the current test xfail because the PRODUCT invariant is broken.

    Distinct from ``inactive_mechanism``: this is NOT "the env can't exercise
    the mechanism". It is "the mechanism ran and the product genuinely VIOLATES
    the invariant" — a live-reproduced defect. It is recorded as an xfail so the
    finding is visible in ``pytest -rx`` (a known, issue-linked gap) rather than
    an unexplained red that gets normalised and then masks a regression.

    Two honesty rules the caller MUST keep for this to stay non-vacuous:
      * Call it ONLY after asserting the SPECIFIC broken signature (e.g. the
        read-back is empty, the external host was reached). If the invariant is
        later restored, that prior assertion fails LOUDLY (red) instead of a
        silent xpass — imperative xfail cannot be strict, so the caller's own
        signature assertion is the strictness backstop.
      * ``issue`` names the tracking issue so ``-rx`` is not a dead end.
    """
    pytest.xfail(f"REAL-FINDING [{issue}]: {reason}")


_FLEET_EXEC_READY_TIMEOUT_S = float(os.getenv("FLEET_EXEC_READY_TIMEOUT_S", "20"))


def await_fleet_exec_ready(backend: Backend) -> None:
    """Poll a marker echo until the guest exec plane is warm (fleet only).

    A fleet create returns on row-reservation; the guest's exec listener (the
    boot-child) binds a couple of seconds later. An exec fired at first-bind is
    refused, and — the trap this gate closes — an exec fired in the narrow
    just-bound window runs (exit 0) but returns EMPTY stdout, so a
    "true"-and-exit-0 probe declares ready while the stdout capture is not yet
    warm. A following burst then reads empty and a cross-talk / round-trip check
    reds for the wrong reason.

    So the probe ECHOES a marker and requires the marker to come BACK in stdout,
    twice in a row, before declaring ready — this proves the stdout path is warm,
    not merely that the process ran. No-op on the PoC (exec-ready at create).
    Loud-skips if the guest never warms within the bound — a genuine boot
    failure, not a passing state.
    """
    if getattr(backend, "name", "") != "fleet":
        return
    marker = b"__ocu_exec_ready__"
    argv = ["/bin/busybox", "echo", marker.decode("ascii")]
    deadline = time.monotonic() + _FLEET_EXEC_READY_TIMEOUT_S
    consecutive = 0
    last = ""
    while time.monotonic() < deadline:
        try:
            res = backend.exec(argv)
        except BackendUnavailable as exc:
            last = str(exc)
            consecutive = 0
            time.sleep(0.4)
            continue
        if not res.denied and res.exit_code == 0 and marker in res.stdout:
            consecutive += 1
            if consecutive >= 2:
                return
        else:
            consecutive = 0
            last = (
                f"denied={res.denied} exit={res.exit_code} "
                f"stdout={res.stdout[:32]!r}"
            )
        time.sleep(0.4)
    pytest.skip(
        f"guest exec plane never warmed within {_FLEET_EXEC_READY_TIMEOUT_S}s "
        f"(last: {last}). SKIP, not a pass."
    )
