# SPDX-License-Identifier: FSL-1.1-Apache-2.0
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


def _extract_resolve_scope(payload: dict):
    """Pull effective_scope out of a resolve_scope CallToolResult.

    The gateway answers the synthetic resolve_scope tool with a JSON-RPC result
    whose `result.content` carries a single text block; that text is JSON
    {"effective_scope": "<base>-<hex>"}. Returns the scope string (possibly the
    empty string when derivation is off), or None when the shape is not a
    resolvable CallToolResult (a real miss, distinct from an explicit-empty
    scope). Never raises.
    """
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                inner = json.loads(text)
            except (ValueError, TypeError):
                continue
            if isinstance(inner, dict) and "effective_scope" in inner:
                scope = inner.get("effective_scope")
                if isinstance(scope, str):
                    return scope
    return None


# ============================================================================
# MCP Streamable HTTP Client
# ============================================================================

def _require_http_scheme(url: str) -> None:
    """Refuse an orchestrator URL that urlopen would not fetch over the network.

    urllib honours ``file://``, ``ftp://`` and ``data://``, so a misconfigured
    Valve turns a health probe or a scope resolve into a local-file read whose
    result is then reported as if it had come from the orchestrator. The
    resolve path is the dangerous one: it catches every exception and degrades
    to the base scope, so a bad scheme there fails silently rather than loudly.

    Shared by every construction path — the MCP client and the direct
    ``_resolve_scope`` request, which does not go through that client. The
    sibling filter (``openwebui/functions/computer_link_filter.py``) enforces
    the same rule at its own urlopen sites.
    """
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise ValueError(
            f"orchestrator URL scheme {scheme!r} is not supported "
            f"(expected http or https)"
        )


class _MCPClient:
    """MCP Streamable HTTP client for computer-use-orchestrator."""

    # Health-check cache TTL. Long enough that a busy chat doesn't pay a
    # GET /health on every tool call; short enough that a freshly-restarted
    # orchestrator is detected within ~30s.
    _HEALTH_TTL_SECONDS = 30.0
    _HEALTH_TIMEOUT_SECONDS = 3.0

    # The MCP protocol version the orchestrator/gateway pins. Streamable-HTTP
    # servers negotiate the version through the MCP-Protocol-Version HTTP header
    # (not the JSON-RPC body); a request that omits the header, or carries a
    # version the server does not accept, is rejected with -32602 "unsupported
    # or missing protocol version" (HTTP 400) BEFORE auth. The manual preflight
    # below must send this exact version — both in the header and in the
    # initialize body — or it 400s and reports the server as broken. The real
    # tool call goes through the MCP SDK, which sets the header itself.
    _MCP_PROTOCOL_VERSION = "2025-06-18"

    def __init__(self, orchestrator_url: str, mcp_api_key: str = ""):
        base = orchestrator_url.rstrip("/")
        _require_http_scheme(base)
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
            '{"jsonrpc":"2.0","id":1,"method":"initialize",'
            '"params":{"protocolVersion":"' + self._MCP_PROTOCOL_VERSION + '",'
            '"capabilities":{},'
            '"clientInfo":{"name":"preflight","version":"1.0"}}}'
        ).encode("utf-8")
        req = urllib.request.Request(
            self.mcp_url, method="POST", data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": self._MCP_PROTOCOL_VERSION,
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
                # D4 image hop: a "view image" surfaces image_url content blocks.
                # Push each rendered image into the chat via the event emitter (a
                # markdown "message" event - the OpenWebUI way to append content
                # to the assistant turn) and keep ONLY a short text marker in the
                # returned string. The raw base64 data URL never enters the model
                # context (it would blow the context window).
                images = self._extract_images(result)
                if images and event_emitter:
                    for data_url in images:
                        try:
                            await event_emitter({
                                "type": "message",
                                "data": {"content": f"\n![image]({data_url})\n"},
                            })
                        except Exception:
                            pass
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

        D4 image hop: image_url content blocks (a "view image") are surfaced to
        the chat separately via the event emitter. This method NEVER returns the
        raw base64 data URL - an image block collapses to a short text marker
        ("[Image: <path> (displayed)]") so the model sees that an image was
        shown without the payload consuming the context window.
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
        image_count = 0
        for item in content:
            if hasattr(item, "text"):
                parts.append(item.text)
                continue
            # An image_url block collapses to a text marker; the raw data URL is
            # deliberately dropped here (it is surfaced via the event emitter).
            marker = _MCPClient._image_marker(item)
            if marker is not None:
                image_count += 1
                parts.append(marker)

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

    @staticmethod
    def _block_image_data_url(item):
        """Return the data URL of an image content block, else None.

        Handles two shapes without importing either SDK's model:
          - OpenAI-style: {"type": "image_url", "image_url": {"url": "data:..."}}
          - MCP-native:   {"type": "image", "data": "<base64>", "mimeType": "..."}
        Accepts both attribute-style (SDK-deserialised objects) and dict-style
        blocks. Any block that is not an image returns None.
        """
        def _get(obj, key):
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        block_type = _get(item, "type")

        # OpenAI-style image_url block.
        image_url = _get(item, "image_url")
        if image_url is not None:
            url = _get(image_url, "url")
            if isinstance(url, str) and url:
                return url

        # MCP-native image block: reconstruct the data URL from data + mimeType.
        if block_type == "image":
            data = _get(item, "data")
            if isinstance(data, str) and data:
                mime = _get(item, "mimeType") or "image/png"
                return f"data:{mime};base64,{data}"

        return None

    @staticmethod
    def _image_marker(item):
        """Return a short text marker for an image block, else None.

        Never includes the base64 payload. If the block carries a filesystem
        path hint (some tools attach one) it is shown, otherwise a generic
        "(displayed)" marker is emitted.
        """
        if _MCPClient._block_image_data_url(item) is None:
            return None
        path = None
        if isinstance(item, dict):
            path = item.get("path") or item.get("filename")
        else:
            path = getattr(item, "path", None) or getattr(item, "filename", None)
        if path:
            return f"[Image: {path} (displayed)]"
        return "[Image (displayed)]"

    @staticmethod
    def _extract_images(result) -> list:
        """Return the data URLs of all image content blocks, in order.

        Used by the emitter path in call_tool; the returned URLs are pushed to
        the chat as markdown, never into the model-facing return string.
        """
        if result is None:
            return []
        content = getattr(result, "content", None)
        if not content:
            return []
        urls = []
        for item in content:
            url = _MCPClient._block_image_data_url(item)
            if url:
                urls.append(url)
        return urls


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
        FILESTORE_URL: str = Field(
            default="https://filestore:7080",
            description="Internal URL of the object-store service's F9 north Files-API, reached over the ocu-north network. Chat attachments are created here (multipart POST /v1/files) so they appear in the guest's read-only /mnt/user-data/uploads view (engine key uploads/<name>). NOT the MCP gateway."
        )
        OCU_FILESYSTEM_ID: str = Field(
            default="fs-fleet",
            description="The BASE attested filesystem scope attachments are written under (X-OCU-Filesystem-Id), compose-seeded by init.sh. With control's -derive-chat-scope on (ADR-0030, D5), the tool resolves a per-chat scope '<base>-<hex>' from the caller-scoped status verb and writes attachments under that isolated scope; the tool never derives the handle locally. Degrades to this base (shared across chats) when derivation is off."
        )
        FILESTORE_CA_CERT: str = Field(
            default="/etc/ocu/ca.pem",
            description="Path to the fleet CA that signs the filestore TLS leaf. requests verifies https://filestore:7080 against it (never verify=False). Empty falls back to system trust."
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
        # D5 per-chat storage scope, resolved once per chat_id from control's
        # caller-scoped status verb and memoised. The tool NEVER derives the
        # scope handle locally; the attested owner form is control-only.
        self._chat_scope_cache: dict[str, str] = {}

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

    def _resolve_chat_scope_sync(self, chat_id: str) -> str:
        """Blocking MCP tools/call to the gateway's resolve_scope tool; returns
        the per-chat effective_scope, degrading to the base OCU_FILESYSTEM_ID.

        Wire: a JSON-RPC tools/call for the synthetic `resolve_scope` tool on the
        SAME MCP endpoint the bash tool speaks to (POST ORCHESTRATOR_URL, bearer +
        MCP-Protocol-Version + X-Chat-Id). The gateway maps X-Chat-Id ->
        session_hint, ensures/creates the session, and returns a CallToolResult
        whose single text content block is JSON {"effective_scope":"<base>-<hex>"}.
        The tool reads that value; it NEVER derives the scope handle locally - the
        attested owner form is control-only (ADR-0030, D5).

        Degrade to the base OCU_FILESYSTEM_ID ONLY on an EXPLICIT empty scope
        (control ran without -derive-chat-scope, so effective_scope is blank) or a
        REAL transport error / JSON-RPC error / unparseable body. A 202-empty or an
        otherwise-successful-but-unusable response is NOT treated as a resolved
        scope - it degrades WITH a visible debug flag, never silently as if the
        base were the attested answer (the review's fake-green). Never raises; the
        upload path must not break on a resolve miss.
        """
        base = self.valves.OCU_FILESYSTEM_ID

        def _degrade_early(reason: object) -> str:
            if self.valves.DEBUG_LOGGING:
                print(f"[SCOPE] resolve_scope miss for chat {chat_id}: {reason} -> base {base}")
            return base

        try:
            _require_http_scheme(self.valves.ORCHESTRATOR_URL)
        except ValueError as exc:
            # This path never raises — the upload must survive a resolve miss —
            # so a bad scheme degrades like any other miss, but visibly.
            return _degrade_early(exc)
        endpoint = self.valves.ORCHESTRATOR_URL.rstrip("/") + "/mcp"
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "resolve_scope", "arguments": {}},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            method="POST",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": _MCPClient._MCP_PROTOCOL_VERSION,
                "X-Chat-Id": chat_id,
            },
        )
        api_key = self.valves.MCP_API_KEY
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")

        def _degrade(reason: str) -> str:
            if self.valves.DEBUG_LOGGING:
                print(f"[SCOPE] resolve_scope miss for chat {chat_id}: {reason} -> base {base}")
            return base

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
        except Exception as e:
            return _degrade(f"transport error {e}")

        # A body-less / empty success (e.g. a 202 from a wire that does not carry a
        # CallToolResult) is a MISS, not a base scope. Flag it; never silent-green.
        if not raw.strip():
            return _degrade(f"empty body (HTTP {status})")
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError) as e:
            return _degrade(f"unparseable body (HTTP {status}): {e}")
        if not isinstance(payload, dict) or "error" in payload:
            return _degrade(f"JSON-RPC error or non-object (HTTP {status})")

        scope = _extract_resolve_scope(payload)
        if scope is None:
            return _degrade(f"no resolvable effective_scope in CallToolResult (HTTP {status})")
        if scope == "":
            # An EXPLICIT empty scope is the derivation-off degrade: real, expected.
            return _degrade("effective_scope is explicitly empty (derive-chat-scope off)")
        return scope

    async def _resolve_chat_scope(self, chat_id: str) -> str:
        """Resolve (and memoise) this chat's storage scope via the status verb.

        Returns the control-derived effective_scope for the chat, or the base
        OCU_FILESYSTEM_ID when derivation is off / the verb is unavailable. The
        result is cached per chat_id so a busy chat pays the round-trip once.
        """
        chat_id = chat_id or "default"
        cached = self._chat_scope_cache.get(chat_id)
        if cached is not None:
            return cached
        scope = await asyncio.to_thread(self._resolve_chat_scope_sync, chat_id)
        self._chat_scope_cache[chat_id] = scope
        return scope

    async def _sync_files_if_needed(
        self, chat_id: str, command_or_path: str, __files__: list = None, emitter=None
    ):
        """Sync uploaded files to computer-use-orchestrator if command/path references uploads."""
        uploads_path = "/mnt/user-data/uploads"
        needs_files = uploads_path in command_or_path or "uploads/" in command_or_path
        if not needs_files:
            return
        if __files__:
            # D5: resolve THIS chat's isolated scope from control's status verb
            # before writing the attachment. When -derive-chat-scope is on the
            # scope is "<base>-<hex>" (distinct per chat); otherwise it degrades
            # to the base OCU_FILESYSTEM_ID (today's shared single-tenant scope).
            # The attachment lands under the resolved scope so the guest's minted
            # Storage-JWT claim keys the same subtree.
            scope = await self._resolve_chat_scope(chat_id)
            try:
                sync_result = await asyncio.to_thread(
                    _sync_uploaded_files,
                    self.valves.FILESTORE_URL,
                    scope,
                    __files__,
                    ca_cert_path=self.valves.FILESTORE_CA_CERT,
                    debug=self.valves.DEBUG_LOGGING,
                )
                if sync_result.get("synced", 0) > 0:
                    print(f"Synced {sync_result['synced']} file(s)")
                # A non-zero errors count means one or more attachments did NOT
                # reach the store, so the guest may read STALE or absent bytes.
                # This MUST be model-visible -- a silent errors count is the exact
                # staleness class D6 exists to kill (a swallowed error re-opens it).
                errors = sync_result.get("errors", 0)
                if errors > 0:
                    warning = (
                        f"WARNING: {errors} chat attachment(s) failed to sync to "
                        "the guest; it may read stale or missing bytes at "
                        "/mnt/user-data/uploads."
                    )
                    print(f"[SYNC] {warning}")
                    if emitter:
                        try:
                            await emitter({
                                "type": "status",
                                "data": {"description": warning, "done": True},
                            })
                        except Exception:
                            pass
            except Exception as e:
                print(f"[SYNC] Error: {e}")
                if emitter:
                    try:
                        await emitter({
                            "type": "status",
                            "data": {
                                "description": (
                                    "WARNING: chat attachment sync failed; the guest "
                                    "may not see the uploaded file(s)."
                                ),
                                "done": True,
                            },
                        })
                    except Exception:
                        pass

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

        Every per-tool wrapper (bash_tool/str_replace/create_file/view)
        funnels through here. Without this helper each wrapper duplicated:
          - the in_progress emit before the call
          - the try/except + final emit
          - the _looks_like_error → status decision
          - the wrapper-crash error string
        and they drifted (str_replace used `"error" in result.lower()[:20]` which
        false-positives on "errors fixed: 0", view only matched "Error:", etc).

        NOTE for new tool wrappers:
          - If your tool needs uploaded files, call `await self._sync_files_if_needed(...)`
            BEFORE delegating here (this helper does NOT take __files__).
          - chat_id is defaulted to "default" if empty/None — server-side
            chat scoping needs a non-empty value.
        """
        # Defense-in-depth: every per-tool wrapper already does
        # `chat_id or "default"`, but if a future wrapper forgets, the
        # server-side X-Chat-Id header would otherwise be empty and the
        # MCP call would silently land in the wrong (or no) chat scope.
        chat_id = chat_id or "default"

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
        await self._sync_files_if_needed(chat_id, command, __files__, emitter=__event_emitter__)
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
        await self._sync_files_if_needed(chat_id, path, __files__, emitter=__event_emitter__)
        args = {"description": description, "path": path}
        if view_range:
            args["view_range"] = view_range
        return await self._run_tool(
            "view", args,
            chat_id, __event_emitter__, __request__, __user__,
            in_progress_desc=description or f"Reading {path}...",
            ok_desc="Read complete", err_desc="Read failed",
        )


# ============================================================================
# File sync helper (HTTP — no SSH needed)
# ============================================================================

# The F9 north Files-API wire is transport-pinned (ADR-0028 / ADR-0025). The
# create route is multipart/form-data with TWO ordered parts read by the
# object-store service's STAGE-0 gate: the "params" JSON FIELD FIRST, then the
# "file" part (filename "upload") streaming the raw bytes. A body whose first
# part is not "params" — or a JSON body — is refused. The scope rides
# authoritatively in the X-OCU-Filesystem-Id header on EVERY request; the
# filesystem_id inside "params" is design-level create-meta only. This mirrors
# the pane BFF F9 client (web/src/lib/objectstore/f9.ts) byte-for-intent.
_F9_FILES_ROUTE = "/v1/files"
_F9_SCOPE_HEADER = "X-OCU-Filesystem-Id"
_F9_MULTIPART_PARAMS_FIELD = "params"
_F9_MULTIPART_FILE_FIELD = "file"
_F9_MULTIPART_FILE_FILENAME = "upload"


def _sync_uploaded_files(
    filestore_url: str,
    filesystem_id: str,
    files: list,
    ca_cert_path: str = "",
    debug: bool = False,
) -> dict:
    """Sync OpenWebUI chat attachments into the guest via the F9 north Files-API.

    Each attachment is created under the attested filesystem scope with a flat
    uploads path ("/<filename>"), so it appears in the guest's flat
    /mnt/user-data view (F9 north-create joins the uploads/ engine subtree). Idempotent
    across turns: an F9 list is fetched once and each candidate is deduped against it.

    Dedup precedence (D6): the F9 FileObject now carries an OPTIONAL "sha256"
    hex field (the engine-computed content digest). When the stored object
    exposes a sha256, an upload is skipped ONLY if the local content sha256
    (streamed in 8192-byte chunks) matches it exactly - so a same-name,
    same-size edit is re-uploaded rather than silently dropped. When the stored
    object has NO sha256 (an older filestore, or a reconcile-minted handle that
    never captured a create-time digest), the client falls back to the legacy
    name + size skip. This is the compat window: correctness improves the moment
    the server surfaces the field, with no client flag day.

    NOTE (single-tenant demo): the whole stand shares one deploy-pinned scope
    (fs-fleet), so uploads are visible across chats. That is a consequence of a
    single filesystem_id, not a bug here; per-chat scope is a future
    control-plane feature.
    """
    import hashlib
    import requests

    if not files:
        return {"synced": 0, "skipped": 0, "errors": 0}

    base_url = filestore_url.rstrip("/")
    # https://filestore:7080 is served with the fleet CA-signed leaf; verify
    # against the mounted CA (never verify=False). Falls back to system trust
    # only when no CA path is configured.
    verify = ca_cert_path if ca_cert_path else True
    scope_headers = {_F9_SCOPE_HEADER: filesystem_id}

    # Fetch the current object list ONCE for dedup (F9 GET /v1/files). Each entry
    # keeps both the size and the OPTIONAL sha256 so the loop below can prefer a
    # content-digest match and fall back to name+size only when the digest is
    # absent (older server / reconcile-minted handle).
    remote_by_name: dict = {}
    try:
        resp = requests.get(
            f"{base_url}{_F9_FILES_ROUTE}",
            headers=scope_headers,
            timeout=5,
            verify=verify,
        )
        resp.raise_for_status()
        for obj in resp.json().get("data", []):
            name = obj.get("filename")
            if name:
                remote_by_name[name] = {
                    "size": obj.get("size_bytes"),
                    # Absent on pre-D6 objects; normalise "" to None so the
                    # skip decision below never matches an empty digest.
                    "sha256": obj.get("sha256") or None,
                }
    except Exception as e:
        if debug:
            print(f"[SYNC] F9 list (dedup) unavailable, will upload all: {e}")

    synced, skipped, errors = 0, 0, 0

    for file_info in files:
        temp_file_path = None
        try:
            source_path = (
                file_info.get("file", {}).get("path")
                if isinstance(file_info.get("file"), dict)
                else file_info.get("path")
            )
            filename = file_info.get("name") or (
                os.path.basename(source_path) if source_path else "unknown"
            )
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

            size_bytes = os.path.getsize(source_path)

            # Dedup decision (D6). Prefer the content sha256 the server now
            # surfaces; fall back to name+size only when it is absent.
            remote = remote_by_name.get(filename)
            if remote is not None:
                remote_sha256 = remote.get("sha256")
                if remote_sha256:
                    # Server exposes a digest: skip ONLY on an exact content
                    # match. A same-name, same-size EDIT differs here and is
                    # re-uploaded (the defect the old name+size dedup hid).
                    sha256_hash = hashlib.sha256()
                    with open(source_path, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            sha256_hash.update(chunk)
                    local_sha256 = sha256_hash.hexdigest()
                    if remote_sha256 == local_sha256:
                        skipped += 1
                        continue
                elif remote.get("size") == size_bytes:
                    # Compat window: no server digest, so the best signal is the
                    # legacy name+size match.
                    skipped += 1
                    continue

            mime_type = (
                file_info.get("file", {}).get("meta", {}).get("content_type")
                if isinstance(file_info.get("file"), dict)
                else None
            ) or "application/octet-stream"

            # Part 1: the "params" JSON FIELD (must be the FIRST multipart part).
            # filesystem_id here is design-level create-meta; the authoritative
            # scope is the X-OCU-Filesystem-Id header. media_type (not mime_type)
            # is the request MIME field name (ADR-0028, strict-decoded).
            params = {
                "filesystem_id": filesystem_id,
                "path": f"/{filename}",
                "declared_size_bytes": size_bytes,
                "authorization_metadata": {"intent": "write", "downloadable": True},
                "filename": filename,
                "media_type": mime_type,
                # A re-attach with changed content (the D6 sha256 arm fired above)
                # must REPLACE the existing object, not 409. F9 create defaults
                # overwrite_existing=false (refuse), so an omitted flag makes the
                # re-upload fail and the guest keeps reading stale bytes -- the exact
                # staleness D6 exists to kill. The sha256 dedup short-circuits before
                # this POST on identical content, so overwrite only ever fires on a
                # genuine change; the client holds the write lease (intent:write) and
                # per ADR-0030 the scope is this chat's sole writer.
                "overwrite_existing": True,
            }

            with open(source_path, "rb") as f:
                # requests preserves insertion order, so the "params" field is
                # emitted before the "file" part — the STAGE-0 ordering the
                # service requires. No content-type is hand-set: requests
                # generates the multipart boundary itself.
                multipart = [
                    (_F9_MULTIPART_PARAMS_FIELD, (None, json.dumps(params), "application/json")),
                    (
                        _F9_MULTIPART_FILE_FIELD,
                        (_F9_MULTIPART_FILE_FILENAME, f, "application/octet-stream"),
                    ),
                ]
                resp = requests.post(
                    f"{base_url}{_F9_FILES_ROUTE}",
                    headers=scope_headers,
                    files=multipart,
                    timeout=30,
                    verify=verify,
                )
                resp.raise_for_status()
            synced += 1
        except Exception as e:
            if debug:
                print(f"[SYNC] F9 create failed for one file: {e}")
            errors += 1
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass

    return {"synced": synced, "skipped": skipped, "errors": errors}
