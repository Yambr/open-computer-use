# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""Backend interface for the PoC-vs-fleet journey suite.

A journey test speaks the same verbs to both systems and asserts the
per-backend outcome declared in scenarios.yaml. The two backends differ in
what a verb *means*, never in the verb's name, so a paired test reads the
same on both sides. Each verb below documents that semantic difference.

The base is an interface: every verb raises NotImplementedError. Concrete
backends (PocBackend, FleetBackend) implement the verbs against the real
running system. Nothing here mocks a system under test.

Two sentinels carry the meaning that a verb has no analogue on a backend:

    PocHoleNotEnforced   the verb names a boundary the PoC does not have.
                         A [PoC-HOLE] scenario reads this as "the hole is
                         open here" rather than as a test failure.

    BackendUnavailable   the backend's stack is not reachable / not live.
                         conftest turns this into a loud pytest.skip so a
                         down stack is never a green.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


class BackendError(Exception):
    """Base class for backend signalling exceptions."""


class BackendUnavailable(BackendError):
    """The backend's stack is not reachable, or a required substrate

    (e.g. Lima + runsc for the fleet) is absent. conftest converts this to a
    pytest.skip with a loud reason. It is NEVER swallowed into a pass: a
    scenario whose backend is unavailable is reported skipped, not green.
    """


class PocHoleNotEnforced(BackendError):
    """The verb names an authz / isolation boundary the PoC does not have.

    Raised by PocBackend for verbs like revoke_all() or a downloadable-axis
    preview(). A [PoC-HOLE] scenario catches this and reads it as the hole
    being open on the PoC side — that absence IS the finding the scenario
    records. It is not a failure and not a skip.
    """


@dataclass(frozen=True)
class FileRef:
    """A file as the backend surfaces it to the user.

    On the PoC, ``id`` is the on-disk relative path under the chat's outputs
    directory (the host sees the real path). On the fleet, ``id`` is an
    opaque server-minted scope-bound file_id (F9 / ADR-0023) that carries no
    host path. ``scope`` is the chat_id on the PoC and the filesystem_id on
    the fleet. Tests compare files by (scope, id) and by content, never by a
    host path, so the same assertion holds on both backends.
    """

    id: str
    name: str
    scope: str
    size: int


@dataclass(frozen=True)
class DownloadResult:
    """The bytes returned to the browser for a download, plus its envelope.

    ``status`` is the HTTP status class the byte path returned. ``content_type``
    and ``data`` carry the delivered artifact. ``refused`` is True when the
    byte-to-browser path was declined (e.g. downloadable=false on the fleet);
    tests assert on the envelope, never guess at partial bytes.
    """

    status: int
    content_type: str
    data: bytes
    refused: bool = False


@dataclass(frozen=True)
class SessionRef:
    """A created sandbox session.

    ``key`` is the control-issued session key on the fleet, or the chat_id on
    the PoC. ``status`` is the last-known lifecycle state string the backend
    reports (e.g. "active", "released", "denied"). Tests key on the reported
    state, never on a hardcoded timeout.
    """

    key: str
    status: str
    # Free-text diagnosis for a REFUSED create. Kept OUT of `status` because
    # tests compare that field for exact equality ("denied:409"), so anything
    # appended there silently breaks them -- which is exactly what happened
    # when the image name was folded into the status string.
    detail: str = ""


@dataclass(frozen=True)
class ExecResult:
    """The result of an exec inside the guest / container.

    ``exit_code`` is the process exit status. ``stdout`` / ``stderr`` are the
    decoded streams (the fleet wire carries stdout_b64; the backend decodes).
    ``denied`` is True when the exec was refused (e.g. after revoke/all or for
    a session this caller never created).
    """

    exit_code: int
    stdout: bytes
    stderr: bytes
    denied: bool = False


# Mount surfaces a journey verb can target. Both backends map these to the
# same guest paths: PoC to the host-bind /mnt/user-data/{uploads,outputs}
# (docker_manager.py binds uploads :ro, outputs :rw); fleet to the FUSE
# /mnt/user-data/{uploads,outputs} (guest-config.json: uploads readonly:true
# dir 0555/file 0444, outputs readonly:false dir 0755/file 0644). The
# read-only user-input surface is "uploads" on both — there is no "inputs"
# directory on either backend, so the read-only keystone must target uploads
# for the write to hit a real read-only inode (EROFS/EACCES), not ENOENT.
SURFACE_UPLOADS = "uploads"
SURFACE_OUTPUTS = "outputs"
# Back-compat alias: the read-only user-input surface. Points at the real
# read-only mount ("uploads"), NOT a non-existent "inputs" path.
SURFACE_INPUTS = SURFACE_UPLOADS


@runtime_checkable
class Backend(Protocol):
    """The journey verbs a paired test calls against either system.

    Every method raises NotImplementedError in this Protocol's default (a
    Protocol has no bodies to inherit; concrete classes must implement each
    verb). A concrete backend that has no analogue for an authz verb raises
    PocHoleNotEnforced rather than faking a result.
    """

    @property
    def name(self) -> str:
        """Backend id, one of "poc" or "fleet". Used by conftest to pick the

        per-backend expectation column from scenarios.yaml.
        """
        raise NotImplementedError

    def live(self) -> bool:
        """True iff the backend's stack is reachable and testable right now.

        PoC: True when a local Docker daemon answers. Fleet: True ONLY when
        the fleet compose is up AND the runsc runtime is registered (Lima),
        because FUSE/runsc cannot run on a Darwin host. When this returns
        False, conftest skips the backend's cases with a loud reason — it
        never xpasses and never substitutes a mock.
        """
        raise NotImplementedError

    def login(self) -> Any:
        """Bootstrap a user session and return an auth handle.

        Fleet: returns a first-party session cookie (SameSite=None, Secure,
        HttpOnly) obtained after embed-token verification (sig + aud +
        exp<=120s); subsequent verbs carry it. PoC: returns a no-auth handle
        carrying only the chat_id — there is no cookie or token to verify.
        """
        raise NotImplementedError

    def upload(self, surface: str, name: str, data: bytes) -> FileRef:
        """Upload ``data`` as ``name`` onto ``surface`` (SURFACE_INPUTS or

        SURFACE_OUTPUTS) and return the stored FileRef.

        Fleet: an inputs upload lands on the readonly:true mount (dir 0555 /
        file 0444) via F9 / the mount plane; an outputs-surface upload from
        the user side is rejected. PoC: writes the host-bind /data/{chat}/
        uploads (:ro) directory; there is no server-side surface authz, so a
        rejected-surface expectation is a PoC-HOLE the concrete backend
        signals with PocHoleNotEnforced where applicable.
        """
        raise NotImplementedError

    def run_agent(self, prompt: str) -> ExecResult:
        """Drive the agent to perform work (e.g. write report.docx).

        Fleet: the agent runs in the gVisor guest and writes the FUSE
        /mnt/user-data/outputs surface. PoC: the agent runs in the per-chat
        container and writes the host-bind outputs directory. Returns the
        exec-shaped result of the agent turn; the produced artifact is then
        observed via list_files / download.
        """
        raise NotImplementedError

    def exec(self, argv: list[str]) -> ExecResult:
        """Run ``argv`` inside the guest / container and return its result.

        Fleet: POST /v1alpha/sessions/exec over the gateway mTLS plane with
        the session_hint; stdout arrives base64 (decoded into ExecResult).
        PoC: exec via the MCP bash tool / docker exec into the per-chat
        container. Used by isolation and read-only probes (C2, C5, D4, D5).
        """
        raise NotImplementedError

    def exec_sh(self, script: str) -> ExecResult:
        """Run a ``/bin/sh -c <script>`` inside the guest, backend-correctly.

        The single chokepoint for shell-script execs. It exists because the
        two substrates need DIFFERENT argv for the same script and getting it
        wrong is a silent vacuity, not a loud failure:

        - Fleet (the demo guest ``ocu-guest:assembled-demo``) is a static
          busybox with NO ``/bin/sh`` and no coreutils on PATH. A bare
          ``["sh", "-c", ...]`` or ``["/bin/sh", "-c", ...]`` is ENOENT / exit
          127 there, which makes a negative assertion ("no leak found", "write
          refused") pass for the WRONG reason. Every applet must be invoked
          through ``/bin/busybox`` exactly as deploy/fleet/storage-chain-demo.sh
          and exec-demo.sh do, so the script actually runs.
        - PoC (the per-chat Ubuntu container) has a real ``/bin/sh`` and a
          normal userland, so the script runs as-is.

        Concrete backends implement this by prefixing per substrate. Tests MUST
        route every shell exec through here, never a raw ``exec(["sh", ...])``
        or ``exec(["python3", ...])`` — a meta-guard test greps the suite's own
        files to enforce it (a code-read cannot catch an ENOENT that only
        surfaces at run time).
        """
        raise NotImplementedError

    def list_files(self, scope: str) -> list[FileRef]:
        """List the files visible to ``scope`` and return them as FileRefs.

        Fleet: F9 /v1/files, cursor-paginated, returning opaque scope-bound
        file_ids; a foreign scope returns none of this scope's files. PoC:
        GET /api/outputs/{chat_id}; any caller with the chat_id sees its
        files (the cross-scope hole D1/B2 exercises).
        """
        raise NotImplementedError

    def download(self, file_id: str) -> DownloadResult:
        """Fetch the bytes for ``file_id`` and return a DownloadResult.

        Fleet: the three-axis authz (scope + read + downloadable) gates the
        byte path; a downloadable=false file returns refused=True with no
        bytes to the browser. PoC: GET /files/{chat}/{file} streams bytes
        with no authz beyond the chat_id scoping.
        """
        raise NotImplementedError

    def preview(self, file_id: str) -> DownloadResult:
        """Render ``file_id`` for in-session preview (not download).

        Fleet: preview renders in-session even for downloadable=false, but the
        byte-to-browser path stays refused — the preview-not-download exfil
        control (D6/G6). PoC: has no preview-vs-download distinction; the
        concrete backend raises PocHoleNotEnforced so a [PoC-HOLE] scenario
        records the missing boundary.
        """
        raise NotImplementedError

    def create_session(self, image: Optional[str] = None) -> SessionRef:
        """Create a sandbox session, optionally pinning ``image``.

        Fleet: POST /v1alpha/sessions with a session_hint; an empty image
        resolves control's DEFAULT image (image ENTRYPOINT metadata is NOT
        trusted — the #94 bug), an off-allow-list image is denied, and a row
        is reserved against the tier quota. PoC: docker run of any image,
        unbounded — the concrete backend returns a SessionRef but there is no
        allow-list or quota to enforce (the A6/E7 hole).
        """
        raise NotImplementedError

    def get_session(self, key: str) -> SessionRef:
        """Fetch the current state of session ``key``.

        Fleet: GET /v1alpha/sessions/{key}; the row is durable in Postgres and
        survives a control restart, and a never-created key returns 404. PoC:
        reads the in-memory container map, which is lost on restart (the E4
        contrast).
        """
        raise NotImplementedError

    def revoke_all(self) -> None:
        """Operator kill-switch: deny every session and every new create.

        Fleet: POST /v1alpha/revoke/all over the operator UDS (SO_PEERCRED).
        PoC: has no kill-switch — the concrete backend raises
        PocHoleNotEnforced so the [PoC-HOLE] E2 scenario records the absence.
        """
        raise NotImplementedError

    def resume_all(self) -> None:
        """Operator resume: allow new sessions again after revoke_all().

        Fleet: POST /v1alpha/resume/all over the operator UDS; pre-revoke
        sessions stay denied (resume does not un-revoke). PoC: raises
        PocHoleNotEnforced (no kill-switch, so nothing to resume).
        """
        raise NotImplementedError
