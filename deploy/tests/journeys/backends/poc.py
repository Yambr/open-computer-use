# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""PoC backend: Open WebUI + computer-use-server (FastAPI), plain Docker.

Targets the real PoC surface described by computer-use-server/app.py:

    GET  /api/outputs/{chat_id}              list outputs
    GET  /files/{chat_id}/{filename}         download one output
    GET  /files/{chat_id}/archive            zip all outputs
    POST /api/uploads/{chat_id}/{filename}   upload into the :ro inputs bind
    GET  /api/uploads/{chat_id}/list         list uploaded inputs

There is NO auth. The chat_id is the only scoping: any caller with a chat_id
reads that chat's files, and the host (via the /data host-bind) sees every
file. The absence of authz, egress control, session tokens, and audit is the
finding the [PoC-HOLE] scenarios record — so where a verb names one of those
boundaries this backend raises PocHoleNotEnforced rather than faking a result.

If the PoC stack is not up, a verb raises BackendUnavailable; conftest turns
that into a loud skip. Nothing here mocks a running system.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    import requests

from .base import (
    Backend,
    BackendUnavailable,
    DownloadResult,
    ExecResult,
    FileRef,
    PocHoleNotEnforced,
    SessionRef,
    SURFACE_INPUTS,
    SURFACE_OUTPUTS,
)

# The computer-use-server FastAPI base. Override for a non-default checkout.
POC_SERVER_URL = os.getenv("POC_SERVER_URL", "http://127.0.0.1:8000")
# The chat_id used as the default scope for single-scope journeys. A second
# scope (for cross-scope keystones) is derived by suffixing "-b".
POC_CHAT_ID = os.getenv("POC_CHAT_ID", "journey-poc")
_HTTP_TIMEOUT_S = float(os.getenv("POC_HTTP_TIMEOUT_S", "20"))


def _requests():
    """Import the `requests` library lazily.

    Kept out of module load so pytest can collect this file (and the fleet
    cases) even where `requests` is not installed. A PoC verb that needs HTTP
    calls this and raises BackendUnavailable if the dependency is absent —
    conftest turns that into a loud skip, never a mock.
    """
    try:
        import requests  # noqa: PLC0415 - deliberate lazy import

        return requests
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise BackendUnavailable(
            "the `requests` library is required for the PoC HTTP verbs; "
            "install it in the test env"
        ) from exc


class PocBackend(Backend):
    """Concrete PoC backend. Real HTTP against computer-use-server."""

    def __init__(self, chat_id: str = POC_CHAT_ID, base_url: str = POC_SERVER_URL):
        self._chat_id = chat_id
        self._base = base_url.rstrip("/")
        self._session_obj = None

    @property
    def _session(self):
        if self._session_obj is None:
            self._session_obj = _requests().Session()
        return self._session_obj

    @property
    def name(self) -> str:
        return "poc"

    # -- availability --------------------------------------------------

    def live(self) -> bool:
        """True iff the actual PoC surface is up, not merely a Docker daemon.

        A reachable Docker daemon alone is NOT the PoC — gating on it lets a
        [poc] case proceed and hard-fail with "No such container:
        owui-chat-{chat_id}" instead of a clean loud-skip. So probe, in order
        (any miss short-circuits, never raises so conftest skips cleanly):

          1. docker CLI present and the daemon answers.
          2. EITHER the per-chat container (owui-chat-{chat_id}) exists OR the
             computer-use-server FastAPI answers on its files/outputs route.

        The two-of-(container|server) OR is deliberate: some journeys drive the
        container directly (docker exec), others hit the server; the PoC is
        "live enough to test" when at least one real surface answers. A down PoC
        stack returns False -> conftest loud-skip with a reason, never a green.
        """
        docker = shutil.which("docker")
        if not docker:
            return False
        try:
            proc = subprocess.run(
                [docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if proc.returncode != 0:
            return False
        # Probe the ACTUAL PoC surface: the per-chat container OR the server.
        return self._container_present(docker) or self._server_answers()

    def _container_present(self, docker: str) -> bool:
        """True iff the per-chat container owui-chat-{chat_id} exists.

        Uses `docker inspect` on the real per-chat container name the exec /
        session verbs address, so live() gates on the surface those verbs need.
        Returns False on any error rather than raising.
        """
        cname = self._container(self._chat_id)
        try:
            proc = subprocess.run(
                [docker, "inspect", "--format", "{{.State.Status}}", cname],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0

    def _server_answers(self) -> bool:
        """True iff the computer-use-server FastAPI answers on a real route.

        Hits GET /api/outputs/{chat_id} (a route app.py serves) and treats any
        HTTP response — including a 404 for an empty scope — as "the server is
        up". A transport failure (server down) or a missing `requests` returns
        False, never raises. This never substitutes a mock: it only reports
        whether the real FastAPI surface responded.
        """
        try:
            req = _requests()
        except BackendUnavailable:
            return False
        try:
            resp = req.get(
                self._url(f"/api/outputs/{self._chat_id}"), timeout=5
            )
        except req.RequestException:
            return False
        return resp.status_code < 500

    # -- helpers -------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def _get(self, path: str, **kw: Any) -> "requests.Response":
        req = _requests()
        try:
            return self._session.get(self._url(path), timeout=_HTTP_TIMEOUT_S, **kw)
        except req.RequestException as exc:  # server not up
            raise BackendUnavailable(
                f"PoC server unreachable at {self._base}{path}: {exc}"
            ) from exc

    def _post(self, path: str, **kw: Any) -> "requests.Response":
        req = _requests()
        try:
            return self._session.post(self._url(path), timeout=_HTTP_TIMEOUT_S, **kw)
        except req.RequestException as exc:
            raise BackendUnavailable(
                f"PoC server unreachable at {self._base}{path}: {exc}"
            ) from exc

    def _container(self, chat_id: str) -> str:
        return f"owui-chat-{chat_id}"

    # -- journey verbs -------------------------------------------------

    def login(self) -> Any:
        """No cookie, no token. Returns the chat_id handle only.

        The PoC sets no first-party cookie and verifies no embed token; the
        chat_id alone scopes every call. A1's keystone (strip-cookie -> 401)
        has no PoC analogue, so that boundary is a PoC-HOLE recorded by the
        paired test, not enforced here.
        """
        return {"chat_id": self._chat_id}

    def upload(self, surface: str, name: str, data: bytes) -> FileRef:
        """Upload into the PoC inputs bind via POST /api/uploads.

        The PoC has a single upload target (the :ro uploads bind that maps to
        /mnt/user-data/uploads in the container). There is no server-side
        surface authz, so an outputs-surface upload has no distinct rejection
        path — that missing boundary is the C1 keystone hole; this backend
        signals it with PocHoleNotEnforced.
        """
        if surface == SURFACE_OUTPUTS:
            raise PocHoleNotEnforced(
                "PoC has no server-side outputs-surface upload boundary; "
                "uploads always land in the :ro inputs bind"
            )
        if surface != SURFACE_INPUTS:
            raise ValueError(f"unknown surface: {surface!r}")
        resp = self._post(
            f"/api/uploads/{self._chat_id}/{name}",
            files={"file": (name, data)},
        )
        resp.raise_for_status()
        return FileRef(id=name, name=name, scope=self._chat_id, size=len(data))

    def run_agent(self, prompt: str) -> ExecResult:
        """Not driven headlessly in this scaffold.

        Driving the real OWUI agent turn requires a model and the chat UI; the
        journey tests that need a produced artifact create it via exec() into
        the container's outputs bind (an in-container write is the same end
        state the agent produces). This verb is left for a UI-driving group
        test to implement against the live OWUI; the scaffold does not stub a
        green agent turn.
        """
        raise NotImplementedError(
            "run_agent drives the live OWUI chat UI; implement in the "
            "UI-journey group test, do not stub"
        )

    def exec(self, argv: list[str]) -> ExecResult:
        """docker exec into the per-chat container owui-chat-{chat_id}.

        Used by content and read-only probes. Raises BackendUnavailable if the
        container is not running (conftest -> skip), never a fabricated exit.
        """
        docker = shutil.which("docker")
        if not docker:
            raise BackendUnavailable("docker CLI not found for PoC exec")
        cname = self._container(self._chat_id)
        try:
            proc = subprocess.run(
                [docker, "exec", cname, *argv],
                capture_output=True,
                timeout=_HTTP_TIMEOUT_S,
            )
        except subprocess.SubprocessError as exc:
            raise BackendUnavailable(
                f"PoC container {cname} not execable: {exc}"
            ) from exc
        return ExecResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            denied=False,
        )

    def exec_sh(self, script: str) -> ExecResult:
        """Run ``script`` via ``/bin/sh -c`` inside the per-chat container.

        The PoC container is a normal Ubuntu userland with a real /bin/sh, so
        the script runs as-is over the same docker-exec transport as exec().
        Routes through exec() so a missing container is a BackendUnavailable
        (conftest -> loud skip), never a fabricated exit.
        """
        return self.exec(["/bin/sh", "-c", script])

    def list_files(self, scope: str) -> list[FileRef]:
        """GET /api/outputs/{scope}. Any caller with the chat_id sees these.

        There is no cross-scope boundary: a different scope value simply lists
        that scope's outputs directory. D1 exercises exactly this — the paired
        test records the read-across as the PoC-HOLE it is.
        """
        resp = self._get(f"/api/outputs/{scope}")
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

    def download(self, file_id: str) -> DownloadResult:
        """GET /files/{chat}/{file}. Streams bytes with no authz beyond scope.

        There is no downloadable axis: every file the chat_id can see is
        byte-deliverable. refused is always False on the PoC — the D6/G6
        preview-not-download control has no analogue here.
        """
        resp = self._get(f"/files/{self._chat_id}/{file_id}")
        return DownloadResult(
            status=resp.status_code,
            content_type=resp.headers.get("content-type", ""),
            data=resp.content if resp.status_code == 200 else b"",
            refused=False,
        )

    def preview(self, file_id: str) -> DownloadResult:
        """No preview-vs-download distinction on the PoC.

        Everything downloads, so there is no in-session-only preview path to
        exercise. The D6 [PoC-HOLE] scenario reads this sentinel as the
        missing exfil boundary.
        """
        raise PocHoleNotEnforced(
            "PoC has no preview-vs-download boundary; every file downloads"
        )

    def create_session(self, image: Optional[str] = None) -> SessionRef:
        """The PoC session is the chat itself; docker run is unbounded.

        There is no allow-list and no quota. A session "create" maps to the
        chat_id scope; the A6/E7 hole (any image, no cap) is recorded by the
        paired test. Returns the chat scope as the session key with an
        "active" status — this is a real state (the chat exists), not a
        fabricated success for a boundary that is absent.
        """
        return SessionRef(key=self._chat_id, status="active")

    def get_session(self, key: str) -> SessionRef:
        """PoC session state is the in-memory container map (lost on restart).

        Reports "active" when the per-chat container is running, "released"
        otherwise. There is no durable row; E4 records that contrast.
        """
        docker = shutil.which("docker")
        if not docker:
            raise BackendUnavailable("docker CLI not found for PoC session probe")
        cname = self._container(key)
        proc = subprocess.run(
            [docker, "ps", "--filter", f"name={cname}", "--format", "{{.Names}}"],
            capture_output=True,
            timeout=10,
        )
        running = cname in proc.stdout.decode("utf-8", "replace")
        return SessionRef(key=key, status="active" if running else "released")

    def revoke_all(self) -> None:
        """No kill-switch on the PoC.

        E2 records the absence: there is no operator surface to deny every
        session at once.
        """
        raise PocHoleNotEnforced("PoC has no operator kill-switch (revoke/all)")

    def resume_all(self) -> None:
        """No kill-switch, so nothing to resume."""
        raise PocHoleNotEnforced("PoC has no operator resume (resume/all)")
