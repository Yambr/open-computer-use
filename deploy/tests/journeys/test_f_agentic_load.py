# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""GROUP F — Agentic-load: concurrency, parallel exec, large-file streaming,
pagination, and churn against the PoC and the fleet.

One paired test per scenario F1..F5. Each drives the real journey verbs on the
running backend (never a mock) and asserts the observable end state the
scenario names, plus its keystone (the negative / inversion) so the green is
reproducibly reddable.

Honesty rules this file obeys (see conftest.py / README.md):
  * A down stack skips loudly (the ``backend`` fixture); it is never a green.
  * A boundary the PoC lacks raises PocHoleNotEnforced; the paired test reads
    that as the finding (F1 cap, F5 release/reconcile have no PoC analogue).
  * A fleet verb the scaffold has not yet bound to its live wire raises
    NotImplementedError (upload / list_files / download / preview). A leg that
    needs such a verb is marked with ``inactive_mechanism`` (an xfail with a
    reason — a RECORDED gap), never swallowed into a pass.
  * Where a contract value is not frozen (the tier cap size, the stream
    ceiling, cursor pagination shape, the release/reconcile slot count), the
    test asserts the ENVELOPE / STATUS class, not an invented body, and says so
    in a comment.
  * A load probe is sized to actually stress the chain; a neuter payload that
    any single buffer absorbs passing green is vacuous (F3).

The file-level user hops in this group (concurrent isolation reads, large-file
byte path, paginated listing) are wire / exec journeys, not browser journeys,
so Playwright is not required here; the browser-driven download/preview hops
live in the B/D group bodies and use a real fill + click, never
page.evaluate(fetch).
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import os
import time
import uuid
from typing import Any, Callable

import pytest

from backends.base import (
    Backend,
    BackendUnavailable,
    FileRef,
    PocHoleNotEnforced,
    SURFACE_OUTPUTS,
    SURFACE_UPLOADS,
)
from conftest import await_fleet_exec_ready, inactive_mechanism

Expect = Callable[[str], dict]

# Concurrency knobs. K is the number of concurrent sessions F1 opens; it is a
# probe count, NOT an assertion of the tier cap (the cap size is a deployment
# value, not frozen in a wire contract). F1 asserts the SHAPE of the outcome
# under load, not a specific cap number. Override for a deployment whose cap is
# known, to push exactly one create past the ceiling.
F_CONCURRENCY = int(os.getenv("F_CONCURRENCY", "6"))
# P parallel exec calls in one session (F2). Each carries a distinct marker so a
# cross-talk / interleave shows up as a 1:1 mismatch.
F_PARALLEL_EXEC = int(os.getenv("F_PARALLEL_EXEC", "5"))
# Churn cycles for F5.
F_CHURN_CYCLES = int(os.getenv("F_CHURN_CYCLES", "8"))
# F3 large-file size. Sized ABOVE a single-buffer absorb so the whole chain
# (host WS / UDS / guest WS / child pipe on the fleet; single stream on the
# PoC) is exercised. 24 MiB clears the 8 MiB stream ceiling proven in the wire
# tests; a 2 MiB neuter payload would be absorbed by one buffer and pass
# vacuously. Override only upward.
F_LARGE_BYTES = int(os.getenv("F_LARGE_BYTES", str(24 * 1024 * 1024)))


def _admitted(status: str) -> bool:
    """True iff a SessionRef.status reports an admitted (active) session.

    Fleet create returns status "active" on 200/201 and "denied:{http}" on an
    admission refusal (see FleetBackend.create_session). PoC create is always
    "active" (unbounded — no admission gate). Keying on the reported state, not
    a hardcoded timeout, is the conftest honesty rule.
    """
    return status == "active"


def _denied_http(status: str) -> int:
    """Extract the HTTP class from a "denied:{http}" status string, else -1."""
    if status.startswith("denied:"):
        tail = status.split(":", 1)[1]
        return int(tail) if tail.isdigit() else -1
    return -1


def _foreign_backend(backend: Backend, primary_scope: str) -> Backend:
    """A second backend instance keyed on a scope distinct from ``primary_scope``.

    The PoC scopes on chat_id, so a plain ``type(backend)()`` reuses the SAME
    default chat_id and the cross-scope keystone would compare a scope to
    itself (vacuous). Build the PoC foreign backend on a distinct chat_id. Other
    backends scope on the session/fs, not on a constructor chat_id, so a bare
    instance is already a distinct scope for their keystone.
    """
    if backend.name == "poc":
        return type(backend)(chat_id=f"{primary_scope}-foreign")
    return type(backend)()


def _poc_list_uploads(backend: Backend, scope: str) -> list[FileRef]:
    """List the PoC uploads/ surface (GET /api/uploads/{chat}/list).

    F4 uploads onto SURFACE_UPLOADS (uploads/), but the scaffold
    ``list_files`` reads outputs/ (GET /api/outputs) — a different dir. This
    lists the SAME surface the files landed on so the no-gaps keystone observes
    the real set. Reuses the backend's own real HTTP path (its private ``_get``)
    and parses the identical ``{"files":[{"name","path","size"}]}`` shape
    list_files uses — a real server response, never a fabricated list.
    """
    resp = backend._get(f"/api/uploads/{scope}/list")
    resp.raise_for_status()
    payload = resp.json()
    return [
        FileRef(
            id=f.get("path", f.get("name", "")),
            name=f.get("name", f.get("path", "")),
            scope=scope,
            size=int(f.get("size", 0)),
        )
        for f in payload.get("files", [])
    ]


# =====================================================================
# F1 — run many sessions concurrently
#   proves: isolation + quota hold under concurrency
#   PoC:   containers created freely (noisy-neighbor) — the hole
#   Fleet: up-to-cap concurrent sessions isolated; cap enforced under race
#   KEYSTONE: K=cap all succeed & each sees only its own files; K+1 concurrent,
#             exactly the overflow gets 409 (no double-admit); i cannot read j.
# =====================================================================
def test_f1_concurrent_sessions_quota_and_isolation(backend: Backend, expect: Expect) -> None:
    """F1 — isolation + quota hold under concurrency.

    Drives K concurrent real create_session calls and asserts the per-backend
    admission SHAPE, then the cross-session isolation keystone. The tier cap
    size is a deployment value (not a frozen wire contract), so this asserts the
    ENVELOPE — that the fleet either admits within a cap or denies overflow with
    409 and never double-admits — rather than a specific cap number.
    """
    sc = expect("F1")
    assert sc["bucket"] == "HARDENED"

    def _one_create(_i: int):
        # A fresh backend instance per thread: each carries its own last-key so
        # concurrent creates do not stomp a shared _last_hint. This is the real
        # create wire (curl mTLS on the fleet, docker/chat scope on the PoC).
        impl = type(backend)()
        return impl.create_session()

    with concurrent.futures.ThreadPoolExecutor(max_workers=F_CONCURRENCY) as pool:
        refs = list(pool.map(_one_create, range(F_CONCURRENCY)))

    admitted = [r for r in refs if _admitted(r.status)]
    denied = [r for r in refs if not _admitted(r.status)]

    if backend.name == "poc":
        # PoC-HOLE side: docker run is unbounded, there is no admission gate, so
        # every concurrent create is admitted. That absence of a cap IS the
        # finding this scenario records against the PoC.
        assert not denied, (
            "PoC has no concurrency cap — every create is expected to be "
            f"admitted (the noisy-neighbor hole); got denials {denied}"
        )
        assert len(admitted) == F_CONCURRENCY
        # The cap keystone (overflow -> 409) has no PoC analogue. Record it.
        assert "409" not in [str(_denied_http(r.status)) for r in refs]
        return

    # Fleet side. Two admitted regimes are both correct depending on where
    # F_CONCURRENCY sits relative to the deployment cap; assert the ENVELOPE:
    #   (a) all admitted  -> K <= cap; no false denial.
    #   (b) some denied    -> the denials MUST be 409 (tier cap), never a 5xx
    #                         crash, and the admitted set + overflow account for
    #                         every request (no request lost, no double-admit).
    for r in denied:
        code = _denied_http(r.status)
        assert code == 409, (
            f"fleet overflow must deny with 409 at the tier cap, got {r.status}"
        )
    # No double-admit: every request resolved to exactly one outcome, and the
    # admitted keys are unique (no key handed to two concurrent creates).
    assert len(admitted) + len(denied) == F_CONCURRENCY
    admitted_keys = [r.key for r in admitted if r.key]
    assert len(admitted_keys) == len(set(admitted_keys)), (
        "double-admit: a session key was issued to more than one concurrent create"
    )

    # KEYSTONE (cross-session isolation): session i must not read session j's
    # outputs under load. The read leg needs the F9 list_files wire, which the
    # scaffold binds in the storage group (raises NotImplementedError here).
    # Rather than fake a green, mark the isolation-read leg as a recorded gap;
    # the admission-envelope above is the live-verified half of F1.
    if len(admitted) >= 2:
        a, b = admitted[0], admitted[1]
        try:
            files_of_b = backend.list_files(b.key)
        except NotImplementedError:
            inactive_mechanism(
                "F1 cross-scope isolation read needs the live F9 /v1/files wire "
                "(bound in the storage group); admission-cap envelope is verified"
            )
        except BackendUnavailable as exc:  # pragma: no cover - env-dependent
            pytest.skip(f"F9 read plane unreachable for F1 isolation leg: {exc}")
        else:
            # If the wire IS bound, the keystone is concrete: scope b's listing
            # must not surface any file id minted under scope a.
            files_of_a = backend.list_files(a.key)
            a_ids = {f.id for f in files_of_a}
            assert all(f.id not in a_ids for f in files_of_b), (
                "isolation breach: session j's listing surfaced session i's file id"
            )


# =====================================================================
# F2 — fan out sub-agents / parallel exec in one session
#   proves: parallel work is stable
#   Fleet: concurrent exec calls carry correct exec-identity (RuntimeID:cname)
#   KEYSTONE: P parallel exec calls each return their OWN correct output
#             (distinct markers, 1:1, not interleaved/misrouted).
# =====================================================================
def test_f2_parallel_exec_no_cross_talk(backend: Backend, expect: Expect) -> None:
    """F2 — parallel work is stable; concurrent execs are 1:1, not misrouted.

    Creates one session, fires P concurrent exec calls each echoing a UNIQUE
    marker, and asserts a bijection: every marker sent comes back exactly once
    on the exec that requested it. An interleave or a mis-route (output of exec
    i surfacing on exec j) breaks the 1:1 and reddens this — the keystone.
    """
    sc = expect("F2")
    assert sc["bucket"] == "HARDENED"

    session = backend.create_session()
    if not _admitted(session.status):
        pytest.skip(
            f"F2 could not obtain a session to fan out into: {session.status}"
        )

    # Readiness gate: a create returns as soon as the ROW is reserved, but the
    # guest boot-child (the exec listener) takes ~2-3s to come up. An exec fired
    # before then is refused (control has no exec target yet), which would make
    # every parallel marker come back empty — a false cross-talk red. Poll a
    # trivial exec until the guest answers, so the 1:1 keystone below observes a
    # real fan-out, not a boot race. Fleet-only; the PoC container is exec-ready
    # at create.
    await_fleet_exec_ready(backend)

    # The cross-talk invariant this scenario names (exec i's output surfacing on
    # exec j) is a fleet exec-identity property (RuntimeID:cname mis-route, #93).
    # On the PoC every _echo is an independent `docker exec` with its own stdout
    # pipe keyed on self._chat_id, so two execs' outputs physically cannot
    # interleave — the cross-talk keystone below has no reddable path on the PoC.
    # Mark the PoC leg as not exercising the mis-route invariant so its green is
    # not misread as a live cross-talk check; the reddable target runs on the
    # fleet only (loud-skipped on Darwin where runsc is absent).
    if backend.name == "poc":
        inactive_mechanism(
            "F2 cross-talk/mis-route keystone is a fleet exec-identity property "
            "(RuntimeID:cname); on the PoC each exec is an independent docker "
            "exec with its own stdout pipe, so interleave cannot occur and the "
            "keystone cannot RED — it runs live on the fleet only"
        )

    markers = [f"F2-{uuid.uuid4().hex}" for _ in range(F_PARALLEL_EXEC)]

    def _echo(marker: str):
        # A fresh backend bound to the SAME session key so every thread targets
        # one session (the "one session, many parallel execs" story). Each
        # thread runs the real exec wire; the marker is the correlation id.
        impl = type(backend)()
        impl._last_hint = getattr(backend, "_last_hint", None)  # fleet addressing
        impl._last_key = getattr(backend, "_last_key", None)
        try:
            # Route through exec_sh (the chokepoint): the fleet guest has no
            # /bin/echo on PATH and control refuses a bare non-absolute argv[0]
            # (409), so exec_sh applies the /bin/busybox sh -c prefix and `echo`
            # runs as a shell builtin. The marker is a hex uuid (no shell-meta),
            # so the single-token echo carries it back intact. The PoC's Ubuntu
            # userland runs the same script under /bin/sh -c. Using exec_sh keeps
            # the argv off the test surface the meta-guard forbids inline.
            res = impl.exec_sh(f"echo {marker}")
        except BackendUnavailable as exc:
            return marker, None, str(exc)
        return marker, res, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=F_PARALLEL_EXEC) as pool:
        results = list(pool.map(_echo, markers))

    unreachable = [m for (m, res, err) in results if res is None]
    if unreachable:
        pytest.skip(
            f"F2 exec plane unreachable for {len(unreachable)}/{len(markers)} calls"
        )

    # KEYSTONE 1:1 — each exec returns its OWN marker and no other's. Build the
    # observed mapping and assert it is the identity on the sent markers.
    for marker, res, _err in results:
        out = res.stdout.decode("utf-8", "replace")
        assert marker in out, (
            f"exec for {marker} did not return its own output (got {out!r})"
        )
        # No cross-talk: this exec must not carry ANOTHER call's marker.
        others = [m for m in markers if m != marker]
        leaked = [m for m in others if m in out]
        assert not leaked, (
            f"cross-talk: exec for {marker} also returned {leaked} — outputs "
            "were interleaved / misrouted"
        )

    # Separate observation (not implied by keystone-1): surjection onto the
    # sent set. keystone-1 asserts each exec carried ITS OWN marker; it cannot
    # see a marker delivered on the WRONG exec while its own also arrived, nor a
    # session that echoed some markers twice and dropped others. Scan every
    # output for every sent marker and require each marker to appear exactly
    # once across the whole run — a duplicate-delivery or a drop reddens this.
    delivery_count = {m: 0 for m in markers}
    for _m, res, _e in results:
        out = res.stdout.decode("utf-8", "replace")
        for m in markers:
            if m in out:
                delivery_count[m] += 1
    misdelivered = {m: c for m, c in delivery_count.items() if c != 1}
    assert not misdelivered, (
        "parallel exec is not 1:1: markers delivered a number of times other "
        f"than once (marker -> count) {misdelivered}"
    )


# =====================================================================
# F3 — push a large file through the storage chain
#   proves: streaming / backpressure without truncation
#   PoC:   single stream
#   Fleet: chunked up+down, hash-stable
#   KEYSTONE: pick a size that stresses the whole buffer chain (above the stream
#             ceiling, not a neuter payload); round-trip is bidirectional and
#             hash-matches (a neuter payload passing is vacuous).
# =====================================================================
def test_f3_large_file_roundtrip_hash_stable(backend: Backend, expect: Expect) -> None:
    """F3 — a large file round-trips through the storage chain without truncation.

    Uploads a payload sized ABOVE the single-buffer absorb (F_LARGE_BYTES,
    default 24 MiB > the 8 MiB stream ceiling) and asserts the downloaded bytes
    hash-match the source — the bidirectional, non-vacuous check. A neuter
    payload that one buffer absorbs would pass without exercising backpressure,
    so the size is the keystone here.
    """
    sc = expect("F3")
    assert sc["bucket"] == "HARDENED"

    # Random incompressible payload so a truncation or a chunk-drop changes the
    # hash. Sized to stress the chain, not to fit one buffer.
    payload = os.urandom(F_LARGE_BYTES)
    src_hash = hashlib.sha256(payload).hexdigest()
    name = f"f3-large-{uuid.uuid4().hex}.bin"

    # The upload -> download byte round-trip needs the storage plane. On the
    # PoC this is the real /api/uploads + /files wire. On the fleet the chunked
    # F9 / mount-plane upload and the UI byte path are bound by the storage /
    # browser group tests (raise NotImplementedError in this scaffold), so the
    # fleet leg is a recorded gap, not a faked green.
    try:
        stored = backend.upload(SURFACE_UPLOADS, name, payload)
    except NotImplementedError:
        inactive_mechanism(
            "F3 fleet large-file leg needs the live chunked F9 / mount-plane "
            "upload wire (bound in the storage group); the size probe and "
            "hash-stability assertion are ready to run once it is wired"
        )
    except PocHoleNotEnforced as exc:  # uploads upload should not hit this
        pytest.fail(f"unexpected PoC-HOLE on uploads upload: {exc}")
    except BackendUnavailable as exc:  # pragma: no cover - env-dependent
        pytest.skip(f"F3 storage plane unreachable on upload: {exc}")

    assert stored.size == F_LARGE_BYTES, (
        "upload reported a truncated size before the round-trip even began"
    )

    # The PoC upload lands in the :ro uploads/ surface, but download() reads the
    # outputs/ surface (GET /files/{chat}/{file} streams outputs on disk; nothing
    # copies uploads -> outputs). To round-trip the SAME bytes through a surface
    # download() can read, exec a copy of the stored file from the in-container
    # uploads mount into the outputs mount (the same end state the agent
    # produces when it writes a report). The busybox `cp` moves all 24 MiB
    # through the container FS, so a truncation there also reddens the hash
    # check below. The download id is then the outputs-side filename.
    download_id = stored.id
    if backend.name == "poc":
        copy = backend.exec(
            [
                "cp",
                f"/mnt/user-data/uploads/{name}",
                f"/mnt/user-data/outputs/{name}",
            ]
        )
        assert copy.exit_code == 0, (
            "F3 PoC round-trip could not stage the payload into the outputs "
            f"surface (cp exit {copy.exit_code}, stderr {copy.stderr!r})"
        )
        download_id = name

    got = backend.download(download_id)
    # Envelope first: the byte path must complete (200) and not refuse. A
    # partial-bytes guess is banned — assert the status class, then the hash.
    assert got.status == 200 and not got.refused, (
        f"F3 large-file download did not deliver bytes: status={got.status} "
        f"refused={got.refused}"
    )
    dst_hash = hashlib.sha256(got.data).hexdigest()
    # KEYSTONE: bidirectional hash-match on a size that stresses the chain.
    assert len(got.data) == F_LARGE_BYTES, (
        f"silent truncation: sent {F_LARGE_BYTES} bytes, got back {len(got.data)}"
    )
    assert dst_hash == src_hash, (
        "large-file round-trip corrupted the payload (hash mismatch) — the "
        "chain truncated or dropped a chunk under backpressure"
    )


# =====================================================================
# F4 — list a directory with hundreds of files
#   proves: pagination does not leak or OOM
#   Fleet: F9 cursor pagination; page N+1 continues with no dupes/gaps
#   KEYSTONE: no file twice or missing across pages; a foreign-scope file never
#             appears on any page.
# =====================================================================
def test_f4_pagination_no_dupes_gaps_or_cross_scope(backend: Backend, expect: Expect) -> None:
    """F4 — paginated listing reassembles the exact set with no dupes/gaps/leak.

    Populates a directory with hundreds of files, lists the full set (cursor-
    paginated on the fleet), and asserts the reassembled ids equal the exact
    expected set — no id twice, none missing — and that a file belonging to a
    DIFFERENT scope never appears on any page. The list wire is the F9 read
    plane; where the scaffold has not yet bound it the leg is a recorded gap.
    """
    sc = expect("F4")
    assert sc["bucket"] == "HARDENED"

    # A count large enough to force more than one page on a cursor-paginated
    # plane (hundreds, per the story) and to catch an OOM-on-full-listing shape.
    n_files = int(os.getenv("F4_FILE_COUNT", "250"))

    # Populate the listing surface with N named files, plus ONE file under a
    # foreign scope that must never surface on this scope's pages. Uploads use
    # the real upload verb; on the fleet the mount-plane upload is bound by the
    # storage group (NotImplementedError here) so the whole populate+list leg is
    # a recorded gap rather than a faked green.
    scope = None
    foreign_scope = None
    try:
        expected_names = set()
        for i in range(n_files):
            fname = f"f4-{i:04d}-{uuid.uuid4().hex[:8]}.txt"
            ref = backend.upload(SURFACE_UPLOADS, fname, f"f4-body-{i}".encode())
            scope = ref.scope
            expected_names.add(ref.name)
        # A foreign-scope file: a second backend instance keyed on a GENUINELY
        # different scope writes one file that must be absent from THIS scope's
        # every page. type(backend)() with no args reuses the SAME default
        # chat_id, so it would test scope == scope (vacuous); derive a distinct
        # scope. The PoC backend keys on chat_id (pass a distinct suffix); other
        # backends scope on the session/fs and need no chat_id override.
        foreign = _foreign_backend(backend, scope)
        foreign_scope = getattr(foreign, "_chat_id", None)
        assert foreign_scope != scope, (
            "F4 foreign backend did not get a distinct scope; the cross-scope "
            "keystone would be vacuous (scope == scope)"
        )
        foreign_name = f"f4-foreign-{uuid.uuid4().hex[:8]}.txt"
        foreign_ref = foreign.upload(SURFACE_UPLOADS, foreign_name, b"foreign-body")
    except NotImplementedError:
        inactive_mechanism(
            "F4 fleet leg needs the live F9 /v1/files cursor wire + mount-plane "
            "upload (bound in the storage group); the reassemble/dupe/gap/"
            "foreign-scope keystone is ready to run once they are wired"
        )
    except PocHoleNotEnforced as exc:
        pytest.fail(f"unexpected PoC-HOLE on inputs upload: {exc}")
    except BackendUnavailable as exc:  # pragma: no cover - env-dependent
        pytest.skip(f"F4 storage plane unreachable while populating: {exc}")

    # List the SAME surface the files were uploaded to. The files landed on
    # uploads/ (the SURFACE_UPLOADS write above); list_files(scope) on the PoC
    # reads outputs/ (GET /api/outputs) — a DIFFERENT dir, so listing it would
    # find none of the uploaded names and the no-gaps keystone would red for the
    # wrong reason. List uploads/ on the PoC (GET /api/uploads/{chat}/list); on
    # the fleet the F9 cursor plane reassembles the pages internally. Either way
    # the OBSERVABLE end state is the reassembled id set the keystone checks.
    if backend.name == "poc":
        listed = _poc_list_uploads(backend, scope)
    else:
        listed = backend.list_files(scope)
    listed_names = [f.name for f in listed]

    # KEYSTONE 1 — no dupes: every listed name is unique.
    assert len(listed_names) == len(set(listed_names)), (
        "pagination duplicated a file across pages"
    )
    # KEYSTONE 2 — no gaps: every uploaded file is present exactly once.
    listed_set = set(listed_names)
    missing = expected_names - listed_set
    assert not missing, f"pagination dropped files across pages: {sorted(missing)[:5]}"
    # KEYSTONE 3 — no cross-scope leak: the foreign-scope file is on NO page.
    assert foreign_name not in listed_set, (
        f"cross-scope leak: a file from scope {foreign_scope!r} surfaced in "
        f"scope {scope!r}'s paginated listing"
    )


# =====================================================================
# F5 — churn create -> exec -> release rapidly
#   proves: slots do not leak under churn
#   PoC:   no analogue (no quota, no release/reconcile)
#   Fleet: steady-state slot count returns to baseline (reconcile under load)
#   KEYSTONE: killing a guest mid-churn still returns its slot on reconcile.
# =====================================================================
def test_f5_churn_slots_return_to_baseline(backend: Backend, expect: Expect) -> None:
    """F5 — rapid create/exec/release churn leaves the slot count at baseline.

    Runs M create->exec cycles back to back and asserts the steady-state
    admission capacity returns to baseline — a fresh create AFTER the churn must
    still be admitted, proving no slot leaked (the live-counter invariant, #93
    reconcile). The mid-churn-kill keystone drives reconcile: a guest removed
    out from under its row must still have its slot reclaimed.
    """
    sc = expect("F5")
    assert sc["bucket"] == "HARDENED"

    if backend.name == "poc":
        # PoC-HOLE side: there is no quota and no release/reconcile, so "slots
        # return to baseline" has no analogue. Churn still runs (unbounded
        # docker), but the release verb the scenario names is absent. The
        # scaffold has no release() verb; the PoC's missing lifecycle is the
        # finding. Assert the absence explicitly rather than fake a slot count.
        first = backend.create_session()
        assert _admitted(first.status), "PoC create is unbounded and should admit"
        # No operator/release lifecycle to drive: revoke_all is the nearest
        # lifecycle boundary and it is a PoC-HOLE.
        with pytest.raises(PocHoleNotEnforced):
            backend.revoke_all()
        return

    # Fleet side. Establish that a create is admitted at baseline.
    baseline = backend.create_session()
    if not _admitted(baseline.status):
        pytest.skip(f"F5 baseline create not admitted: {baseline.status}")

    # Churn: M rapid create->exec cycles. The scaffold Backend Protocol has no
    # explicit release() verb (release is control-side lifecycle: idle reap /
    # operator / reconcile), so this drives the CREATE+EXEC half live and relies
    # on control's reconcile to reclaim slots. Each cycle uses a fresh backend
    # so keys do not collide.
    for _cycle in range(F_CHURN_CYCLES):
        impl = type(backend)()
        ref = impl.create_session()
        if not _admitted(ref.status):
            # Under a tight cap the churn may transiently hit 409; that is a
            # correct envelope, not a leak. Break and let reconcile settle.
            assert _denied_http(ref.status) == 409, (
                f"churn create denied with a non-409 status: {ref.status}"
            )
            break
        # One real exec so the cycle does work before the slot is reclaimed.
        try:
            impl.exec(["true"])
        except BackendUnavailable:
            pass

    # KEYSTONE / steady-state: after the churn a fresh create must STILL be
    # admitted — the slot count returned to baseline (no permanent wall). The
    # exact baseline integer is a deployment value (tier cap), so this asserts
    # the ENVELOPE: capacity is available again, not a specific counter number.
    # Reconcile is not instantaneous; poll the create verb for a short window
    # rather than assert on a hardcoded timeout (the conftest state-not-timeout
    # rule).
    deadline = time.time() + float(os.getenv("F5_RECONCILE_WINDOW_S", "30"))
    post = backend.create_session()
    while not _admitted(post.status) and time.time() < deadline:
        # Only a 409 (cap) is a legitimate transient; any other status is a real
        # failure and should not be retried away.
        if _denied_http(post.status) != 409:
            break
        time.sleep(1.0)
        post = backend.create_session()
    assert _admitted(post.status), (
        "slot leak under churn: a fresh create is still denied after the "
        f"reconcile window (last status {post.status}) — capacity did not "
        "return to baseline"
    )

    # KEYSTONE (mid-churn kill -> slot reclaimed): removing a guest out from
    # under its row must still return the slot on reconcile (#93). Driving the
    # kill needs the container-remove + control-restart path the lifecycle group
    # owns (E5); the scaffold Backend exposes no guest-kill verb, so record the
    # reclaim-under-kill leg as a gap rather than assert a fabricated reclaim.
    inactive_mechanism(
        "F5 mid-churn-kill reclaim keystone drives the guest-remove + reconcile "
        "path owned by the lifecycle group (E5); the steady-state-baseline half "
        "is verified live above"
    )
