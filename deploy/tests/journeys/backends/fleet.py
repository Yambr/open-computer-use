# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""Fleet backend: gateway mTLS -> control -> gVisor guest -> FUSE -> egress
edge -> filestore -> MinIO.

Targets the real fleet surface. The create/exec wire bodies reuse the exact
shapes proven by deploy/fleet/storage-chain-demo.sh and exec-demo.sh:

    POST /v1alpha/sessions
      {"session_hint": "...",
       "image": "...",                         # omit for compute/exec session
       "mount_intent": {"destination": "/mnt/user-data/outputs/",
                        "filesystem_id": "fs-fleet",
                        "read_only": false,
                        "cache_duration_s": 3600},
       "egress_policy": {"default_deny": true,
                         "allowed_upstream": "https://edge:8450",
                         "filesystem_id": "fs-fleet"}}

    POST /v1alpha/sessions/exec
      {"session_hint": "...", "argv": [...]}    # response carries stdout_b64

    GET  /v1alpha/sessions/{key}

All three go through the gateway mTLS plane with ONE client cert (one cert =
one host-attested caller). The cert/key/CA live under deploy/fleet/gateway-pki.
The operator kill-switch (revoke/all, resume/all) is a host-owned UDS at
/run/ocu-control/operator.sock, reachable only where the fleet host mounts it.

live() returns True ONLY when Lima + runsc are detected and the fleet compose
is up. FUSE/runsc cannot run on a Darwin host, so on a Mac this backend is
never live and conftest skips every fleet case with a loud reason. This
backend NEVER mocks a green.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from .base import (
    Backend,
    BackendUnavailable,
    DownloadResult,
    ExecResult,
    FileRef,
    SessionRef,
    SURFACE_INPUTS,
    SURFACE_OUTPUTS,
)

# Control's gateway mTLS plane (host-mapped 127.0.0.1:9466 in the fleet compose).
FLEET_BASE = os.getenv("FLEET_BASE", "https://127.0.0.1:9466")
# gateway-pki dir: one client cert = one host-attested caller.
_DEFAULT_PKI = Path(__file__).resolve().parents[3] / "fleet" / "gateway-pki"
FLEET_PKI = Path(os.getenv("FLEET_PKI", str(_DEFAULT_PKI)))
# The demo guest image (busybox layered over the assembled substrate so a
# write goes through the real FUSE mount). Override per checkout.
FLEET_GUEST_IMAGE = os.getenv("FLEET_GUEST_IMAGE", "ocu-guest:assembled-demo")
# The mount filesystem_id the storage-chain demo uses.
FLEET_FS_ID = os.getenv("FLEET_FS_ID", "fs-fleet")
# The operator UDS the host mounts (kill-switch / resume ingress).
FLEET_OPERATOR_SOCK = os.getenv(
    "FLEET_OPERATOR_SOCK", "/run/ocu-control/operator.sock"
)
# The container name control derives for a session key (ocu-sess-{key}).
_CNAME_PREFIX = "ocu-sess-"
_HTTP_TIMEOUT_S = float(os.getenv("FLEET_HTTP_TIMEOUT_S", "40"))


class FleetBackend(Backend):
    """Concrete fleet backend. Real mTLS wire against control + guest."""

    def __init__(self, base_url: str = FLEET_BASE, pki: Path = FLEET_PKI):
        self._base = base_url.rstrip("/")
        self._pki = Path(pki)
        # Track the last session key so exec/get/download can address it.
        self._last_hint: Optional[str] = None
        self._last_key: Optional[str] = None
        # key -> session_hint for every session THIS backend created. The gateway
        # read surface (POST /v1alpha/sessions/status) addresses a session by the
        # caller's own hint (owner-sealed, NFR-SEC-43), not by a path-param key —
        # so get_session(key) resolves the hint the caller minted the row with.
        # Multi-session tests (E4/E5) read several distinct keys, so a per-latest
        # _last_hint is not enough; this map addresses any of them.
        self._hint_by_key: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "fleet"

    # -- availability --------------------------------------------------

    def live(self) -> bool:
        """True ONLY if Lima + runsc are detected AND the fleet compose is up.

        Probe, in order (any miss -> False, never raises):
          1. docker CLI present.
          2. runsc registered as a Docker runtime (the gVisor substrate).
          3. control's gateway plane answers on the mTLS port.
        A Darwin host cannot run runsc, so step 2 fails there and every fleet
        case is skipped loudly by conftest. This never substitutes a mock and
        never reports a green for an absent stack.
        """
        docker = shutil.which("docker")
        if not docker:
            return False
        if not self._pki_present():
            return False
        try:
            info = subprocess.run(
                [docker, "info", "--format", "{{json .Runtimes}}"],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if info.returncode != 0 or b"runsc" not in info.stdout:
            return False
        # control's gateway plane must answer over the client cert.
        return self._control_answers()

    def _pki_present(self) -> bool:
        return all(
            (self._pki / f).is_file() for f in ("ca.pem", "client.pem", "client.key")
        )

    def _control_answers(self) -> bool:
        """A curl over the mTLS plane returns any HTTP status (not a connect

        failure). Uses curl because it speaks the Ed25519 client cert the
        gateway PKI issues (matching the demo scripts). Returns False on any
        transport failure.
        """
        curl = shutil.which("curl")
        if not curl:
            return False
        try:
            proc = subprocess.run(
                [
                    curl, "-sS", "--max-time", "10",
                    "--cacert", str(self._pki / "ca.pem"),
                    "--cert", str(self._pki / "client.pem"),
                    "--key", str(self._pki / "client.key"),
                    "-o", os.devnull, "-w", "%{http_code}",
                    f"{self._base}/v1alpha/sessions/never-created-probe",
                ],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        # Any HTTP code (e.g. 404) means the mTLS handshake + control answered.
        return proc.returncode == 0 and proc.stdout.strip().isdigit()

    # -- mTLS wire helpers ---------------------------------------------

    def _curl(self, method: str, path: str, body: Optional[dict] = None) -> tuple[int, dict]:
        """Issue an mTLS request and return (http_status, parsed_json_body).

        Uses curl with the gateway client cert (the demo-proven transport).
        Raises BackendUnavailable on a transport failure so conftest skips
        rather than reporting a green. A non-JSON body parses to {}.
        """
        curl = shutil.which("curl")
        if not curl:
            raise BackendUnavailable("curl not found for fleet mTLS wire")
        args = [
            curl, "-sS", "--max-time", str(int(_HTTP_TIMEOUT_S)),
            "--cacert", str(self._pki / "ca.pem"),
            "--cert", str(self._pki / "client.pem"),
            "--key", str(self._pki / "client.key"),
            "-w", "\n__HTTP_%{http_code}__",
            "-X", method, f"{self._base}{path}",
        ]
        if body is not None:
            args += ["-H", "content-type: application/json", "-d", json.dumps(body)]
        try:
            # `self._base` comes from the stand's own env (the operator who
            # launched pytest), and reaches curl as a single argv element — no
            # shell, no string-assembled command. The one sharp edge is a value
            # beginning with `-`, which curl would read as an option rather than
            # a URL; that is a misconfiguration by the person who set it, not a
            # boundary crossing. It would NOT be acceptable for a value arriving
            # from CI metadata or any source outside this trust domain.
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
            proc = subprocess.run(args, capture_output=True, timeout=_HTTP_TIMEOUT_S + 5)
        except subprocess.SubprocessError as exc:
            raise BackendUnavailable(f"fleet wire failure on {path}: {exc}") from exc
        out = proc.stdout.decode("utf-8", "replace")
        status = _parse_status(out)
        payload = _parse_json_prefix(out)
        return status, payload

    def _cname(self, key: str) -> str:
        return f"{_CNAME_PREFIX}{key}"

    # -- journey verbs -------------------------------------------------

    def login(self) -> Any:
        """Return the first-party session handle after embed-token verify.

        The web UI (component 08) mints a first-party cookie (SameSite=None,
        Secure, HttpOnly) only after verifying the embed token's signature,
        audience, and exp<=120s. Driving that bootstrap end-to-end is a
        browser journey (real Playwright); this verb returns the wire-level
        caller identity (the mTLS client cert already attested by the gateway)
        so non-browser fleet verbs can proceed. The cookie/embed A1-A3
        scenarios drive the live UI in the browser group test.
        """
        return {"caller": "mtls-client-cert", "pki": str(self._pki)}

    def upload(self, surface: str, name: str, data: bytes) -> FileRef:
        """Upload onto the FUSE mount for the given surface.

        Fleet inputs is readonly:true (dir 0555 / file 0444), so a user-side
        write to inputs is the provisioning path (control stages inputs before
        the mount starts), and an outputs-surface user write is the normal
        agent path. The chunked F9 / mount-plane upload wire is exercised by
        the storage group test that owns the guest exec + FUSE write; the
        scaffold does not fabricate an upload result. Left NotImplemented so a
        storage group test binds it to the real wire.
        """
        if surface not in (SURFACE_INPUTS, SURFACE_OUTPUTS):
            raise ValueError(f"unknown surface: {surface!r}")
        raise NotImplementedError(
            "fleet upload binds to the live F9 / mount-plane chunked wire in "
            "the storage group test; do not stub a green"
        )

    def run_agent(self, prompt: str) -> ExecResult:
        """The agent loop lives in the calling client, not in OCU (v1 non-goal).

        A fleet journey produces an outputs artifact by exec-ing a write into
        the FUSE mount (the same end state), which is what the storage-chain
        demo proves. Group tests drive that via exec(); this verb is not a
        model-hosting path and is intentionally not implemented here.
        """
        raise NotImplementedError(
            "OCU does not host the agent loop (v1 non-goal); a fleet journey "
            "produces artifacts via exec() into the FUSE mount"
        )

    def exec(self, argv: list[str]) -> ExecResult:
        """POST /v1alpha/sessions/exec with the last session_hint.

        Reuses the exec-demo.sh body shape {"session_hint", "argv"}; the
        response carries stdout_b64, decoded into ExecResult. A hint this
        caller never created returns a denied result (control's owner-sealed
        row -> 404).
        """
        if self._last_hint is None:
            raise BackendUnavailable("no session created yet; call create_session first")
        status, payload = self._curl(
            "POST", "/v1alpha/sessions/exec",
            {"session_hint": self._last_hint, "argv": argv},
        )
        # Only a 2xx carries a real exec result. Every refusal is denied — NOT a
        # successful exec with exit 0. Control refuses an exec into an
        # unaddressable / revoked session (404 ErrNotOwned; 409 "request refused"
        # after revoke/all force-killed the row; 401/403 for an unattested or
        # forbidden caller). Mapping any of these to exit_code 0 would make a
        # kill-switch or isolation assertion pass for the WRONG reason (the E1/E2
        # "exec denied after revoke/all" keystone). A -1 exit + denied=True is the
        # honest shape for "the exec did not run".
        if status not in (200, 201):
            return ExecResult(exit_code=-1, stdout=b"", stderr=b"", denied=True)
        stdout = _b64_field(payload, "stdout_b64")
        stderr = _b64_field(payload, "stderr_b64")
        return ExecResult(
            exit_code=int(payload.get("exit_code", 0)),
            stdout=stdout,
            stderr=stderr,
            denied=False,
        )

    def exec_sh(self, script: str) -> ExecResult:
        """Run ``script`` via ``/bin/busybox sh -c`` in the gVisor guest.

        The demo guest image (ocu-guest:assembled-demo) is a static busybox with
        NO /bin/sh and no coreutils on PATH, so every applet must be invoked
        through /bin/busybox exactly as deploy/fleet/storage-chain-demo.sh and
        exec-demo.sh do. A bare ["sh", "-c", ...] there is ENOENT / exit 127,
        which would make a negative assertion pass for the wrong reason. Routes
        through the same exec() wire (POST /v1alpha/sessions/exec).
        """
        return self.exec(["/bin/busybox", "sh", "-c", script])

    def list_files(self, scope: str) -> list[FileRef]:
        """List via the F9 /v1/files read plane, scoped to ``scope``.

        F9 returns opaque server-minted scope-bound file_ids, cursor-paginated;
        a foreign scope returns none of this scope's files, and an unknown /
        foreign file_id keystone is 404 (not 403), with no enumeration oracle.
        F9 is an internal (no host port) plane in the fleet compose, reached
        via the web UI or an in-cluster caller; the storage group test binds
        this to the live F9 wire. Left NotImplemented so it is bound to the
        real plane, never stubbed.
        """
        raise NotImplementedError(
            "fleet list_files binds to the live F9 /v1/files cursor wire in "
            "the storage group test; do not stub"
        )

    def download(self, file_id: str) -> DownloadResult:
        """Download through the three-axis authz (scope + read + downloadable).

        A downloadable=false file returns refused=True with no bytes to the
        browser (the preview-not-download exfil control). The byte path is
        driven end-to-end in the browser journey via a real Playwright click,
        never page.evaluate(fetch). Left NotImplemented so the browser group
        test binds it to the live UI download.
        """
        raise NotImplementedError(
            "fleet download binds to the live UI byte path (real Playwright "
            "click) in the browser group test; do not stub"
        )

    def preview(self, file_id: str) -> DownloadResult:
        """Render a preview in-session; the byte-to-browser path stays refused

        for downloadable=false. Driven in the browser group test (real fill +
        click). Left NotImplemented so it binds to the live preview surface.
        """
        raise NotImplementedError(
            "fleet preview binds to the live UI preview surface in the "
            "browser group test; do not stub"
        )

    def create_session(self, image: Optional[str] = None) -> SessionRef:
        """Create a live session for the lifecycle journeys (delegates to storage).

        The lifecycle invariants the E group asserts — operator revoke/all,
        the tier-quota ceiling, boot-reconcile, kill-switch — are properties of
        a reserved session ROW, not of whether that session carries a mount. On
        this deploy a mountless (compute) create currently fails at the
        materialize stage (a per-session bridge the storage path skips), a
        separate control defect tracked outside this suite; a storage session
        is a valid live session that exercises the same reservation/lifecycle
        row. So this verb creates a storage session — the E group needs a live
        session, not specifically a mountless one.

        ``image`` is passed THROUGH to the create body so the image-gate
        (A6) is exercisable: an off-allow-list image reaches admission and is
        denied (4xx), an allow-listed image (or None -> the demo default) is
        admitted. When None, create_storage_session pins the allow-listed demo
        image.
        """
        return self.create_storage_session(image=image)

    def create_storage_session(self, image: Optional[str] = None) -> SessionRef:
        """Create a storage session with the full storage-chain-demo body.

        Reuses the exact mount_intent + egress_policy shapes proven by
        deploy/fleet/storage-chain-demo.sh so a guest exec write reaches the
        real FUSE mount. Used by the storage group tests (B/C/D/G).

        ``image`` overrides the guest image sent to control's admission. It is
        NOT silently normalised to the allow-listed default: an off-allow-list
        image is sent as-is so control's image-gate denies it (A6). When None,
        the allow-listed demo image is used.
        """
        import time

        hint = f"journey-storage-{int(time.time() * 1000000)}"
        body = {
            "session_hint": hint,
            "image": image if image is not None else FLEET_GUEST_IMAGE,
            "mount_intent": {
                "destination": "/mnt/user-data/outputs/",
                "filesystem_id": FLEET_FS_ID,
                "read_only": False,
                "cache_duration_s": 3600,
            },
            "egress_policy": {
                "default_deny": True,
                "allowed_upstream": "https://edge:8450",
                "filesystem_id": FLEET_FS_ID,
            },
        }
        status, payload = self._curl("POST", "/v1alpha/sessions", body)
        self._last_hint = hint
        if status not in (200, 201):
            self._last_key = None
            # Name the image in the refusal. Control answers every unclassified
            # refusal with a bare 409 and an EMPTY body on purpose -- the reason
            # lives in the audit stream, not the response -- so a bare
            # "denied:409" sends the reader looking for a quota that is not
            # exhausted. A guest image the daemon does not have fails at
            # materialize and lands here looking identical to one. The image is
            # the single most likely difference between a stand that works and
            # one that does not, so it goes in the message.
            return SessionRef(
                key="",
                status=f"denied:{status}",
                detail=f"image={body['image']}",
            )
        key = payload.get("key", "")
        self._last_key = key or None
        if key:
            # Remember the hint so get_session(key) can address this row via the
            # gateway status surface (which keys on the caller's own hint).
            self._hint_by_key[key] = hint
        return SessionRef(key=key, status="active")

    def destroy_all_sessions(self) -> int:
        """Destroy every session THIS backend created, freeing its slot.

        Per-test teardown. A live session legitimately holds its concurrency
        slot until it is destroyed (an exec exit does NOT end the session — the
        guest is a long-lived UDS service), so a suite that creates one session
        per test and never destroys them accumulates live rows and, after the
        tier cap, every later create 409s. This drives the REAL destroy verb
        (POST /v1alpha/sessions/destroy, addressed by the caller's own hint) so
        each test returns its slot the same way a client's disconnect would —
        NOT a DB-counter poke. Best-effort: a 404 (already gone) or transport
        miss is ignored so teardown never fails a test. Returns the count
        actually destroyed.
        """
        destroyed = 0
        hints = list(self._hint_by_key.values())
        if self._last_hint and self._last_hint not in hints:
            hints.append(self._last_hint)
        for hint in hints:
            try:
                status, _ = self._curl(
                    "POST", "/v1alpha/sessions/destroy", {"session_hint": hint}
                )
                if status in (200, 202, 204):
                    destroyed += 1
            except BackendUnavailable:
                continue
        self._hint_by_key.clear()
        self._last_hint = None
        self._last_key = None
        return destroyed

    def get_session(self, key: str) -> SessionRef:
        """Read a session's state over the gateway mTLS plane.

        The gateway read surface is POST /v1alpha/sessions/status with the
        caller's own session_hint (owner-sealed, NFR-SEC-43) — there is no
        GET /v1alpha/sessions/{key} on this plane (that path-param by-key read
        is the ADR-0022 admin surface on the operator UDS, not the caller
        plane). So a by-key read here resolves the hint the caller minted the
        row with; a value this backend never created is used as a literal hint,
        which control cannot address and returns 404 -> "not_found". Durable in
        Postgres: the status read answers the same row after a control restart.

        The status read travels over the mTLS client cert, so a
        tampered/absent cert still surfaces the handshake refusal as
        "error:<n>" / "denied:<n>" (the G2 keystone).

        State ints map to the reported lifecycle string: 0 reserved / 1 active
        -> "active" (a live reservation), 2 released -> "released".
        """
        hint = self._hint_by_key.get(key, key)
        status, payload = self._curl(
            "POST", "/v1alpha/sessions/status", {"session_hint": hint}
        )
        if status == 404:
            return SessionRef(key=key, status="not_found")
        if status in (401, 403):
            return SessionRef(key=key, status=f"denied:{status}")
        if status not in (200, 201):
            return SessionRef(key=key, status=f"error:{status}")
        state = payload.get("state")
        state_name = {0: "active", 1: "active", 2: "released"}.get(
            state, str(payload.get("status", "active"))
        )
        return SessionRef(key=key, status=state_name)

    def revoke_all(self) -> None:
        """Operator kill-switch over the host UDS /run/ocu-control/operator.sock.

        SO_PEERCRED-gated; reachable only where the fleet host mounts the
        socket. Driven via `occ` or a curl --unix-socket by the lifecycle
        group test (E2/E3). Left NotImplemented so it binds to the real
        operator surface rather than faking a toggle.
        """
        raise NotImplementedError(
            "fleet revoke_all binds to the operator UDS "
            f"({FLEET_OPERATOR_SOCK}) in the lifecycle group test; do not stub"
        )

    def resume_all(self) -> None:
        """Operator resume over the same host UDS. Pre-revoke sessions stay

        denied (resume does not un-revoke). Bound to the real operator surface
        by the lifecycle group test.
        """
        raise NotImplementedError(
            "fleet resume_all binds to the operator UDS "
            f"({FLEET_OPERATOR_SOCK}) in the lifecycle group test; do not stub"
        )


# -- wire parsing helpers ---------------------------------------------


def _parse_status(out: str) -> int:
    """Extract the trailing __HTTP_NNN__ marker curl appends. -1 if absent."""
    marker = "__HTTP_"
    idx = out.rfind(marker)
    if idx == -1:
        return -1
    tail = out[idx + len(marker):]
    digits = tail.split("_", 1)[0]
    return int(digits) if digits.isdigit() else -1


def _parse_json_prefix(out: str) -> dict:
    """Parse the JSON body that precedes the __HTTP_NNN__ marker. {} if none."""
    idx = out.rfind("\n__HTTP_")
    body = out[:idx] if idx != -1 else out
    body = body.strip()
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _b64_field(payload: dict, field: str) -> bytes:
    """Decode a base64 field from a fleet exec response. Empty bytes if absent."""
    import base64

    raw = payload.get(field)
    if not raw:
        return b""
    try:
        return base64.b64decode(raw)
    except (ValueError, TypeError):
        return b""
