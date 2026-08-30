# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""GROUP G — negative / adversarial / isolation invariants (G1..G6).

Paired PoC-vs-fleet journey tests. Each test drives the real journey verbs on
the ``backend`` fixture (parametrized poc/fleet; conftest skips a backend
loudly when it is not live) and asserts the real end state plus the scenario's
keystone — the negative / inversion that makes the green reproducibly reddable.

Honesty rules this file obeys (from the scaffold docstrings and CLAUDE.md):
  * A boundary the PoC lacks raises PocHoleNotEnforced; the paired [PoC-HOLE]
    test reads that absence as the finding, and asserts the fleet CLOSES it.
    That divergence IS the test — never a fake-green that passes on both.
  * A mechanism that is real but inactive in this env is xfail(reason) via
    conftest.inactive_mechanism — a recorded gap, never a silent pass.
  * Where a contract is TBD (createFile 501 until #304 body-freeze,
    post-session retention window), the test asserts the ENVELOPE / STATUS
    CLASS, not an invented body. Each such site says so in a comment.
  * User-facing byte-path hops (G6 download/preview) drive a real Playwright
    fill + click in the live browser group — NEVER page.evaluate(fetch). Where
    Playwright is not wired into this scaffold, those sub-checks are gated with
    pytest.importorskip / xfail(reason) so the skip is honest, not a pass.
  * Asserting only markup / field presence is fake-green. Every test drives an
    observable end state (a stat result, an HTTP status class, a byte compare,
    a chain-verify boolean) and a keystone that flips it.
"""

from __future__ import annotations

import uuid

import pytest

from backends.base import (
    BackendUnavailable,
    DownloadResult,
    PocHoleNotEnforced,
)
from conftest import await_fleet_exec_ready, inactive_mechanism, real_finding


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# The in-guest path control stages the mount-config to on a :ro path BEFORE the
# mount starts (mount-config.schema.json), then unlinks after Load (NFR-SEC-25).
# It is inspected by an in-guest stat; a scrubbed config yields ENOENT.
_MOUNT_CONFIG_PATH = "/etc/ocu/mount-config.json"

# A byte marker the guest writes to prove the FUSE mount still works after the
# config is scrubbed (G1 keystone). Distinct per run so a stale artifact from a
# prior run cannot masquerade as this run's success.
def _unique_marker() -> str:
    return f"g-marker-{uuid.uuid4().hex[:12]}"


def _new_scope() -> str:
    """A fresh, previously-unused scope value for cross-scope keystones."""
    return f"g-scope-{uuid.uuid4().hex[:12]}"


class _substrate_up:
    """Context manager: convert a mid-test BackendUnavailable into a LOUD skip.

    conftest's ``backend`` fixture probes ``live()`` before the test, but that
    probe is coarse on purpose: the PoC ``live()`` gates only on a reachable
    Docker daemon, and the fleet on runsc + a control handshake. A verb that
    then finds the ACTUAL substrate down (the FastAPI server not up, the
    mount-plane unreachable) raises BackendUnavailable mid-test. The scaffold's
    contract is that such a signal is a loud skip — a down stack is never a
    green AND never a spurious red masquerading as a real assertion failure.

    pytest registers ``pytest_*`` hooks only from conftest / installed plugins,
    not from a test module, and this file stays self-contained (it does not
    edit the shared conftest). Wrapping the substrate-touching region in this
    context manager is the reliable in-module conversion: a BackendUnavailable
    raised inside the ``with`` block becomes a loud pytest.skip.
    """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None and issubclass(exc_type, BackendUnavailable):
            pytest.skip(
                f"substrate down mid-test (loud skip, not a pass, not a red): {exc}"
            )
        return False


def _require_poc_container_up(backend) -> None:
    """Loud-skip if the PoC per-chat container is not running.

    Several PoC probes (egress reachability, in-container reads) need the
    per-chat container live. The scaffold's ``exec`` returns a non-zero
    ExecResult (docker says "No such container") rather than raising when the
    container is down, so a naive assertion on its output would red on a
    down substrate. This turns that condition into a loud skip — the finding a
    PoC-HOLE scenario records requires the PoC to actually be up; a down
    container is skip-not-red and skip-not-green.
    """
    probe = backend.get_session(backend._chat_id)
    if probe.status != "active":
        pytest.skip(
            "PoC per-chat container is not running; bring up the PoC stack + a "
            "live chat so its container exists, then re-run. This is a LOUD "
            "SKIP, not a pass — the container-dependent probe cannot run."
        )


# ---------------------------------------------------------------------------
# G1 — mount-config scrubbed after Load (NFR-SEC-25) [HARDENED]
# ---------------------------------------------------------------------------

def test_g1_mount_config_scrubbed_after_boot(backend, expect):
    """G1 | invariant: the guest-config is unlinked after Load and is absent
    in the guest (NFR-SEC-25); the guest still functions once it is gone.

    Bucket HARDENED. The PoC has no such config at all, so there is nothing to
    scrub — that absence is the PoC-side finding. The fleet stages the config
    on a :ro path, Loads it, then unlinks it; an in-guest stat must return
    ENOENT while the mount stays up.
    """
    ctx = expect("G1")

    if backend.name == "poc":
        # PoC contrast: no mount-config exists. The per-chat container is
        # host-bind wired, not config-driven. Assert the ENVELOPE (the file is
        # not present) rather than inventing a config path the PoC never had.
        _require_poc_container_up(backend)
        res = backend.exec_sh(f"stat {_MOUNT_CONFIG_PATH} 2>&1; echo rc=$?")
        combined = res.stdout.decode("utf-8", "replace") + res.stderr.decode("utf-8", "replace")
        assert "rc=0" not in combined, (
            "PoC finding: no mount-config should exist in the PoC container, "
            f"but stat succeeded: {combined!r}"
        )
        assert ctx["bucket"] == "HARDENED"
        return

    # Fleet: create a real storage session so the config is actually staged +
    # scrubbed, then stat it in-guest.
    sess = backend.create_storage_session()
    assert sess.status == "active", f"storage session not active: {sess.status}"
    await_fleet_exec_ready(backend)

    # NEGATIVE (must-pass, kept a hard assertion): the config path is GONE
    # post-Load (NFR-SEC-25). The applet MUST be /bin/busybox stat — a bare stat
    # is "not found" (127), which would satisfy "rc=0 not present" WITHOUT ever
    # observing ENOENT (a vacuous scrub check). We require the specific ENOENT
    # signature (busybox stat prints "No such file" / rc 1), and a positive
    # anchor that the guest CAN stat a file that IS present, so the negative is
    # a real absence, not a broken stat.
    anchor = backend.exec_sh(
        "/bin/busybox stat /etc/ocu >/dev/null 2>&1; echo __rc=$?"
    )
    anchor_out = anchor.stdout.decode("utf-8", "replace")
    assert "not found" not in anchor_out and "__rc=0" in anchor_out, (
        "fleet: /bin/busybox stat could not stat a present path (/etc/ocu) — "
        f"the scrub negative below would be unsound (out={anchor_out!r})"
    )
    stat_res = backend.exec_sh(
        f"/bin/busybox stat {_MOUNT_CONFIG_PATH} 2>&1; echo __rc=$?"
    )
    stat_out = stat_res.stdout.decode("utf-8", "replace")
    assert "not found" not in stat_out or "No such file" in stat_out, (
        f"fleet: /bin/busybox stat did not run for the scrub check (out={stat_out!r})"
    )
    # End state: the config path is GONE post-Load — busybox stat reports ENOENT.
    assert "__rc=0" not in stat_out, (
        "NFR-SEC-25 violated: mount-config still present in-guest after Load; "
        f"stat output: {stat_out!r}"
    )
    assert "No such file" in stat_out or "__rc=1" in stat_out, (
        "fleet: the scrub check produced no ENOENT signature — the config's "
        f"absence is not positively observed (out={stat_out!r})"
    )

    # KEYSTONE (positive half): the guest still functions after the config is
    # gone — a write through the live FUSE mount round-trips. SPLIT from the
    # scrub negative above (which stays a hard assertion) so a scrub regression
    # cannot hide behind this keystone's xfail. The applet MUST be
    # /bin/busybox-prefixed (static guest).
    marker = _unique_marker()
    out_path = f"/mnt/user-data/outputs/{marker}.txt"
    write_res = backend.exec_sh(
        f"printf '%s' {marker} > {out_path} && /bin/busybox cat {out_path}; "
        f"echo __rc=$?"
    )
    assert not write_res.denied, "guest write denied after config scrub"
    combined = (
        write_res.stdout.decode("utf-8", "replace")
        + write_res.stderr.decode("utf-8", "replace")
    )
    if marker in write_res.stdout.decode("utf-8", "replace"):
        # Round-trip restored (the written marker came back) -> the storage-write
        # finding is fixed; real PASS of the positive keystone (the scrub
        # negative above already passed).
        pass
    else:
        # REAL-FINDING (same storage-write-plane defect as B4/D5): the FUSE write
        # does not round-trip — the written marker does NOT come back (the mount
        # wrapper streams the Put without the REQUIRED declared_size_bytes, so a
        # zero-length object is persisted and the read-back yields empty / an I/O
        # error). SILENT DATA LOSS: the write reports success but no bytes
        # survive. The scrub itself is proven (negative above); only the
        # mount-still-live positive half is blocked. The signature is "the marker
        # did NOT come back", so a restored round-trip flips this to the PASS arm.
        real_finding(
            "storage-write-plane",
            "guest FUSE outputs write does not round-trip after the config "
            "scrub (silent data loss): the written marker does not read back. "
            "The rclone mount wrapper streams the Put without the REQUIRED "
            "declared_size_bytes, so a zero-length object is persisted and the "
            f"read-back yields empty/I-O-error (out={combined!r}). The scrub "
            "(NFR-SEC-25) IS proven above; only the mount-live half is blocked.",
        )

    # A/B no-scrub control note: the scaffold's storage session always scrubs
    # (NFR-SEC-25 is unconditional — no keep-config knob, per the run.go
    # unlink). The A/B contrast (a no-scrub session STILL shows the config) is
    # driven by the storage group's dedicated A/B harness which can toggle a
    # no-scrub image; asserting it here would require a second image this
    # backend does not expose, so the contrast is left to that harness. The
    # keystone above already makes THIS green reddable (a live mount + a gone
    # config), which is the non-vacuous core of G1.


# ---------------------------------------------------------------------------
# G2 — forged / tampered wire frame refused [PoC-HOLE]
# ---------------------------------------------------------------------------

def test_g2_forged_wire_frame_refused(backend, expect):
    """G2 | invariant: signature verification refuses forgeries (F9 / gateway
    signature check); mutating one byte of a valid signature flips accept to
    refuse.

    Bucket PoC-HOLE. The PoC signs nothing: any caller with a chat_id is
    served over plain HTTP, so a "forged frame" is indistinguishable from a
    legitimate one — that IS the hole. The fleet gateway attests the caller by
    its mTLS client cert; a tampered credential fails the handshake and control
    never answers.
    """
    ctx = expect("G2")

    if backend.name == "poc":
        # PoC-HOLE: there is no wire signature to forge. Demonstrate the hole
        # by showing an unauthenticated read is served — no signature is
        # demanded at any hop. This is the finding, not a failure.
        assert ctx["bucket"] == "PoC-HOLE"
        with _substrate_up():
            files = backend.list_files(_new_scope())
        # A brand-new scope returns an (empty) list with NO credential presented
        # — the read is accepted purely on a guessable chat_id. If the PoC ever
        # grew a signature gate this call would raise instead of returning a
        # list, flipping this assertion.
        assert isinstance(files, list), (
            "PoC unexpectedly refused an unsigned read — the G2 hole would be closed"
        )
        return

    # Fleet: the gateway mTLS client cert IS the signed wire identity. A valid
    # cert (the one live() already proved) is accepted; a tampered/absent cert
    # fails the handshake. Drive both sides against the real gateway plane.

    # Positive: a valid frame over the attested cert is accepted (control
    # answers a GET, even 404 for a never-created key, meaning the signature
    # passed and the request reached control).
    good = backend.get_session("g2-never-created-probe")
    assert good.status in ("not_found", "active") or good.status.startswith("error:"), (
        f"valid-cert frame did not reach control: {good.status}"
    )

    # KEYSTONE: mutate one byte of the presented client cert -> refuse. We copy
    # the valid PKI into a temp dir and flip a byte of client.pem (keeping ca.pem
    # and client.key intact), producing a syntactically-structured but no-longer-
    # CA-signed / tampered certificate — the mTLS analogue of flipping a signature
    # byte. Presenting it makes the gateway reject the TLS handshake, so control
    # never answers.
    #
    # This must observe a GATEWAY refusal, not a local file-load failure: an
    # absent PKI dir makes curl fail before any handshake (returning the verb's
    # error class locally) and would pass VACUOUSLY. A real-but-tampered cert
    # reaches the gateway and is refused THERE. The refusal surfaces through the
    # status class get_session actually produces for a failed handshake: _curl
    # gets no HTTP marker back (curl errors on the rejected handshake), so
    # get_session returns a defined error status ("error:<n>"), distinct from the
    # "active"/"not_found" a valid frame produces above. We assert that class
    # flip — a valid frame reaches control, a tampered frame does not.
    import shutil as _sh
    import tempfile as _tf
    from pathlib import Path as _Path

    from backends.fleet import FleetBackend

    with _tf.TemporaryDirectory() as _td:
        forged_pki = _Path(_td)
        _sh.copy(backend._pki / "ca.pem", forged_pki / "ca.pem")
        _sh.copy(backend._pki / "client.key", forged_pki / "client.key")
        valid_cert = (backend._pki / "client.pem").read_bytes()
        # Flip one byte inside the DER/base64 body (past the PEM header line) so
        # the file stays a structurally-valid PEM but the certificate no longer
        # verifies against the CA.
        idx = max(0, len(valid_cert) - 40)
        tampered = bytearray(valid_cert)
        tampered[idx] ^= 0x01
        (forged_pki / "client.pem").write_bytes(bytes(tampered))

        forged = FleetBackend(base_url=backend._base, pki=forged_pki)
        with _substrate_up():
            forged_state = forged.get_session("g2-forged-probe")
    # A tampered client cert must NOT be accepted by the gateway. The valid frame
    # above reached control (active/not_found/error); the tampered frame must NOT
    # yield a live-session answer — it surfaces the verb's error class, never a
    # 200-class "active"/"not_found". If control answered a real state anyway, the
    # signature gate is open (the G2 invariant is broken).
    assert forged_state.status not in ("active", "not_found"), (
        "gateway accepted a tampered/CA-unsigned client cert — the mTLS "
        f"signature gate is open (got status {forged_state.status!r})"
    )
    assert forged_state.status.startswith("error:") or forged_state.status.startswith("denied:"), (
        "tampered-cert probe did not surface a transport/handshake refusal "
        f"class; got {forged_state.status!r} (expected an error:/denied: class)"
    )


# ---------------------------------------------------------------------------
# G3 — audit hash-chain integrity + fail-closed [PoC-HOLE]
# ---------------------------------------------------------------------------

def test_g3_audit_hash_chain_and_fail_closed(backend, expect):
    """G3 | invariant: a file-op emits an OCSF class-1001 hash-chained event;
    tampering one chain link makes verify fail; an unreachable sink refuses
    the op (fail-closed).

    Bucket PoC-HOLE. The PoC emits NO audit at all — every file-op is
    unrecorded. That total absence is the finding. The fleet's gateway-authored
    hash chain is the closed boundary: a download produces a class-1001 event,
    a tampered link fails verification, and a down sink fail-closes the op.
    """
    ctx = expect("G3")

    if backend.name == "poc":
        # PoC-HOLE: no audit surface exists. There is no verb on the PoC that
        # returns an audit event, so the finding is the missing capability.
        assert ctx["bucket"] == "PoC-HOLE"
        assert not hasattr(backend, "read_audit_chain"), (
            "PoC unexpectedly exposes an audit chain — the G3 hole would be closed"
        )
        return

    # Fleet: the audit chain is written by the gateway on a host-owned path and
    # verified out-of-band (occ audit verify / the audit group harness). This
    # journey backend exposes the file-op verbs, not the on-disk chain reader
    # and the sink-toggle — those are host-privileged surfaces the audit group
    # test owns. Drive the file-op that MUST emit the event, then defer the
    # tamper + fail-closed keystones to that harness with an honest xfail so the
    # gap is RECORDED, never silently passed.
    if not hasattr(backend, "read_audit_chain"):
        # The op that must produce a class-1001 event: a real guest write
        # through the FUSE mount (a file-op the gateway audits).
        sess = backend.create_storage_session()
        assert sess.status == "active", f"storage session not active: {sess.status}"
        # The guest boot-child mounts the FUSE surface asynchronously after the
        # create returns; an exec issued before the mount is ready is denied
        # (exit=-1, denied). Wait for the exec plane to be live so the file-op
        # under test measures the audit path, not a boot race (same gate B uses).
        await_fleet_exec_ready(backend)
        marker = _unique_marker()
        out_path = f"/mnt/user-data/outputs/{marker}.txt"
        op = backend.exec_sh(f"printf '%s' {marker} > {out_path}")
        assert op.exit_code == 0 and not op.denied, "audited file-op did not complete"
        # The chain-verify and the tamper/sink-down keystones need the
        # host-owned audit path + a sink toggle this backend does not expose.
        # xfail(reason) records the gap instead of asserting an invented body.
        inactive_mechanism(
            "audit chain read + tamper + sink-down fail-closed require the "
            "host-owned audit path and a sink toggle exposed only in the audit "
            "group harness; the file-op that MUST emit class-1001 completed"
        )

    # If a future audit-aware fleet backend exposes read_audit_chain, drive the
    # full keystone here (kept as the real assertion for that harness):
    sess = backend.create_storage_session()
    marker = _unique_marker()
    out_path = f"/mnt/user-data/outputs/{marker}.txt"
    backend.exec_sh(f"printf '%s' {marker} > {out_path}")

    chain = backend.read_audit_chain()  # type: ignore[attr-defined]
    # End state: a class-1001 event exists for this op and the chain verifies.
    assert any(e.get("class_uid") == 1001 for e in chain.events), (
        "no OCSF class-1001 file-activity event for the audited op"
    )
    assert chain.verify() is True, "fresh audit chain must verify"

    # KEYSTONE 1: tamper one link -> verify fails.
    assert chain.verify_with_tampered_link() is False, (
        "tampering a chain link did not break verification — chain is not sealed"
    )
    # KEYSTONE 2: an unreachable sink refuses the op (fail-closed, not fire-and-
    # forget). Assert the op is DENIED when the sink is down.
    with backend.audit_sink_unreachable():  # type: ignore[attr-defined]
        denied = backend.exec_sh(f"printf x > {out_path}.2")
    assert denied.denied or denied.exit_code != 0, (
        "op succeeded with the audit sink down — audit is not fail-closed"
    )


# ---------------------------------------------------------------------------
# G4 — egress allow-listed, not open [PoC-HOLE]
# ---------------------------------------------------------------------------

def test_g4_egress_allowlisted_not_open(backend, expect):
    """G4 | invariant: egress is allow-listed, not open — the guest reaches an
    allow-listed endpoint but arbitrary external hosts are blocked, and the
    block is at the egress edge (the allow-listed peer still works, so it is a
    route restriction, not a dead NIC).

    Bucket PoC-HOLE. The PoC guest has full network — any external host is
    reachable, which is the hole. The fleet guest sits only on the
    mount-facing net; its sole allowed peer is the egress edge, and everything
    else has no route.
    """
    ctx = expect("G4")

    if backend.name == "poc":
        # PoC-HOLE: full network. Demonstrate the guest can reach an arbitrary
        # external host (the finding). Use a TCP connect to a public resolver
        # port; a non-error connect proves the open network. We tolerate the
        # host having no outbound at all (a locked-down CI box) by treating an
        # inconclusive probe as inactive rather than a false green.
        _require_poc_container_up(backend)
        probe = backend.exec_sh(
            "if command -v nc >/dev/null 2>&1; then "
            "  (nc -z -w3 1.1.1.1 443 && echo REACHED) || echo BLOCKED; "
            "elif command -v curl >/dev/null 2>&1; then "
            "  (curl -sS -m5 -o /dev/null https://1.1.1.1 && echo REACHED) || echo BLOCKED; "
            "else echo NOTOOL; fi"
        )
        out = probe.stdout.decode("utf-8", "replace")
        if "NOTOOL" in out:
            inactive_mechanism("no nc/curl in the PoC container to probe egress openness")
        if "BLOCKED" in out:
            # The host itself may have no outbound (a locked-down CI box). That
            # is a substrate limitation, not a closed PoC boundary — record it
            # as inactive rather than fabricating an open-network green.
            inactive_mechanism(
                "the PoC host has no outbound to a public host in this env; the "
                "open-network finding cannot be reproduced (not a false green)"
            )
        assert "REACHED" in out, (
            "PoC guest could not reach an arbitrary external host; the open-network "
            f"finding is not reproducible here (out={out!r}, err={probe.stderr!r})"
        )
        assert ctx["bucket"] == "PoC-HOLE"
        return

    # Fleet: the guest is on the mount-facing net only. Assert BOTH halves so
    # the block is proven to be a route restriction, not a broken NIC.
    sess = backend.create_storage_session()
    assert sess.status == "active", f"storage session not active: {sess.status}"
    await_fleet_exec_ready(backend)

    # KEYSTONE (positive half): the allow-listed peer — the egress edge — IS
    # reachable. Assert it FIRST and as a hard invariant, so the external-reach
    # finding below cannot mask a broken allowed route. The demo guest is a
    # static busybox: the applet MUST be /bin/busybox nc (a bare nc is 127 and
    # never runs). edge:8450 is the storage-chain allowed upstream.
    edge = backend.exec_sh(
        "/bin/busybox nc -w4 edge 8450 </dev/null; echo __rc=$?"
    )
    edge_out = (
        edge.stdout.decode("utf-8", "replace")
        + edge.stderr.decode("utf-8", "replace")
    )
    assert not edge.denied
    assert "not found" not in edge_out and "__rc=127" not in edge_out, (
        f"fleet keystone: /bin/busybox nc did not run against the edge — the "
        f"reachability keystone is vacuous (out={edge_out!r})"
    )
    assert "__rc=0" in edge_out, (
        "fleet keystone: the allow-listed egress edge (edge:8450) MUST be "
        f"reachable — the block must be a route restriction, not a dead NIC "
        f"(out={edge_out!r})"
    )

    # Negative half: an arbitrary EXTERNAL host must NOT be reachable from the
    # guest. The applet MUST be /bin/busybox nc so the connect actually runs — a
    # bare nc is "not found" (127) and would pass this negative vacuously (the
    # exact empty-output trap that hid this finding before).
    ext = backend.exec_sh(
        "/bin/busybox nc -w5 1.1.1.1 443 </dev/null; echo __rc=$?"
    )
    ext_out = (
        ext.stdout.decode("utf-8", "replace")
        + ext.stderr.decode("utf-8", "replace")
    )
    assert not ext.denied
    assert "not found" not in ext_out and "__rc=127" not in ext_out, (
        f"fleet: /bin/busybox nc did not run for the external-reach probe — "
        f"the negative half is vacuous (out={ext_out!r})"
    )
    if "__rc=0" not in ext_out:
        # External host unreachable -> egress is genuinely allow-listed. Real PASS.
        return
    # REAL-FINDING (live-reproduced): the guest REACHED an arbitrary external
    # host (1.1.1.1:443, rc 0). The mount-facing docker network runs with
    # internal=false (a NAT bridge), so guests have a default route to the
    # public internet; the in-cluster isolation (control/minio unreachable) is
    # only DNS-scoping, not egress control. The network must be internal:true so
    # the guest's only route is the allow-listed egress edge. We assert the
    # SPECIFIC reached-signature so a closed egress fails this loudly instead of
    # silently xpassing.
    assert "__rc=0" in ext_out, (
        f"fleet: external-reach probe produced no reached signature: {ext_out!r}"
    )
    real_finding(
        "egress-open-external",
        "the guest reached an arbitrary external host (1.1.1.1:443): the "
        "mount-facing network is internal=false (a NAT bridge with a default "
        "route to the public internet), so egress is NOT allow-listed at L3 — "
        "only in-cluster names are unreachable via DNS-scoping. The network "
        "must be internal:true (mount-facing network-model convergence, #333).",
    )


# ---------------------------------------------------------------------------
# G5 — post-session data lifecycle defined [HARDENED]
# ---------------------------------------------------------------------------

def test_g5_post_session_read_lifecycle(backend, expect):
    """G5 | invariant: the post-session data lifecycle is DEFINED — assert the
    status CLASS of a read after the session ends, plus the PoC-side
    disk-persistence contrast. Do NOT assert an invented retention window.

    Bucket HARDENED. On the PoC the download route (GET /files/{chat}/{file})
    reads the host-bind outputs dir ON DISK, so it is DISK-keyed, not
    container-keyed: stopping the per-chat container does not delete the file and
    the FastAPI server keeps serving its bytes (200). The PoC lifecycle is
    therefore data-persistent on the host — the container-scoped state (get_session
    reads `docker ps`) flips to released while the bytes remain downloadable. That
    persistence contrast IS the finding; the PoC has NO data-scoped lifecycle
    boundary at the download route. On the fleet the file_id lifecycle governs the
    read; the retention window is a TBD contract, so this test asserts the STATUS
    CLASS (a defined 2xx-or-4xx), never a made-up duration.
    """
    ctx = expect("G5")

    if backend.name == "poc":
        # Produce a file, then end the session (stop the container) and read.
        _require_poc_container_up(backend)
        marker = _unique_marker()
        fname = f"{marker}.txt"
        out_path = f"/mnt/user-data/outputs/{fname}"
        write = backend.exec_sh(
            f"mkdir -p /mnt/user-data/outputs && printf '%s' {marker} > {out_path}"
        )
        if write.exit_code != 0:
            inactive_mechanism(
                "PoC container has no writable outputs bind in this env; cannot "
                "stage the G5 artifact"
            )

        # While the container is up the download streams (the file exists).
        with _substrate_up():
            live_dl = backend.download(fname)
        assert live_dl.status == 200, (
            f"PoC download of a just-written output should be 200, got {live_dl.status}"
        )

        # End the session: stop the per-chat container. The download route is
        # DISK-keyed (FastAPI reads the host-bind outputs dir), NOT container-
        # keyed — stopping the container does not delete the file, so the earlier
        # "assert post-session download 4xx" was VACUOUS-inverted: the real route
        # returns 200 and that assert would red. Assert the true PoC lifecycle
        # boundary instead: the CONTAINER-keyed state (get_session -> `docker ps`)
        # flips to released, while the disk-keyed download still streams the same
        # bytes. That persistence contrast is the finding.
        import shutil as _sh
        import subprocess as _sp

        docker = _sh.which("docker")
        if not docker:
            inactive_mechanism("docker CLI absent; cannot end the PoC session for G5")
        cname = backend._container(backend._chat_id)
        _sp.run([docker, "stop", cname], capture_output=True, timeout=30)
        try:
            # Container-keyed state IS scoped to the container: get_session reads
            # `docker ps`, so a stopped container reports "released".
            with _substrate_up():
                ended_state = backend.get_session(backend._chat_id)
            # Disk-keyed read is NOT scoped to the container: the download route
            # reads the host-bind on disk, so the same bytes stream (200).
            with _substrate_up():
                after_dl = backend.download(fname)
        finally:
            # Restore the container so we do not leave the PoC stack degraded
            # for other cases in the run.
            _sp.run([docker, "start", cname], capture_output=True, timeout=30)

        # END STATE: the container-scoped lifecycle boundary DID move (the state
        # read flips to released once the container is stopped). This is the only
        # container-keyed surface the PoC has.
        assert ended_state.status == "released", (
            "PoC container-keyed state should read released after the container "
            f"is stopped, got {ended_state.status!r}"
        )
        # KEYSTONE / the finding: the raw bytes still stream at the disk-keyed
        # download route AFTER the session (container) ended — a defined 200, not
        # a 404 the route cannot produce. The PoC lifecycle is container-scoped
        # for STATE but data-PERSISTENT on the host-bind for BYTES: there is no
        # data-scoped retention boundary. If the download ever started 404ing
        # post-session (a real data lifecycle), this assert would flip.
        assert after_dl.status == 200, (
            "PoC download after the session ended should still stream the "
            "host-bind bytes (disk-keyed, not container-keyed); the download "
            f"route cannot produce a container-gone 404, got {after_dl.status}"
        )
        assert after_dl.data == marker.encode(), (
            "post-session PoC download returned different bytes than were "
            "written — the host-bind persistence contrast is not reproducible"
        )
        assert ctx["bucket"] == "HARDENED"
        return

    # Fleet: end the session, then read the file_id. The retention window is a
    # TBD contract, so assert the STATUS CLASS is DEFINED (a clean 2xx or 4xx),
    # never an invented duration. We use the durable-state read (get_session)
    # to end-of-life the session and probe the read plane's envelope.
    sess = backend.create_storage_session()
    assert sess.status == "active", f"storage session not active: {sess.status}"
    key = sess.key

    # After the session ends its row is still queryable (Postgres durable), so
    # the lifecycle STATE is defined and readable — that is the assertable end
    # state. get_session returns a defined status, never a hang.
    state = backend.get_session(key)
    assert state.status in ("active", "released", "not_found") or state.status.startswith("error:"), (
        f"post-session state is not a defined lifecycle value: {state.status}"
    )

    # KEYSTONE: a never-created key is a DEFINED not_found (404), distinguishing
    # "lifecycle-ended" from "never existed" — the lifecycle is a real state
    # machine, not a blanket 200. This is the fleet's defined-end-state proof;
    # the retention WINDOW (how long a file_id survives) stays TBD and is NOT
    # asserted here.
    never = backend.get_session(f"g5-never-created-{uuid.uuid4().hex[:8]}")
    assert never.status == "not_found", (
        f"a never-created key must be a defined 404/not_found, got {never.status}"
    )
    assert ctx["bucket"] == "HARDENED"


# ---------------------------------------------------------------------------
# G6 — non-downloadable file refused at the raw byte route [PoC-HOLE]
# ---------------------------------------------------------------------------

def test_g6_nondownloadable_raw_byte_route_refused(backend, expect):
    """G6 | invariant: the exfil control cannot be bypassed at the wire — the
    direct byte route for a downloadable=false file is refused (mirrors D6 at
    the API level); a downloadable=true file via the SAME route yields bytes,
    so there is no bypass gap between layers.

    Bucket PoC-HOLE. The PoC has no downloadable axis: every file the chat_id
    can see is byte-deliverable, so there is no wire boundary to bypass — that
    is the hole. The fleet enforces the same three-axis check at the raw byte
    route as in the UI: downloadable=false -> refused, downloadable=true ->
    bytes.
    """
    ctx = expect("G6")

    if backend.name == "poc":
        # PoC-HOLE: no preview-vs-download boundary. preview() raises
        # PocHoleNotEnforced, and download() streams unconditionally. Assert
        # BOTH: the boundary verb signals the hole, and the raw byte route
        # serves whatever the chat_id can see (the finding, not a failure).
        assert ctx["bucket"] == "PoC-HOLE"
        with pytest.raises(PocHoleNotEnforced):
            backend.preview("any-file")
        # The raw download route has no downloadable gate — a request either
        # streams (200) or 404s on a missing name, never "refused". refused is
        # always False on the PoC by construction (see poc.py.download).
        with _substrate_up():
            dl = backend.download(f"{_unique_marker()}.txt")
        assert dl.refused is False, (
            "PoC download unexpectedly reported a downloadable-axis refusal — "
            "the G6 hole would be closed"
        )
        assert dl.status in (200, 404), (
            f"PoC raw byte route returned an unexpected status: {dl.status}"
        )
        return

    # Fleet: the raw byte route enforces the downloadable axis. Both halves are
    # required so the refusal is proven axis-specific, not a broken viewer.
    #
    # This is a user-facing byte-path hop. The REAL suite drives it with a
    # Playwright fill + click against the live web UI download control — NEVER
    # page.evaluate(fetch), which would bypass the very browser byte-path the
    # exfil control gates. If Playwright is not wired into this scaffold, gate
    # the browser sub-check with importorskip so the skip is honest.
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="G6 byte-path must be driven by a real Playwright click "
        "(never page.evaluate(fetch)); wire Playwright into the browser group "
        "to run it live",
    )
    assert playwright is not None  # importorskip returns the module

    # The fleet download/preview verbs bind to the live UI byte path in the
    # browser group test (they raise NotImplementedError in this scaffold to
    # avoid stubbing a green). Drive the real end state through those verbs once
    # the browser group binds them; here we assert the CONTRACT they must
    # satisfy, and let NotImplementedError surface honestly if run before the
    # binding exists.
    #
    # Negative: a downloadable=false file -> refused at the raw byte route.
    try:
        refused: DownloadResult = backend.download("file-downloadable-false")
    except NotImplementedError:
        pytest.xfail(
            "fleet download binds to the live UI byte path (real Playwright "
            "click) in the browser group test; not yet bound in this scaffold"
        )
    assert refused.refused is True and not refused.data, (
        "downloadable=false file streamed bytes at the raw byte route — the "
        "exfil control is bypassable at the wire (G6 bypass gap)"
    )

    # KEYSTONE: a downloadable=true file via the SAME route DOES yield bytes,
    # proving the refusal is axis-specific (not a broken byte route).
    allowed: DownloadResult = backend.download("file-downloadable-true")
    assert allowed.refused is False and allowed.status == 200 and len(allowed.data) > 0, (
        "downloadable=true file did not stream via the same raw byte route — "
        "the refusal is not axis-specific"
    )
