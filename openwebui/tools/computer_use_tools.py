"""
title: Computer Use Tools
author: OpenWebUI Implementation
version: 3.0.0

Thin MCP client proxy to computer-use-orchestrator. All config lives server-side.
Only FILE_SERVER_URL + MCP_API_KEY needed — everything else is auto.

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
from datetime import timedelta
from typing import Callable, Awaitable, Optional, List, Annotated
from pydantic import BaseModel, Field


# Client HTTP timeouts (server controls actual command timeout)
CLIENT_HTTP_TIMEOUT = 660       # 11 min > server's 600s COMMAND_TIMEOUT
SUB_AGENT_CLIENT_TIMEOUT = 3660 # 61 min > server's 3600s SUB_AGENT_TIMEOUT


# ============================================================================
# MCP Streamable HTTP Client
# ============================================================================

class _MCPClient:
    """MCP Streamable HTTP client for computer-use-orchestrator."""

    def __init__(self, file_server_url: str, mcp_api_key: str = ""):
        base = file_server_url.rstrip("/")
        self.mcp_url = f"{base}/mcp"
        self.api_key = mcp_api_key

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
        """Call MCP tool via Streamable HTTP with SSE progress."""
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
            return f"[Timeout after {timeout}s] Operation timed out."
        except ConnectionError as e:
            return f"[Error] Could not connect to computer-use-orchestrator: {e}"
        except Exception as e:
            return f"[Error] MCP call failed: {e}"

    @staticmethod
    def _extract_text(result) -> str:
        """Extract text from MCP tool result."""
        if not result or not result.content:
            return "[No output]"
        parts = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
        return "\n".join(parts) if parts else "[No text output]"


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
        FILE_SERVER_URL: str = Field(
            default="http://localhost:8081",
            description="File server URL (hosts MCP endpoint and file uploads)"
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
        self._mcp_client_url = None

    @property
    def mcp_client(self) -> _MCPClient:
        """Lazy MCP client — recreated when valves change."""
        url = self.valves.FILE_SERVER_URL
        if self._mcp_client is None or self._mcp_client_url != url:
            self._mcp_client = _MCPClient(url, self.valves.MCP_API_KEY)
            self._mcp_client_url = url
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
                    _sync_uploaded_files, self.valves.FILE_SERVER_URL, chat_id, __files__,
                    debug=self.valves.DEBUG_LOGGING
                )
                if sync_result.get("synced", 0) > 0:
                    print(f"Synced {sync_result['synced']} file(s)")
            except Exception as e:
                print(f"[SYNC] Error: {e}")

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

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": description or "Executing bash command...", "status": "in_progress", "done": False}})

        try:
            headers = self._build_mcp_headers(chat_id, __user__, request=__request__)
            result = await self.mcp_client.call_tool(
                "bash_tool", {"command": command, "description": description},
                headers=headers, timeout=CLIENT_HTTP_TIMEOUT,
                event_emitter=__event_emitter__,
            )
            if __event_emitter__:
                is_err = result.startswith("[Error]") or result.startswith("Error:")
                await __event_emitter__({"type": "status", "data": {"description": "Command failed" if is_err else "Command completed", "status": "error" if is_err else "complete", "done": True}})
            return result
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Execution error", "status": "error", "done": True}})
            return f"Error: {str(e)}"

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

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": description or f"Editing {path}...", "status": "in_progress", "done": False}})

        try:
            headers = self._build_mcp_headers(chat_id, __user__, request=__request__)
            result = await self.mcp_client.call_tool(
                "str_replace", {"description": description, "old_str": old_str, "path": path, "new_str": new_str},
                headers=headers, timeout=CLIENT_HTTP_TIMEOUT,
                event_emitter=__event_emitter__,
            )
            if __event_emitter__:
                is_err = "error" in result.lower()[:20]
                await __event_emitter__({"type": "status", "data": {"description": "File edited" if not is_err else "Edit failed", "status": "complete" if not is_err else "error", "done": True}})
            return result
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Execution error", "status": "error", "done": True}})
            return f"Error: {str(e)}"

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

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": description or f"Creating {path}...", "status": "in_progress", "done": False}})

        try:
            headers = self._build_mcp_headers(chat_id, __user__, request=__request__)
            result = await self.mcp_client.call_tool(
                "create_file", {"description": description, "file_text": file_text, "path": path},
                headers=headers, timeout=CLIENT_HTTP_TIMEOUT,
                event_emitter=__event_emitter__,
            )
            if __event_emitter__:
                is_err = "error" in result.lower()[:20]
                await __event_emitter__({"type": "status", "data": {"description": "File created" if not is_err else "Creation failed", "status": "complete" if not is_err else "error", "done": True}})
            return result
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Execution error", "status": "error", "done": True}})
            return f"Error: {str(e)}"

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

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": description or f"Reading {path}...", "status": "in_progress", "done": False}})

        try:
            headers = self._build_mcp_headers(chat_id, __user__, request=__request__)
            args = {"description": description, "path": path}
            if view_range:
                args["view_range"] = view_range

            result = await self.mcp_client.call_tool(
                "view", args, headers=headers, timeout=CLIENT_HTTP_TIMEOUT,
                event_emitter=__event_emitter__,
            )
            if __event_emitter__:
                is_err = result.startswith("Error:")
                await __event_emitter__({"type": "status", "data": {"description": "Read complete" if not is_err else "Read failed", "status": "complete" if not is_err else "error", "done": True}})
            return result
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Execution error", "status": "error", "done": True}})
            return f"Error: {str(e)}"

    async def sub_agent(
        self,
        task: str,
        description: str,
        model: str = "sonnet",
        max_turns: int = 50,
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
        :param max_turns: Max iterations, default 50
        :param mode: "act" (execute) or "plan" (plan only)
        :param working_directory: Work dir, default /home/assistant
        :param resume_session_id: Session ID to resume (from previous result)
        :return: Sub-agent's response with results, cost, turn count, session_id
        """
        chat_id = (__metadata__.get("chat_id") if __metadata__ else None) or "default"

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": description or f"Starting sub-agent ({model})...", "status": "in_progress", "done": False}})

        if __files__:
            await self._sync_files_if_needed(chat_id, "/mnt/user-data/uploads", __files__)

        try:
            headers = self._build_mcp_headers(chat_id, __user__, request=__request__)
            args = {
                "task": task, "description": description, "model": model,
                "max_turns": max_turns, "working_directory": working_directory,
            }
            if resume_session_id:
                args["resume_session_id"] = resume_session_id

            result = await self.mcp_client.call_tool(
                "sub_agent", args, headers=headers, timeout=SUB_AGENT_CLIENT_TIMEOUT,
                event_emitter=__event_emitter__,
            )
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Sub-agent completed", "status": "complete", "done": True}})
            return result
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Sub-agent error", "status": "error", "done": True}})
            return f"Sub-agent error: {str(e)}"


# ============================================================================
# File sync helper (HTTP — no SSH needed)
# ============================================================================

def _sync_uploaded_files(file_server_url: str, chat_id: str, files: list, debug: bool = False) -> dict:
    """Sync uploaded files from OpenWebUI to computer-use-orchestrator via HTTP."""
    import requests
    import hashlib

    if not files:
        return {"synced": 0, "skipped": 0, "errors": 0}

    try:
        manifest_url = f"{file_server_url}/api/uploads/{chat_id}/manifest"
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

            upload_url = f"{file_server_url}/api/uploads/{chat_id}/{filename}"
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
