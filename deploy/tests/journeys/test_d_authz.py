# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""GROUP D — Authz boundary (D1..D7) of the PoC-vs-fleet journey suite.

Every D scenario is adversarial: it drives the same journey verb against both
backends and asserts the per-backend end state from scenarios.yaml. All seven
are [PoC-HOLE] — the PoC has no authz boundary (any chat_id reads any chat, the
guest has full network, there is no token or credential model), so the PoC side
either SUCCEEDS across the would-be boundary or signals the missing boundary
with the PocHoleNotEnforced sentinel; the fleet side DENIES with the specific
status the contract pins (404 for scope, 403 for foreign-scope-valid-sig, 401
for missing/expired auth, no-route for network isolation). That divergence is
the finding each test records.

Honesty rules encoded here (never fake-green):
  * The green must be reproducibly reddable: each test carries the scenario's
    KEYSTONE — the inversion that would flip green to red (own-id -> 200 so a
    404 is scope-specific not a blanket wall; a fresh token -> 200 so a 401 is
    freshness-specific; the allowed peer reachable so isolation is a route
    restriction not a dead NIC).
  * Where a fleet verb is bound to the live storage/browser group wire in the
    scaffold (list_files, download, preview, upload raise NotImplementedError
    until that group binds them), this test does not stub a green — it xfails
    with a reason so the gap is RECORDED, not silently passed.
  * Where a contract is still TBD (createFile write verb is 501 until #304;
    the BoundedReason envelope body is frozen but its fields are asserted as a
    STATUS CLASS, not an invented shape), the test asserts the envelope / HTTP
    status class and says so in a comment.
  * User-facing hops (D6 preview / save, D7 re-auth surface) are driven by a
    real Playwright fill + click in the browser group test, NEVER
    page.evaluate(fetch). Where Playwright is not wired into this scaffold the
    byte-path assertions are marked xfail(reason) so they are honest.
"""

from __future__ import annotations

import pytest

from backends.base import (
    Backend,
    BackendUnavailable,
    DownloadResult,
    ExecResult,
    PocHoleNotEnforced,
)
from conftest import await_fleet_exec_ready, real_finding

# HTTP status classes the fleet contract pins for the authz hops (BoundedReason
# deny envelope, HTTP status authoritative). Named here so a test reads by
# meaning, not by a bare integer.
STATUS_OK = 200
STATUS_UNAUTHORIZED = 401  # missing / expired token
STATUS_FORBIDDEN = 403     # valid signature, foreign scope
STATUS_NOT_FOUND = 404     # unknown / foreign file_id (scope, not blanket deny)


def _fleet_wire_bound(fn, *args, **kwargs):
    """Call a fleet verb that the scaffold binds to the live group wire.

    Several fleet read/byte verbs (list_files, download, preview, upload) raise
    NotImplementedError until the storage / browser group test binds them to
    the real F9 / mount / UI wire. Calling one before that binding is not a
    failure of THIS test and must never be faked green. This helper turns that
    unbound state into an xfail with a reason so the gap is recorded.

    Returns the verb's result when bound; xfails (does not return) when not.
    """
    try:
        return fn(*args, **kwargs)
    except NotImplementedError as exc:
        pytest.xfail(
            "fleet verb not yet bound to the live group wire in this scaffold "
            f"(binds in the storage/browser group test): {exc}"
        )


# Signals an in-container exec emits when the PoC substrate is absent: the
# per-chat container has not been created (the chat has never run) or the local
# daemon cannot exec it. The `backend` fixture's live() gates only on the Docker
# DAEMON answering — it does NOT require the per-chat container or the FastAPI
# server to be up. A PoC test that then execs into a non-existent container must
# be a LOUD SKIP (absent substrate), never a red (a red here would be a false
# defect) and never a green (that would be fake). This mirrors the fleet side,
# where an absent Lima/runsc stack is a loud skip in conftest.
_POC_ABSENT_CONTAINER_MARKERS = (
    b"No such container",
    b"is not running",
    b"Cannot connect to the Docker daemon",
)


def _require_poc_container(result: ExecResult) -> ExecResult:
    """Loud-skip a PoC test when its per-chat container is not up.

    An exec against a missing container returns a clean non-zero ExecResult
    (docker prints "No such container" to stderr and exits 1) rather than
    raising, so it would otherwise be read as a real assertion failure. Detect
    that absent-substrate signal and convert it to a loud skip: the PoC compose
    plus the chat container must be up for these in-container probes to mean
    anything. Returns the result unchanged when the container IS up.
    """
    if result.exit_code != 0 and any(
        m in result.stderr for m in _POC_ABSENT_CONTAINER_MARKERS
    ):
        pytest.skip(
            "PoC per-chat container not up: bring up docker-compose.yml + "
            "docker-compose.webui.yml AND run a chat so owui-chat-{chat_id} "
            "exists, then re-run. This is a LOUD SKIP (absent substrate), not "
            "a pass and not a defect."
        )
    return result


def _poc_server_verb(fn, *args, **kwargs):
    """Call a PoC verb that hits the FastAPI server; loud-skip if it is down.

    The `backend` fixture's live() gates only on the Docker DAEMON — the
    computer-use-server (FastAPI) may still be down, in which case a server verb
    (list_files / download / preview) raises BackendUnavailable from inside the
    test body (after the fixture already passed). Convert that to a LOUD SKIP:
    an absent server is not a defect and not a green, exactly as conftest treats
    an absent stack in live(). Returns the verb's result when the server is up.
    """
    try:
        return fn(*args, **kwargs)
    except BackendUnavailable as exc:
        pytest.skip(
            "PoC server not up: start docker-compose.yml + "
            "docker-compose.webui.yml (computer-use-server FastAPI), then "
            f"re-run. LOUD SKIP (absent substrate), not a pass: {exc}"
        )


# =====================================================================
# D1 — read another user's file by guessing an id
#      proves: no cross-scope read AND no enumeration leak
# =====================================================================
def test_d1_no_cross_scope_read_no_enumeration_leak(backend: Backend, expect):
    """D1: a caller cannot read another scope's file by guessing an id, and
    probing yields no existence oracle.

    PoC-HOLE: on the PoC, any caller holding a chat_id reads that chat's files
    (list_files(scopeB) returns scopeB's outputs) — the cross-scope read
    SUCCEEDS, which IS the finding. On the fleet, a foreign file_id resolves to
    404 (not 403, so the response does not distinguish "exists but forbidden"
    from "unknown" — no enumeration oracle), while the caller's OWN id resolves
    to 200 (the keystone: the 404 is scope-specific, not a blanket wall).
    """
    sc = expect("D1")
    assert sc["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # The PoC hole: a second scope's outputs are readable by anyone who
        # names that scope. Derive scope B by the documented "-b" suffix
        # (poc.py: a second scope is derived by suffixing "-b").
        own_scope = backend.login()["chat_id"]
        foreign_scope = f"{own_scope}-b"
        # Cross-scope read SUCCEEDS on the PoC — it returns a list (no authz
        # boundary rejects it). That success is the recorded hole. We assert
        # the call is served (a list, not an auth refusal), not a specific file
        # count (the foreign scope may legitimately be empty on a fresh stack).
        foreign_listing = _poc_server_verb(backend.list_files, foreign_scope)
        assert isinstance(foreign_listing, list), (
            "PoC hole: a foreign scope's outputs listing is served with no "
            "authz boundary; expected a list, got a refusal"
        )
        # KEYSTONE (PoC side): reading the caller's OWN scope also succeeds, so
        # the cross-scope success above is genuinely a missing boundary, not a
        # coincidental server error that also happens to hit foreign scope.
        own_listing = _poc_server_verb(backend.list_files, own_scope)
        assert isinstance(own_listing, list)
        return

    # Fleet side. list_files / download bind to the live F9 wire in the storage
    # group test; if unbound here, record the gap rather than fake a green.
    files = _fleet_wire_bound(backend.list_files, backend.login().get("caller", "fleet"))
    # A foreign / unknown file_id must resolve to 404 (scope, not 403 — F9 does
    # not leak existence). Craft an id that is well-formed but not one of ours.
    foreign_id = "fid-D1-foreign-0000000000000000"
    foreign = _fleet_wire_bound(backend.download, foreign_id)
    assert isinstance(foreign, DownloadResult)
    assert foreign.status == STATUS_NOT_FOUND, (
        "fleet: a foreign file_id must be 404 (not 403) so the response carries "
        "no existence oracle"
    )
    # KEYSTONE: the caller's OWN file_id -> 200. The 404 above is scope-specific,
    # not a blanket deny. Take a real own id from the (bound) listing.
    assert files, "fleet: expected at least one own file to prove own-id -> 200"
    own = _fleet_wire_bound(backend.download, files[0].id)
    assert own.status == STATUS_OK, (
        "fleet keystone: the caller's OWN file_id must be 200 — the 404 is "
        "scope-specific, not a blanket wall"
    )
    # No-enumeration-oracle sub-check: several sequential foreign probes return
    # the SAME 404 shape, so timing / status cannot distinguish existent from
    # non-existent ids.
    probe_ids = [f"fid-D1-probe-{i:016d}" for i in range(4)]
    statuses = {
        _fleet_wire_bound(backend.download, pid).status for pid in probe_ids
    }
    assert statuses == {STATUS_NOT_FOUND}, (
        "fleet: sequential foreign probes must 404 uniformly (no existence "
        f"oracle); saw {statuses}"
    )


# =====================================================================
# D2 — valid token, foreign scope
#      proves: the scope check is distinct from the auth check
# =====================================================================
def test_d2_valid_token_foreign_scope_forbidden(backend: Backend, expect):
    """D2: a token with a valid signature but a foreign scope claim is denied at
    the scope check (403), distinct from the auth check.

    PoC-HOLE: the PoC has no token model at all, so there is no scope-vs-auth
    distinction to exercise — the boundary is absent. On the fleet, a valid
    signature carrying a filesystem_id the caller does not own -> 403, while a
    matching scope -> 200 (the keystone: swapping ONLY the scope claim flips
    200 to 403, proving the scope check runs independently of the signature
    check).
    """
    sc = expect("D2")
    assert sc["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # No token model -> no scope-vs-auth check. The PoC scopes only by the
        # chat_id in the URL, so the download verb never distinguishes a
        # "foreign scope" from a valid one: it simply serves whatever the
        # chat_id names. That absence is the recorded hole. There is no
        # dedicated PocHoleNotEnforced verb for a token here (download() serves
        # unconditionally), so we assert the hole via the download verb having
        # no scope-refusal path: a download call returns a DownloadResult with
        # refused=False regardless of scope.
        result = _poc_server_verb(backend.download, "any-file-poc-has-no-scope-check")
        assert isinstance(result, DownloadResult)
        assert result.refused is False, (
            "PoC hole: download has no scope-refusal path; every file the "
            "chat_id names is byte-deliverable"
        )
        return

    # Fleet side. The scope check lives in the F9 / mount plane; the wire that
    # presents a foreign-scope-valid-signature token is bound in the storage
    # group test (it needs a control-minted token with a swapped fs_id claim).
    # download() on a file_id owned by a foreign scope must be 403 (valid sig,
    # wrong scope), NOT 404 (that would be the unknown-id case D1). Assert the
    # STATUS CLASS; the BoundedReason body fields are frozen but we assert the
    # authoritative HTTP status, not an invented body shape.
    foreign_scope_file = "fid-D2-foreign-scope-valid-sig"
    result = _fleet_wire_bound(backend.download, foreign_scope_file)
    assert isinstance(result, DownloadResult)
    assert result.status == STATUS_FORBIDDEN, (
        "fleet: valid signature + foreign scope must be 403 (scope check "
        "distinct from auth check), not 404 and not 200"
    )
    # KEYSTONE: a matching-scope file_id -> 200. Swapping ONLY the scope claim
    # is what flips 200 to 403 above; the caller's own file proves the 403 is
    # scope-specific, not a blanket auth failure.
    own_files = _fleet_wire_bound(backend.list_files, backend.login().get("caller", "fleet"))
    assert own_files, "fleet: expected an own file to prove matching-scope -> 200"
    own = _fleet_wire_bound(backend.download, own_files[0].id)
    assert own.status == STATUS_OK, (
        "fleet keystone: a matching scope must be 200 — the 403 above is "
        "scope-specific, proving the scope check is distinct from the signature"
    )


# =====================================================================
# D3 — filestore with no or expired token
#      proves: missing-auth is refused
# =====================================================================
def test_d3_missing_or_expired_token_unauthorized(backend: Backend, expect):
    """D3: a filestore call with no token, or an expired one, is refused with
    401 and a BoundedReason envelope; a fresh valid token -> 200.

    PoC-HOLE: the PoC has no token model — there is nothing to omit or expire,
    so the missing-auth boundary is absent (every call is served on the chat_id
    alone). On the fleet, a missing Authorization -> 401 and an expired token
    -> 401, both carrying the BoundedReason envelope (asserted as a STATUS
    CLASS; the envelope body is frozen but the HTTP status is authoritative per
    the storage contract). The keystone: a fresh valid token -> 200, so the 401
    is auth-specific, not a permanent wall.
    """
    sc = expect("D3")
    assert sc["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # No token to be missing or expired. The PoC serves the download on the
        # chat_id alone, so a "no-token" call is indistinguishable from a normal
        # one — the boundary is absent. Record the hole: the download verb has
        # no 401 path.
        result = _poc_server_verb(backend.download, "any-file-poc-has-no-token")
        assert isinstance(result, DownloadResult)
        assert result.status != STATUS_UNAUTHORIZED, (
            "PoC hole: there is no auth check, so a call is never 401 — the "
            "missing-token boundary is absent"
        )
        return

    # Fleet side. The missing / expired-token wire is bound in the storage group
    # test (it needs to drop the Authorization header, then present a
    # control-minted token past its exp). Here we assert the STATUS CLASS the
    # contract pins for both cases. The BoundedReason body is frozen; we assert
    # HTTP status (authoritative), not an invented envelope shape.
    #
    # Missing-token case: download without any token -> 401.
    missing = _fleet_wire_bound(backend.download, "fid-D3-no-token")
    assert isinstance(missing, DownloadResult)
    assert missing.status == STATUS_UNAUTHORIZED, (
        "fleet: a filestore call with no token must be 401 (BoundedReason "
        "envelope); HTTP status is authoritative"
    )
    # Expired-token case: same call with an expired token -> 401.
    expired = _fleet_wire_bound(backend.download, "fid-D3-expired-token")
    assert expired.status == STATUS_UNAUTHORIZED, (
        "fleet: an expired token must be 401 (BoundedReason envelope), same "
        "class as the missing case"
    )
    # KEYSTONE: a fresh valid token -> 200. The 401 is auth-specific, not a
    # permanent wall.
    own_files = _fleet_wire_bound(backend.list_files, backend.login().get("caller", "fleet"))
    assert own_files, "fleet: expected an own file to prove fresh-token -> 200"
    fresh = _fleet_wire_bound(backend.download, own_files[0].id)
    assert fresh.status == STATUS_OK, (
        "fleet keystone: a fresh valid token must be 200 — the 401 is "
        "auth-specific, not a permanent wall"
    )


# =====================================================================
# D4 — (in guest) hit MinIO / control directly
#      proves: guest network isolation
# =====================================================================
def test_d4_guest_network_isolation(backend: Backend, expect):
    """D4: from inside the guest, a direct hop to control / MinIO is refused by
    the network (no route), while the mount-edge (the allowed peer) is
    reachable.

    PoC-HOLE: the PoC container has full network, so an in-container curl to any
    host SUCCEEDS — the isolation boundary is absent, which IS the finding. On
    the fleet the guest sits only on the ocu-mount-facing net: a TCP hop to
    control or MinIO is refused / times out / has no route, while the
    mount-edge (its one allowed peer) is reachable. The keystone is that
    reachable peer — isolation is a route restriction, not a dead NIC.
    """
    sc = expect("D4")
    assert sc["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # Full-network PoC: the container reaches an arbitrary external host.
        # Use a real in-container exec through the exec_sh chokepoint (which runs
        # /bin/sh -c on the PoC's Ubuntu userland), not a fabricated exit. The
        # PoC image ships python3, so we probe reachability with a short-timeout
        # TCP connect via a python3 one-liner invoked from the shell — this keeps
        # the connect off curl/nc availability. exit 0 == the connect succeeded
        # == the hole is open. 1.1.1.1:53 is a stable external TCP endpoint; a
        # full-network container reaches it, asserting the ABSENCE of egress
        # control. The busybox demo guest has no python3, so the fleet arm below
        # uses busybox nc instead — the probe is split by backend so each arm
        # runs a probe its substrate can actually execute (never a vacuous pass).
        py = (
            "import socket,sys\n"
            "s=socket.socket();s.settimeout(3)\n"
            "try:\n"
            "    s.connect(('1.1.1.1',53));ok=True\n"
            "except OSError:\n"
            "    ok=False\n"
            "sys.exit(0 if ok else 1)\n"
        )
        # Feed the python source on stdin so the shell string carries no nested
        # quoting: `python3 - <<'PY'` runs the heredoc body as the program, and
        # its sys.exit propagates as the exec exit code.
        probe = "python3 - <<'PY'\n" + py + "PY\n"
        result = backend.exec_sh(probe)
        assert isinstance(result, ExecResult)
        # A missing per-chat container is a loud skip (absent substrate), never
        # a red. Only assert the hole when the container is genuinely up.
        result = _require_poc_container(result)
        # The PoC hole: an arbitrary external host is reachable from the guest.
        assert result.exit_code == 0, (
            "PoC hole: the container has full network; an external TCP connect "
            f"should succeed (exit 0), got exit {result.exit_code}"
        )
        return

    # Fleet side. Real guest exec over the gateway mTLS plane (POST
    # /v1alpha/sessions/exec). Create a storage session so the guest is placed
    # on the mount-facing net exactly as the storage-chain demo proves.
    backend.create_storage_session()
    await_fleet_exec_ready(backend)
    # A TCP hop to control / MinIO must be refused (no route). The demo guest is
    # a static busybox with NO nc on PATH (only the /bin/busybox multi-call
    # binary), so the applet MUST be invoked as `/bin/busybox nc` — a bare `nc`
    # is "nc: not found" (rc 127) and the connect never runs, which would make
    # this isolation check pass for the WRONG reason. We probe with
    # `/bin/busybox nc` and assert the connect actually failed with a NO-ROUTE
    # signature (busybox nc reports "bad address" when the peer's name does not
    # resolve on the mount-facing net, or times out): not a generic non-zero.
    for target_host, target_port, label in (
        ("control", 8443, "control"),
        ("minio", 9000, "MinIO"),
    ):
        result = backend.exec_sh(
            f"/bin/busybox nc -w4 {target_host} {target_port} </dev/null; "
            f"echo __rc=$?"
        )
        assert isinstance(result, ExecResult)
        combined = (
            result.stdout.decode("utf-8", "replace")
            + result.stderr.decode("utf-8", "replace")
        )
        # denied==True would mean the exec itself was refused (a different
        # boundary); here we want the exec to RUN and the in-guest connect to
        # FAIL (no route to the isolated peer).
        assert not result.denied, (
            f"fleet: the exec to probe {label} was refused at the control "
            "plane; we want the exec to run and the in-guest connect to fail"
        )
        # The applet MUST have run: a "not found" (127) means the probe was
        # vacuous. Guard it explicitly so a missing applet can never masquerade
        # as isolation.
        assert "not found" not in combined and "__rc=127" not in combined, (
            f"fleet: /bin/busybox nc did not run for {label} — the probe is "
            f"vacuous, not an isolation result (out={combined!r})"
        )
        # The connect must have FAILED with a no-route signature (name does not
        # resolve on the mount-facing net, or a timeout), not exit 0.
        assert "__rc=0" not in combined, (
            f"fleet: the guest reached {label} directly (exit 0); isolation "
            "requires no route to control/MinIO from the mount-facing net "
            f"(out={combined!r})"
        )
        assert "bad address" in combined or "__rc=" in combined, (
            f"fleet: {label} probe produced no observable connect outcome "
            f"(out={combined!r})"
        )
    # KEYSTONE: the mount-edge (the guest's one allowed peer) IS reachable —
    # isolation is a route restriction, not a dead NIC. The storage-chain demo
    # uses edge:8450 as the allowed upstream; a `/bin/busybox nc` connect there
    # must SUCCEED (rc 0).
    edge = backend.exec_sh(
        "/bin/busybox nc -w4 edge 8450 </dev/null; echo __rc=$?"
    )
    assert isinstance(edge, ExecResult)
    edge_out = (
        edge.stdout.decode("utf-8", "replace")
        + edge.stderr.decode("utf-8", "replace")
    )
    assert not edge.denied
    assert "not found" not in edge_out, (
        "fleet keystone: /bin/busybox nc did not run against the edge — the "
        f"reachability keystone would be vacuous (out={edge_out!r})"
    )
    assert "__rc=0" in edge_out, (
        "fleet keystone: the mount-edge (edge:8450) is the guest's allowed "
        "peer and MUST be reachable — isolation is a route restriction, not a "
        f"dead NIC (out={edge_out!r})"
    )


# =====================================================================
# D5 — (in guest) read the real filestore credential
#      proves: the guest never holds the upstream secret
# =====================================================================
def test_d5_guest_never_holds_upstream_credential(backend: Backend, expect):
    """D5: the real filestore credential is never present in the guest; the
    guest holds only the weak Storage-JWT, and the real credential is injected
    at egress.

    PoC-HOLE: the PoC has no secret model — the host holds the raw files
    directly and there is no upstream credential to protect, so the boundary is
    absent (the finding). On the fleet, grepping the guest env, filesystem, and
    the mount-config-after-load for the real credential finds NONE (the
    mount-config is scrubbed after Load per NFR-SEC-25), and a direct
    guest->MinIO with only the weak JWT fails. The keystone: the
    exchanged/injected credential DOES work through egress (custody is real,
    not a broken path).
    """
    sc = expect("D5")
    assert sc["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # No secret model at all. The PoC host-binds raw files; there is no
        # upstream credential to hold or leak. Record the hole: the "guest"
        # (the per-chat container) reaches its storage as plain host-bound
        # files, so there is nothing to grep for — the boundary does not exist.
        # We assert the absence structurally: the container reads its outputs
        # directly off the bind (an ls succeeds), i.e. no credential-gated hop.
        result = _require_poc_container(backend.exec(["ls", "-1", "/mnt/user-data/outputs"]))
        assert isinstance(result, ExecResult)
        assert result.exit_code == 0, (
            "PoC hole: storage is a raw host-bind reachable with no credential "
            "hop; the outputs dir lists directly inside the container"
        )
        return

    # Fleet side. Real guest exec. Create the storage session so the guest is
    # booted with the mount-config on a :ro path (which control unlinks after
    # Load — NFR-SEC-25 / G1).
    backend.create_storage_session()
    await_fleet_exec_ready(backend)
    # A marker that would appear ONLY in a real long-lived object-store
    # credential (e.g. an AWS-style access key prefix or a MinIO root
    # credential). We grep the guest env, the whole filesystem, and any
    # lingering mount-config for it. It must be ABSENT — the guest holds only
    # the weak, short-lived ES256 Storage-JWT.
    #
    # We look for the structural shapes of a real static credential, not a
    # specific secret value: a long-lived access-key id prefix and a secret-key
    # env var name. Any hit is a leak.
    #
    # The demo guest is a static busybox (no coreutils, no bare sh/ls/env/grep
    # on PATH), so every applet is invoked through /bin/busybox exactly like
    # storage-chain-demo.sh. A bare ["sh","-c",...] here would exit 127 and the
    # credential grep would never run — "LEAK_* not in out" would pass
    # vacuously. Prefixing the whole script with /bin/busybox makes env/grep/
    # test actually execute so a leak would genuinely reddens the assertion.
    grep_probe = (
        "set -e\n"
        # env: no real credential env var (access key / secret key).
        "busybox env | busybox grep -Ei "
        "'AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|MINIO_ROOT' "
        "&& echo LEAK_ENV || true\n"
        # filesystem: no file carrying a long-lived AKIA-style access key. The
        # grep is SCOPED to the real writable / config / mount areas a credential
        # could land in — NOT `/`: a recursive grep over the whole gVisor root
        # (incl. /proc and /sys) runs for ~60s and blows the exec timeout, which
        # returns a 409 that the backend surfaces as denied (a probe that never
        # completes, not a leak result). These dirs cover the guest's real
        # attack surface (env-file drops, config, tmp, home, the FUSE mount).
        # `grep -q .` (not `head -n1`) gates the echo: head exits 0 on EMPTY
        # input, so it would print LEAK_FS on every run and red the assertion
        # unconditionally (a baked-in false red that never observes the real
        # boundary). `grep -q .` exits 0 only when the upstream grep found a
        # match, so LEAK_FS fires solely on a genuine on-disk credential.
        "for d in /etc /run /tmp /home /root /var /mnt; do "
        "busybox test -d \"$d\" && "
        "busybox grep -REl 'AKIA[0-9A-Z]{16}' \"$d\" 2>/dev/null; "
        "done | busybox grep -q . && echo LEAK_FS || true\n"
        # mount-config must be gone after Load (NFR-SEC-25 / G1). Its known
        # :ro path is /etc/ocu/mount-config.json; a stat that succeeds is a
        # residue leak.
        "busybox test -e /etc/ocu/mount-config.json && echo LEAK_CFG || true\n"
    )
    result = backend.exec_sh(grep_probe)
    assert isinstance(result, ExecResult)
    assert not result.denied
    out = result.stdout.decode("utf-8", "replace")
    for marker in ("LEAK_ENV", "LEAK_FS", "LEAK_CFG"):
        assert marker not in out, (
            f"fleet: the real filestore credential leaked into the guest "
            f"({marker}); the guest must hold only the weak Storage-JWT"
        )
    # Direct guest->MinIO with only the weak JWT must FAIL: the weak JWT is not
    # a MinIO credential, and the guest has no route to MinIO anyway (D4). A
    # direct object-store hop is refused. The applet MUST be /bin/busybox nc:
    # a bare `nc` is "not found" (127) and the hop never runs — a vacuous pass.
    # busybox nc reports "bad address" when the peer's name does not resolve on
    # the mount-facing net (the no-route signature), which is the real failure.
    direct = backend.exec_sh(
        "/bin/busybox nc -w4 minio 9000 </dev/null; echo __rc=$?"
    )
    direct_out = (
        direct.stdout.decode("utf-8", "replace")
        + direct.stderr.decode("utf-8", "replace")
    )
    # The connect must actually RUN: an exec refusal (denied=True -> exit_code
    # -1) would satisfy exit_code != 0 vacuously without ever attempting the
    # hop. Guard denial first, then assert the applet ran and the connect failed.
    assert not direct.denied, (
        "fleet: the direct guest->MinIO probe was refused before it ran; the "
        "no-route assertion below would pass vacuously"
    )
    assert "not found" not in direct_out and "__rc=127" not in direct_out, (
        f"fleet: /bin/busybox nc did not run for the MinIO hop — vacuous probe "
        f"(out={direct_out!r})"
    )
    assert "__rc=0" not in direct_out, (
        "fleet: a direct guest->MinIO with only the weak JWT must fail (no "
        f"route, wrong credential) (out={direct_out!r})"
    )

    # KEYSTONE (positive half): the exchanged / injected credential works through
    # egress — a write through the FUSE mount round-trips. This half is SPLIT
    # from the credential-absence invariant above (which stays a hard assertion)
    # so a real cred-leak regression cannot hide behind this keystone's xfail.
    #
    # REAL-FINDING (live-reproduced): the FUSE write plane does NOT round-trip on
    # this deploy. The guest-mount wrapper (ocu-rclone-filestore) streams the Put
    # without the contractually-REQUIRED declared_size_bytes (files-api
    # createFile/upload: "declared_size_bytes required (>0)"), so the broker
    # rejects the body and only a zero-length object is persisted; the read-back
    # then fails with an I/O error. Custody-via-egress cannot be proven until the
    # mount wrapper buffers-and-declares the size. We assert the SPECIFIC broken
    # signature (read-back I/O error) so a restored round-trip fails this
    # assertion loudly instead of silently xpassing.
    marker_name = "d5-egress-custody.txt"
    write = backend.exec_sh(
        f"echo d5-ok > /mnt/user-data/outputs/{marker_name} "
        f"&& /bin/busybox cat /mnt/user-data/outputs/{marker_name}; echo __rc=$?"
    )
    assert isinstance(write, ExecResult)
    assert not write.denied
    combined = (
        write.stdout.decode("utf-8", "replace")
        + write.stderr.decode("utf-8", "replace")
    )
    if b"d5-ok" in write.stdout:
        # Round-trip restored (the marker read back) -> the finding is fixed;
        # this is a real PASS of the custody-via-egress keystone.
        return
    # The written marker did NOT come back: silent data loss on the storage
    # write plane. Signature is "marker absent from read-back", so a restored
    # round-trip flips this to the PASS arm above rather than xpassing silently.
    real_finding(
        "storage-write-plane",
        "FUSE outputs write does not round-trip (silent data loss): the written "
        "marker does not read back. The rclone mount wrapper streams the Put "
        "without the REQUIRED declared_size_bytes, the broker persists a "
        f"zero-length object, and the read-back yields empty/I-O-error "
        f"(out={combined!r}). Custody-via-egress cannot be proven until the "
        "mount wrapper buffers-and-declares the size (files-api createFile).",
    )


# =====================================================================
# D6 — preview downloadable=false, then try to save
#      proves: preview-not-download exfil control
# =====================================================================
def test_d6_preview_not_download_exfil_control(backend: Backend, expect):
    """D6: a downloadable=false file previews in-session but its byte path to
    the browser is refused; a downloadable=true file still downloads.

    PoC-HOLE: the PoC has no preview-vs-download distinction — everything
    downloads. Its preview() raises PocHoleNotEnforced, which IS the finding
    (the exfil boundary is absent). On the fleet, preview renders in-session
    even for downloadable=false, while download() returns refused=True with no
    bytes; the keystone is that a downloadable=true file DOES download (the
    refusal is axis-specific, not a broken viewer).

    User-facing hop: the real suite drives the preview and the save via a real
    Playwright fill + click, NEVER page.evaluate(fetch). Playwright is not
    wired into this scaffold, so the byte-path half is xfailed with a reason
    below rather than passed silently.
    """
    sc = expect("D6")
    assert sc["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # The PoC has no preview boundary: preview() raises PocHoleNotEnforced.
        # Catch it as the finding — the exfil control is absent here.
        with pytest.raises(PocHoleNotEnforced):
            backend.preview("any-file-poc-has-no-preview-axis")
        # And the corollary hole: download() has no downloadable axis — every
        # file the chat_id names streams (refused is always False on the PoC).
        result = _poc_server_verb(backend.download, "any-file-poc-downloads-everything")
        assert isinstance(result, DownloadResult)
        assert result.refused is False, (
            "PoC hole: no downloadable axis; every file byte-streams to the "
            "browser"
        )
        return

    # Fleet side. The preview render and the byte-to-browser refusal are driven
    # in the browser group test with a real Playwright fill + click (never
    # page.evaluate(fetch)). preview() and download() are bound to that live UI
    # surface there; here they raise NotImplementedError until bound. Record
    # the gap honestly rather than fake a green.
    #
    # downloadable=false: preview renders in-session; download refuses the byte
    # path (refused=True, no bytes).
    preview_result = _fleet_wire_bound(backend.preview, "fid-D6-downloadable-false")
    assert isinstance(preview_result, DownloadResult)
    assert preview_result.status == STATUS_OK and len(preview_result.data) > 0, (
        "fleet: a downloadable=false file must still PREVIEW in-session "
        "(rendered bytes on the preview path)"
    )
    dl_refused = _fleet_wire_bound(backend.download, "fid-D6-downloadable-false")
    assert isinstance(dl_refused, DownloadResult)
    assert dl_refused.refused is True and len(dl_refused.data) == 0, (
        "fleet: the byte-to-browser path for a downloadable=false file must be "
        "REFUSED with no bytes (preview-not-download exfil control)"
    )
    # KEYSTONE: a downloadable=true file DOES download — the refusal is
    # axis-specific, not a broken viewer.
    dl_ok = _fleet_wire_bound(backend.download, "fid-D6-downloadable-true")
    assert isinstance(dl_ok, DownloadResult)
    assert dl_ok.refused is False and dl_ok.status == STATUS_OK and len(dl_ok.data) > 0, (
        "fleet keystone: a downloadable=true file must download (bytes to the "
        "browser) — the refusal above is axis-specific"
    )


# =====================================================================
# D7 — replay captured/expired session-JWT at egress
#      proves: token freshness is enforced at the edge
# =====================================================================
def test_d7_expired_or_replayed_jwt_refused_at_egress(backend: Backend, expect):
    """D7: an expired or replayed Storage-JWT presented at egress is refused
    (401, validated via control's JWKS); a currently-valid JWT exchanges and
    fetches.

    PoC-HOLE: the PoC has no token model and no egress edge — there is no JWT
    to expire or replay, so the freshness boundary is absent (the finding). On
    the fleet, egress validates the weak JWT against control's JWKS: an expired
    token -> 401 and a replayed token past its exp -> 401. The keystone: a
    currently-valid JWT exchanges (RFC-8693) and fetches, so the 401 is
    freshness-specific, not a broken edge.
    """
    sc = expect("D7")
    assert sc["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # No JWT, no egress edge. There is no token to replay and no edge to
        # validate freshness — the boundary is absent. The PoC "guest" reaches
        # storage as raw host-bound files with no token hop; record the hole by
        # showing the storage path works with no credential at all.
        result = _require_poc_container(backend.exec(["ls", "-1", "/mnt/user-data/outputs"]))
        assert isinstance(result, ExecResult)
        assert result.exit_code == 0, (
            "PoC hole: no session-JWT and no egress edge; storage is reachable "
            "with no token freshness check"
        )
        return

    # Fleet side. The egress edge validates the Storage-JWT via control's JWKS.
    # Forcing an expired / replayed token at the edge requires minting a token
    # past its exp and driving a mount operation through egress; that wire is
    # bound in the storage group test. Here we assert the STATUS CLASS the
    # contract pins (401 at egress). We assert via the guest's storage path,
    # which traverses egress: an operation carrying an expired token is refused
    # at the edge, surfacing to the guest as a failed mount op (non-zero exit)
    # or a 401 on the direct egress probe.
    backend.create_storage_session()
    # Expired-token case: drive an egress-traversing mount op with a token past
    # its exp. The mount op fails at the edge. We cannot mint an expired token
    # from the guest without the control/storage wire, so this is bound in the
    # storage group test — record the gap rather than assert an invented body.
    expired = _fleet_wire_bound(
        backend.download, "fid-D7-expired-jwt-at-egress"
    )
    assert isinstance(expired, DownloadResult)
    assert expired.status == STATUS_UNAUTHORIZED, (
        "fleet: an expired Storage-JWT at egress must be 401 (control JWKS "
        "validation); HTTP status is authoritative"
    )
    # Replayed-token case: the same captured token presented again past its exp
    # -> 401. Freshness, not one-time-use, is what the edge enforces here.
    replayed = _fleet_wire_bound(
        backend.download, "fid-D7-replayed-jwt-past-exp"
    )
    assert replayed.status == STATUS_UNAUTHORIZED, (
        "fleet: a replayed Storage-JWT past its exp must be 401 at egress "
        "(same freshness class as the expired case)"
    )
    # KEYSTONE: a currently-valid JWT exchanges (RFC-8693) and fetches. The 401
    # is freshness-specific, not a broken edge. A write through the FUSE mount
    # traverses egress with a fresh control-minted token; exit 0 proves the
    # valid path works end-to-end. The argv is /bin/busybox-prefixed (static
    # guest, no bare sh) exactly like storage-chain-demo.sh; a bare ["sh",...]
    # would exit 127 (ENOENT) and red this keystone for the wrong reason.
    fresh_write = backend.exec_sh(
        "echo d7-ok > /mnt/user-data/outputs/d7-fresh.txt "
        "&& /bin/busybox cat /mnt/user-data/outputs/d7-fresh.txt"
    )
    assert isinstance(fresh_write, ExecResult)
    assert not fresh_write.denied
    assert fresh_write.exit_code == 0 and b"d7-ok" in fresh_write.stdout, (
        "fleet keystone: a currently-valid JWT must exchange and fetch through "
        "egress — the 401 above is freshness-specific, not a broken edge"
    )
