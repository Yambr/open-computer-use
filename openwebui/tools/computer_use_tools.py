# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
title: Computer Use Tools
author: OpenWebUI Implementation
version: 4.0.0

Thin MCP client proxy to computer-use-orchestrator. All config lives server-side.
Only ORCHESTRATOR_URL + MCP_API_KEY needed — everything else is auto.

Container naming: owui-chat-{chat_id}

REQUIRED SETUP:
- Tool ID MUST be "ai_computer_use" for system prompt injection to work
- Companion filter "Computer Use Filter" (computer_link_filter.py) must be installed and enabled
"""

import asyncio
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import timedelta
from typing import Callable, Awaitable, Optional, List, Annotated
from pydantic import BaseModel, Field


# Client HTTP timeouts (server controls actual command timeout)
CLIENT_HTTP_TIMEOUT = 660       # 11 min > server's 600s COMMAND_TIMEOUT
SUB_AGENT_CLIENT_TIMEOUT = 3660 # 61 min > server's 3600s SUB_AGENT_TIMEOUT


# Every error string the wrapper produces starts with one of these prefixes.
# The outer per-tool wrappers use _looks_like_error() to decide whether to
# emit status="error" — a single source of truth so a new error class added
# below doesn't silently leave the UI green.
_ERROR_PREFIXES = (
    "[CONFIG ERROR]",
    "[NETWORK ERROR]",
    "[MCP TRANSPORT ERROR]",
    "[UNEXPECTED ERROR]",
    "[TOOL ERROR]",
    "[Timeout",
    "[Error",
    "Error:",
)


def _looks_like_error(s: str) -> bool:
    if not isinstance(s, str):
        return False
    return any(s.startswith(p) for p in _ERROR_PREFIXES)


# ============================================================================
# MCP Streamable HTTP Client
# ============================================================================

class _MCPClient:
    """MCP Streamable HTTP client for computer-use-orchestrator."""

    # Health-check cache TTL. Long enough that a busy chat doesn't pay a
    # GET /health on every tool call; short enough that a freshly-restarted
    # orchestrator is detected within ~30s.
    _HEALTH_TTL_SECONDS = 30.0
    _HEALTH_TIMEOUT_SECONDS = 3.0

    def __init__(self, orchestrator_url: str, mcp_api_key: str = ""):
        base = orchestrator_url.rstrip("/")
        self.base_url = base
        self.mcp_url = f"{base}/mcp"
        self.health_url = f"{base}/health"
        self.api_key = mcp_api_key
        # (checked_at, ok, err_str) — None on cold start.
        self._last_health: Optional[tuple] = None

    def _check_health_sync(self) -> tuple[bool, str]:
        """Blocking probe of BOTH /health AND /mcp. Returns (ok, err_string).

        We hit /mcp too because the failure mode that bit us in production was
        exactly: /health returns 200 (FastAPI is up), but /mcp returns 500
        ("Task group is not initialized") because the lifespan swallowed an
        ImportError and never entered session_manager.run(). A /health-only
        probe would have called everything green and let the cancel-scope
        crash propagate as silent empty output.

        Cached for _HEALTH_TTL_SECONDS so the AI doesn't pay two round-trips
        on every tool call when the server is healthy. Cache stores the
        failure verdict too, so a known-bad server short-circuits."""
        now = time.monotonic()
        if self._last_health is not None:
            checked_at, ok, err = self._last_health
            if (now - checked_at) < self._HEALTH_TTL_SECONDS:
                return ok, err

        # 1) GET /health — fastest fail for "container down / wrong URL".
        ok, err = self._http_probe_get(self.health_url)
        if not ok:
            self._last_health = (now, False, f"GET /health -> {err}")
            return False, self._last_health[2]

        # 2) POST /mcp initialize — catches "FastAPI up but MCP broken".
        ok, err = self._http_probe_mcp_initialize()
        if not ok:
            self._last_health = (now, False, f"POST /mcp -> {err}")
            return False, self._last_health[2]

        self._last_health = (now, True, "")
        return True, ""

    def _http_probe_get(self, url: str) -> tuple[bool, str]:
        """GET probe with the standard error-message normalization."""
        try:
            req = urllib.request.Request(url, method="GET")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urllib.request.urlopen(req, timeout=self._HEALTH_TIMEOUT_SECONDS) as resp:
                if 200 <= resp.status < 300:
                    return True, ""
                return False, f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return False, f"{type(e).__name__}: {getattr(e, 'reason', e)}"
        except (TimeoutError, OSError) as e:
            return False, f"{type(e).__name__}: {e}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def _http_probe_mcp_initialize(self) -> tuple[bool, str]:
        """POST /mcp with a minimal initialize. Verifies session_manager is live."""
        body = (
            b'{"jsonrpc":"2.0","id":1,"method":"initialize",'
            b'"params":{"protocolVersion":"2024-11-05","capabilities":{},'
            b'"clientInfo":{"name":"preflight","version":"1.0"}}}'
        )
        req = urllib.request.Request(
            self.mcp_url, method="POST", data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "X-Chat-Id": "preflight",
            },
        )
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self._HEALTH_TIMEOUT_SECONDS) as resp:
                if 200 <= resp.status < 300:
                    return True, ""
                return False, f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            # 401/403 means the endpoint is up — auth is mismatched, not a
            # broken server. That's surface-able by the actual MCP call later.
            if e.code in (401, 403):
                return True, ""
            return False, f"HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return False, f"{type(e).__name__}: {getattr(e, 'reason', e)}"
        except (TimeoutError, OSError) as e:
            return False, f"{type(e).__name__}: {e}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def _config_error_message(self, err: str) -> str:
        """Build the [CONFIG ERROR] string the AI receives when /health fails.

        The message is written to be useful to BOTH the end-user (who reads
        chat) and to a downstream AI model that sees the tool result. It
        names the URL it tried, the underlying error, the most likely fix,
        and how to verify."""
        return (
            f"[CONFIG ERROR] Cannot use computer-use-server at {self.base_url}.\n"
            f"  Pre-flight: {err}\n"
            f"  Likely causes:\n"
            f"    1. The orchestrator container is not running:\n"
            f"         docker compose -f docker-compose.yml up -d computer-use-server\n"
            f"    2. /health is up but /mcp returns 500 — lifespan failed to start the\n"
            f"       MCP session manager. Check `docker logs computer-use-server` for ImportError.\n"
            f"  Verify after fix:\n"
            f"    curl -fsS {self.health_url}     # should return {{\"status\":\"healthy\"}}\n"
            f"    ./tests/test-mcp-endpoint-live.sh {self.base_url}\n"
            f"  Tool ORCHESTRATOR_URL Valve currently points at: {self.base_url}\n"
            f"  This URL must be reachable from inside the open-webui container.\n"
            f"  Cached for {int(self._HEALTH_TTL_SECONDS)}s; a server restart will be picked up automatically."
        )

    def build_headers(
        self,
        chat_id: str,
        user_email: str = "",
        user_name: str = "",
    ) -> dict:
        """Build HTTP headers — only per-request user context."""
        headers = {"X-Chat-Id": chat_id}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if user_email:
            headers["X-User-Email"] = user_email
        if user_name:
            headers["X-User-Name"] = urllib.parse.quote(user_name, safe="")
        return headers

    def _create_session(self, headers: dict, timeout: int):
        """Create MCP client session context manager."""
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession

        class _SessionContext:
            def __init__(self, url, headers, timeout):
                self.url = url
                self.headers = headers
                self.timeout = timeout
                self._transport_cm = None
                self._session_cm = None
                self._session = None

            async def __aenter__(self):
                self._transport_cm = streamablehttp_client(
                    self.url,
                    headers=self.headers,
                    sse_read_timeout=timedelta(seconds=self.timeout + 60),
                )
                read, write, _ = await self._transport_cm.__aenter__()
                self._session_cm = ClientSession(read, write)
                self._session = await self._session_cm.__aenter__()
                await self._session.initialize()
                return self._session

            async def __aexit__(self, *args):
                if self._session_cm:
                    await self._session_cm.__aexit__(*args)
                if self._transport_cm:
                    await self._transport_cm.__aexit__(*args)

        return _SessionContext(self.mcp_url, headers, timeout)

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        headers: dict,
        timeout: int,
        event_emitter: Callable = None,
        operation_name: str = "",
    ) -> str:
        """Call MCP tool via Streamable HTTP with SSE progress.

        Failure-mode contract: on ANY failure path this method returns a
        string with one of the _ERROR_PREFIXES. Outer wrappers detect that
        and emit status="error" so the chat UI shows red. We never return
        empty / ambiguous results that the AI could mistake for success.
        """
        async def _emit_error(description: str):
            if event_emitter:
                try:
                    await event_emitter({"type": "status", "data": {
                        "description": description,
                        "status": "error",
                        "done": True,
                    }})
                except Exception:
                    pass

        # Pre-flight reachability check. Without this, a missing server
        # (DNS fail / connection refused) lands us inside the MCP SDK,
        # which raises a confusing `RuntimeError: Attempted to exit cancel
        # scope in a different task` from __aexit__ — the actual failure
        # gets buried and the wrapper returns either "[No output]" or a
        # cryptic string. Pre-flight returns a clear actionable message
        # before any of that machinery runs.
        ok, health_err = await asyncio.to_thread(self._check_health_sync)
        if not ok:
            await _emit_error("Computer Use server unreachable")
            return self._config_error_message(health_err)

        async def on_progress(progress, total, message):
            if event_emitter:
                display_msg = message or f"{tool_name}: working..."
                try:
                    await event_emitter({
                        "type": "status",
                        "data": {
                            "description": display_msg,
                            "status": "in_progress",
                            "done": False,
                        }
                    })
                except Exception:
                    pass

        async def _execute():
            async with self._create_session(headers, timeout) as session:
                result = await session.call_tool(
                    tool_name, arguments,
                    progress_callback=on_progress,
                    read_timeout_seconds=timedelta(seconds=timeout + 30),
                )
                return self._extract_text(result)

        try:
            return await asyncio.wait_for(_execute(), timeout=timeout + 60)
        except asyncio.TimeoutError:
            await _emit_error(f"Timeout after {timeout}s")
            return (
                f"[Timeout after {timeout}s] Operation did not complete within the client timeout. "
                f"Check `docker logs computer-use-server` to see whether the orchestrator is still working."
            )
        except (ConnectionError, OSError) as e:
            # Invalidate the health cache so the next call re-probes
            # immediately rather than waiting out the TTL.
            self._last_health = None
            await _emit_error("Network error reaching orchestrator")
            return (
                f"[NETWORK ERROR] {type(e).__name__}: {e}\n"
                f"  The orchestrator at {self.base_url} accepted the health check but the MCP "
                f"call dropped its connection. It may have just crashed or been restarted.\n"
                f"  Check: docker logs computer-use-server"
            )
        except RuntimeError as e:
            # The mcp SDK raises RuntimeError("Attempted to exit cancel scope ...")
            # when the streamable-HTTP transport collapses mid-call. Surface it
            # as a transport-layer issue, not a generic crash, so the AI knows
            # the issue is the connection rather than the tool's logic.
            self._last_health = None
            await _emit_error("MCP transport error")
            return (
                f"[MCP TRANSPORT ERROR] {e}\n"
                f"  The MCP session was killed mid-call. Likely causes: orchestrator "
                f"crashed, container restarted, or the MCP SDK version on the server "
                f"and client are incompatible.\n"
                f"  Check: docker logs computer-use-server"
            )
        except Exception as e:
            import traceback
            await _emit_error(f"Unexpected error: {type(e).__name__}")
            tb = traceback.format_exc()
            return (
                f"[UNEXPECTED ERROR] {type(e).__name__}: {e}\n"
                f"  This was not classified as a known failure mode. Server-side "
                f"traceback (truncated to 2000 chars; full trace in open-webui logs):\n"
                f"{tb[:2000]}"
            )

    @staticmethod
    def _extract_text(result) -> str:
        """Extract text from MCP tool result.

        Distinguishes three cases the old version conflated under "[No output]":
          1. result is None or missing — session died before producing one.
          2. result.isError is True — server-side tool raised.
          3. content is empty — legitimate empty stdout/stderr from a
             successful command (e.g. `true`, `mkdir -p existing-dir`).

        The phrasing of case 3 is deliberate: an AI reading "[No output]"
        often concludes the tool is broken. "[Command produced no output.
        Exit was successful — this is not an error.]" blocks that misread.
        """
        if result is None:
            return (
                "[Error] MCP returned no result object — the session may have "
                "died between request and response. Retry the call; if it "
                "happens again, check `docker logs computer-use-server`."
            )

        is_error = bool(getattr(result, "isError", False))

        content = getattr(result, "content", None)
        if not content:
            if is_error:
                return (
                    "[TOOL ERROR] Server-side tool raised an exception with no "
                    "message. Check `docker logs computer-use-server` for the "
                    "traceback."
                )
            return (
                "[Command produced no output. Exit was successful — this is "
                "not an error. If you expected output, the command may have "
                "written to a file instead of stdout.]"
            )

        parts = []
        for item in content:
            if hasattr(item, "text"):
                parts.append(item.text)

        if not parts:
            return (
                "[Empty content blocks — the server returned content but no "
                "text fields. This usually means a binary payload that this "
                "client cannot render, or an SDK shape change.]"
            )

        joined = "\n".join(parts)
        if is_error:
            # Prepend the prefix so outer wrappers + UI flag this as error
            # even when the server-side tool produced text alongside the
            # exception.
            return f"[TOOL ERROR] {joined}"
        return joined


def _get_user_mcp_server_names(request, user_id: str = "") -> list:
    """Extract MCP server names available to the user from OpenWebUI config.

    Reads request.app.state.config.TOOL_SERVER_CONNECTIONS, filters by type=="mcp"
    and user access_control, returns server names (last URL path segment).
    """
    if not request or not hasattr(request, "app"):
        return []
    try:
        connections = request.app.state.config.TOOL_SERVER_CONNECTIONS
    except Exception:
        return []

    names = []
    for server in connections:
        if server.get("type") != "mcp":
            continue

        # Access control check: if access_control is set, user must be in read list
        ac = server.get("access_control", {})
        if ac:
            read_group = ac.get("read", {})
            user_ids = read_group.get("user_ids", [])
            group_ids = read_group.get("group_ids", [])
            if user_ids or group_ids:
                if user_id and user_id not in user_ids:
                    continue

        url = server.get("url", "")
        if not url:
            continue
        # Extract server name from URL: https://api.example.com/mcp/confluence → confluence
        name = url.rstrip("/").rsplit("/", 1)[-1]
        if name and name != "mcp":
            names.append(name)

    return names


# Custom type for view_range
ViewRange = Annotated[
    Optional[List[int]],
    Field(
        default=None,
        min_length=2,
        max_length=2,
        description="Optional line range for text files. Format: [start_line, end_line] where lines are indexed starting at 1. Use [start_line, -1] to view from start_line to the end of the file. When not provided, the entire file is displayed, truncating from the middle if it exceeds 16,000 characters (showing beginning and end)."
    )
]


class Tools:
    class Valves(BaseModel):
        ORCHESTRATOR_URL: str = Field(
            default="http://computer-use-server:8081",
            description="Internal URL of the Computer Use orchestrator (MCP endpoint + file uploads). Must be reachable from inside the Open WebUI container."
        )
        MCP_API_KEY: str = Field(
            default="",
            description="Bearer token for computer-use-orchestrator /mcp endpoint authentication"
        )
        DEBUG_LOGGING: bool = Field(
            default=False,
            description="Enable verbose debug logging"
        )

    def __init__(self):
        self.valves = self.Valves()
        self.file_handler = True
        self.citation = True
        self._mcp_client = None
        # Track the (url, api_key) tuple the current client was built for —
        # invalidate if either changes so edits to MCP_API_KEY in Valves take
        # effect without a process restart.
        self._mcp_client_config: tuple[str, str] | None = None

    @property
    def mcp_client(self) -> _MCPClient:
        """Lazy MCP client — recreated when valves change."""
        url = self.valves.ORCHESTRATOR_URL
        config = (url, self.valves.MCP_API_KEY)
        if self._mcp_client is None or self._mcp_client_config != config:
            self._mcp_client = _MCPClient(url, self.valves.MCP_API_KEY)
            self._mcp_client_config = config
            print(f"[MCP] Client initialized: {self._mcp_client.mcp_url}")
        return self._mcp_client

    # =========================================================================
    # Helpers
    # =========================================================================

    def _build_mcp_headers(self, chat_id: str, __user__: dict = None, request=None) -> dict:
        """Build HTTP headers — per-request user context + MCP server names."""
        user_email = __user__.get("email", "") if __user__ else ""
        user_name = __user__.get("name", "") if __user__ else ""
        headers = self.mcp_client.build_headers(
            chat_id=chat_id,
            user_email=user_email,
            user_name=user_name,
        )
        if request:
            try:
                user_id = __user__.get("id", "") if __user__ else ""
                names = _get_user_mcp_server_names(request, user_id)
                if names:
                    headers["X-Mcp-Servers"] = ",".join(names)
            except Exception:
                pass
        return headers

    async def _sync_files_if_needed(self, chat_id: str, command_or_path: str, __files__: list = None):
        """Sync uploaded files to computer-use-orchestrator if command/path references uploads."""
        uploads_path = "/mnt/user-data/uploads"
        needs_files = uploads_path in command_or_path or "uploads/" in command_or_path
        if not needs_files:
            return
        if __files__:
            try:
                sync_result = await asyncio.to_thread(
                    _sync_uploaded_files, self.valves.ORCHESTRATOR_URL, chat_id, __files__,
                    debug=self.valves.DEBUG_LOGGING
                )
                if sync_result.get("synced", 0) > 0:
                    print(f"Synced {sync_result['synced']} file(s)")
            except Exception as e:
                print(f"[SYNC] Error: {e}")

    async def _run_tool(
        self,
        tool_name: str,
        args: dict,
        chat_id: str,
        emitter: Optional[Callable[[dict], Awaitable[None]]],
        request,
        __user__: Optional[dict],
        in_progress_desc: str,
        ok_desc: str,
        err_desc: str,
        timeout: int = CLIENT_HTTP_TIMEOUT,
    ) -> str:
        """One transport-aware MCP call with consistent SSE status events.

        Every per-tool wrapper (bash_tool/str_replace/create_file/view/sub_agent)
        funnels through here. Without this helper each wrapper duplicated:
          - the in_progress emit before the call
          - the try/except + final emit
          - the _looks_like_error → status decision
          - the wrapper-crash error string
        and they drifted (str_replace used `"error" in result.lower()[:20]` which
        false-positives on "errors fixed: 0", view only matched "Error:", etc).
        """
        async def emit(description: str, status: str, done: bool):
            if not emitter:
                return
            try:
                await emitter({"type": "status", "data": {
                    "description": description, "status": status, "done": done,
                }})
            except Exception:
                pass

        await emit(in_progress_desc, "in_progress", False)
        try:
            headers = self._build_mcp_headers(chat_id, __user__, request=request)
            result = await self.mcp_client.call_tool(
                tool_name, args, headers=headers, timeout=timeout,
                event_emitter=emitter,
            )
            is_err = _looks_like_error(result)
            await emit(err_desc if is_err else ok_desc, "error" if is_err else "complete", True)
            return result
        except Exception as e:
            await emit("Execution error", "error", True)
            return f"[Error] {tool_name} wrapper crashed: {type(e).__name__}: {e}"

    # =========================================================================
    # Tool methods — delegate to computer-use-orchestrator via MCP Streamable HTTP
    # =========================================================================

    async def bash_tool(
        self,
        command: str,
        description: str,
        __event_emitter__: Callable[[dict], Awaitable[None]] = None,
        __metadata__: dict = None,
        __user__: dict = None,
        __files__: Optional[List[dict]] = None,
        __request__=None,
    ) -> str:
        """
        Run a bash command in the container

        :param command: Bash command to run in container
        :param description: Why I'm running this command
        :return: Command output (stdout/stderr)
        """
        chat_id = (__metadata__.get("chat_id") if __metadata__ else None) or "default"
        await self._sync_files_if_needed(chat_id, command, __files__)
        return await self._run_tool(
            "bash_tool", {"command": command, "description": description},
            chat_id, __event_emitter__, __request__, __user__,
            in_progress_desc=description or "Executing bash command...",
            ok_desc="Command completed", err_desc="Command failed",
        )

    async def str_replace(
        self,
        description: str,
        old_str: str,
        path: str,
        new_str: str = "",
        __event_emitter__: Callable[[dict], Awaitable[None]] = None,
        __metadata__: dict = None,
        __user__: dict = None,
        __files__: Optional[List[dict]] = None,
        __request__=None,
    ) -> str:
        """
        Replace a unique string in a file. The string must appear exactly once.

        :param description: Why I'm making this edit
        :param old_str: String to replace (must be unique in file)
        :param new_str: String to replace with (empty to delete)
        :param path: Path to the file to edit
        :return: Success message or error
        """
        chat_id = (__metadata__.get("chat_id") if __metadata__ else None) or "default"
        if old_str == new_str:
            return "Error: old_str and new_str are identical."
        return await self._run_tool(
            "str_replace", {"description": description, "old_str": old_str, "path": path, "new_str": new_str},
            chat_id, __event_emitter__, __request__, __user__,
            in_progress_desc=description or f"Editing {path}...",
            ok_desc="File edited", err_desc="Edit failed",
        )

    async def create_file(
        self,
        description: str,
        file_text: str,
        path: str,
        __event_emitter__: Callable[[dict], Awaitable[None]] = None,
        __metadata__: dict = None,
        __user__: dict = None,
        __files__: Optional[List[dict]] = None,
        __request__=None,
    ) -> str:
        """
        Create a new file with content in the container

        :param description: Why I'm creating this file
        :param file_text: Content to write to the file
        :param path: Path to the file to create
        :return: Success message or error
        """
        chat_id = (__metadata__.get("chat_id") if __metadata__ else None) or "default"
        return await self._run_tool(
            "create_file", {"description": description, "file_text": file_text, "path": path},
            chat_id, __event_emitter__, __request__, __user__,
            in_progress_desc=description or f"Creating {path}...",
            ok_desc="File created", err_desc="Creation failed",
        )

    async def view(
        self,
        description: str,
        path: str,
        view_range: ViewRange = None,
        __event_emitter__: Callable[[dict], Awaitable[None]] = None,
        __metadata__: dict = None,
        __user__: dict = None,
        __files__: Optional[List[dict]] = None,
        __request__=None,
    ) -> str:
        """
        View text files, directory listings, or binary file info.

        :param description: Why I need to view this
        :param path: Absolute path to file or directory
        :param view_range: Optional [start_line, end_line]. Use [start, -1] for to-end.
        :return: File contents, directory listing, or error message
        """
        chat_id = (__metadata__.get("chat_id") if __metadata__ else None) or "default"
        await self._sync_files_if_needed(chat_id, path, __files__)
        args = {"description": description, "path": path}
        if view_range:
            args["view_range"] = view_range
        return await self._run_tool(
            "view", args,
            chat_id, __event_emitter__, __request__, __user__,
            in_progress_desc=description or f"Reading {path}...",
            ok_desc="Read complete", err_desc="Read failed",
        )

    async def sub_agent(
        self,
        task: str,
        description: str,
        model: str = "sonnet",
        max_turns: int = 25,
        mode: str = "act",
        working_directory: str = "/home/assistant",
        resume_session_id: str = "",
        __event_emitter__: Callable[[dict], Awaitable[None]] = None,
        __metadata__: dict = None,
        __user__: dict = None,
        __files__: Optional[List[dict]] = None,
        __request__=None,
    ) -> str:
        """
        Delegate complex, multi-step tasks to an autonomous sub-agent.

        :param task: Structured task description
        :param description: Why you are delegating this task
        :param model: AI model - "sonnet" (fast, default) or "opus" (powerful)
        :param max_turns: Max iterations, default 25 (raise to 50-80 for large multi-file refactors)
        :param mode: "act" (execute) or "plan" (plan only)
        :param working_directory: Work dir, default /home/assistant
        :param resume_session_id: Session ID to resume (from previous result)
        :return: Sub-agent's response with results, cost, turn count, session_id
        """
        chat_id = (__metadata__.get("chat_id") if __metadata__ else None) or "default"
        if __files__:
            await self._sync_files_if_needed(chat_id, "/mnt/user-data/uploads", __files__)
        args = {
            "task": task, "description": description, "model": model,
            "max_turns": max_turns, "working_directory": working_directory,
        }
        if resume_session_id:
            args["resume_session_id"] = resume_session_id
        return await self._run_tool(
            "sub_agent", args,
            chat_id, __event_emitter__, __request__, __user__,
            in_progress_desc=description or f"Starting sub-agent ({model})...",
            ok_desc="Sub-agent completed", err_desc="Sub-agent failed",
            timeout=SUB_AGENT_CLIENT_TIMEOUT,
        )


# ============================================================================
# File sync helper (HTTP — no SSH needed)
# ============================================================================

def _sync_uploaded_files(orchestrator_url: str, chat_id: str, files: list, debug: bool = False) -> dict:
    """Sync uploaded files from OpenWebUI to computer-use-orchestrator via HTTP."""
    import requests
    import hashlib

    if not files:
        return {"synced": 0, "skipped": 0, "errors": 0}

    try:
        manifest_url = f"{orchestrator_url}/api/uploads/{chat_id}/manifest"
        response = requests.get(manifest_url, timeout=5)
        response.raise_for_status()
        remote_manifest = response.json()
    except Exception:
        remote_manifest = {}

    synced, skipped, errors = 0, 0, 0

    for file_info in files:
        temp_file_path = None
        try:
            source_path = file_info.get("file", {}).get("path") if isinstance(file_info.get("file"), dict) else file_info.get("path")
            filename = file_info.get("name") or (os.path.basename(source_path) if source_path else "unknown")
            filename = os.path.basename(filename)

            if not source_path:
                errors += 1
                continue

            try:
                from open_webui.storage.provider import Storage
                local_file_path = Storage.get_file(source_path)
                if local_file_path != source_path:
                    temp_file_path = local_file_path
                source_path = local_file_path
            except Exception:
                errors += 1
                continue

            if not os.path.exists(source_path):
                errors += 1
                continue

            md5_hash = hashlib.md5()
            with open(source_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    md5_hash.update(chunk)
            local_md5 = md5_hash.hexdigest()

            if remote_manifest.get(filename) == local_md5:
                skipped += 1
                continue

            upload_url = f"{orchestrator_url}/api/uploads/{chat_id}/{filename}"
            with open(source_path, "rb") as f:
                files_data = {"file": (filename, f, "application/octet-stream")}
                resp = requests.post(upload_url, files=files_data, timeout=30)
                resp.raise_for_status()
            synced += 1
        except Exception:
            errors += 1
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass

    return {"synced": synced, "skipped": skipped, "errors": errors}
