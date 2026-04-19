# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
MCP Server Tools for Computer Use

Provides MCP tools (bash, str_replace, create_file, view, sub_agent) via Streamable HTTP.
Works with local Docker socket for container management.

ARCHITECTURE:
- File-server runs alongside Docker daemon on the same host
- Docker containers are created/managed via local Docker socket
- Each chat gets its own isolated container: owui-chat-{chat_id}

GITLAB TOKEN FETCHING:
Priority order for GitLab token:
1. X-Gitlab-Token header (direct from client)
2. MCP Tokens Wrapper (fetches token by user email)
3. No token (continue without GitLab auth)

HTTP Headers — all optional except Chat ID. Headers override env var defaults.

| Parameter         | Header                 | Alt Header (OpenWebUI)         | Required | Fallback                        |
|-------------------|------------------------|--------------------------------|----------|---------------------------------|
| Chat ID           | X-Chat-Id              | X-OpenWebUI-Chat-Id            | Yes      | —                               |
| User Email        | X-User-Email           | X-OpenWebUI-User-Email         | No       | —                               |
| User Name         | X-User-Name            | X-OpenWebUI-User-Name          | No       | —                               |
| GitLab Token      | X-Gitlab-Token         | X-OpenWebUI-Gitlab-Token       | No       | MCP Tokens Wrapper by email     |
| GitLab Host       | X-Gitlab-Host          | X-OpenWebUI-Gitlab-Host        | No       | gitlab.com                      |
| Anthropic API Key | X-Anthropic-Api-Key    | X-OpenWebUI-Anthropic-Api-Key  | No       | ANTHROPIC_AUTH_TOKEN env        |
| Anthropic Base URL| X-Anthropic-Base-Url   | X-OpenWebUI-Anthropic-Base-Url | No       | ANTHROPIC_BASE_URL env          |
| MCP Tokens URL    | X-Mcp-Tokens-Url       | X-OpenWebUI-Mcp-Tokens-Url     | No       | MCP_TOKENS_URL env              |
| MCP Tokens API Key| X-Mcp-Tokens-Api-Key   | X-OpenWebUI-Mcp-Tokens-Api-Key | No       | MCP_TOKENS_API_KEY env          |
| MCP Servers       | X-Mcp-Servers          | X-OpenWebUI-Mcp-Servers        | No       | —                               |

Environment Variables (computer-use-orchestrator defaults):
- MCP_TOKENS_URL: MCP Tokens Wrapper service (optional, for centralized token management)
- MCP_TOKENS_API_KEY: Internal API key for MCP Tokens Wrapper
- ANTHROPIC_AUTH_TOKEN: Shared LiteLLM proxy key for Claude Code sub-agent
- ANTHROPIC_BASE_URL: LLM API base URL (default: https://api.anthropic.com)
- SUB_AGENT_DEFAULT_MODEL: Default model for sub_agent (sonnet/opus, default: sonnet)
- SUB_AGENT_MAX_TURNS: Default max turns for sub_agent (default: 25)
- SUB_AGENT_TIMEOUT: Timeout for sub_agent execution in seconds (default: 3600)

LiteLLM Integration:
  mcp_servers:
    docker_ai:
      url: "http://computer-use-server:8081/mcp"
      transport: "http"
      auth_type: "bearer_token"
      auth_value: "<MCP_API_KEY>"
      extra_headers:
        # OpenWebUI headers (alternative)
        - "x-openwebui-chat-id"
        - "x-openwebui-user-email"
        - "x-openwebui-user-name"
        - "x-openwebui-gitlab-token"
        - "x-openwebui-gitlab-host"
        - "x-openwebui-anthropic-api-key"
        - "x-openwebui-anthropic-base-url"
        # Direct headers
        - "x-chat-id"
        - "x-user-email"
        - "x-user-name"
        - "x-gitlab-token"
        - "x-gitlab-host"
        - "x-anthropic-api-key"
        - "x-anthropic-base-url"
"""

import os
import re
import json
import shlex
import time
import asyncio
import urllib.parse
from typing import Optional, List, Annotated

from mcp.server.fastmcp import FastMCP, Context
from pydantic import Field
import skill_manager
from context_vars import (
    current_chat_id, current_user_email, current_user_name,
    current_gitlab_token, current_gitlab_host,
    current_anthropic_auth_token, current_anthropic_base_url,
    current_mcp_tokens_url, current_mcp_tokens_api_key, current_mcp_servers,
    current_instructions,
)
from system_prompt import render_system_prompt


# Single-user mode: "" (lenient default), "true" (solo), "false" (strict multi-user)
SINGLE_USER_MODE = os.getenv("SINGLE_USER_MODE", "").lower()

# Warning appended to tool responses when using default container in lenient mode
DEFAULT_CHAT_ID_WARNING = (
    "\n\n---\n"
    "Note: No X-Chat-Id header provided — using shared 'default' container.\n"
    "All sessions without a chat ID share the same container (files, processes, state).\n\n"
    "Options:\n"
    "- Set SINGLE_USER_MODE=true in .env to always use one container (single-user setup)\n"
    "- Set SINGLE_USER_MODE=false to require X-Chat-Id (multi-user setup)\n"
    "- Pass X-Chat-Id header in your MCP client for per-session isolation\n"
)

# Error returned when chat_id is missing in strict multi-user mode
CHAT_ID_REQUIRED_ERROR = (
    "Error: X-Chat-Id header is required (SINGLE_USER_MODE=false).\n\n"
    "In multi-user mode, every request must include X-Chat-Id for container isolation.\n"
    "Pass -H \"X-Chat-Id: your-unique-id\" or set SINGLE_USER_MODE=true for single-user setup."
)


def _validate_chat_id() -> tuple[str, str | None]:
    """
    Validate chat_id based on SINGLE_USER_MODE setting.

    Returns:
        tuple: (chat_id, error_message) - error_message is None if valid
    """
    chat_id = current_chat_id.get()

    if SINGLE_USER_MODE == "true":
        return "default", None

    if chat_id == "default":
        if SINGLE_USER_MODE == "false":
            return chat_id, CHAT_ID_REQUIRED_ERROR
        return chat_id, None

    return chat_id, None


def _get_default_chat_warning() -> str:
    """Return warning suffix if using default chat_id in lenient mode."""
    if SINGLE_USER_MODE in ("true", "false"):
        return ""
    if current_chat_id.get() == "default":
        print("[WARN] No X-Chat-Id header and SINGLE_USER_MODE not set — using shared 'default' container")
        return DEFAULT_CHAT_ID_WARNING
    return ""


# Configuration from environment

# Docker management extracted to docker_manager.py
from docker_manager import (
    get_docker_client, get_container_cdp_address,
    _get_or_create_container, _execute_bash, execute_bash_streaming, _execute_python_with_stdin,
    _reset_shutdown_timer, _get_compose_network_name,
    build_mcp_config, build_mcp_config_write_script,
    _fetch_gitlab_token, _ensure_gitlab_token,
    DOCKER_SOCKET, DOCKER_IMAGE, CONTAINER_MEM_LIMIT, CONTAINER_CPU_LIMIT,
    COMMAND_TIMEOUT, ENABLE_NETWORK, USER_DATA_BASE_PATH, PUBLIC_BASE_URL,
    MCP_TOKENS_URL, MCP_TOKENS_API_KEY,
    SUB_AGENT_DEFAULT_MODEL, SUB_AGENT_MAX_TURNS, SUB_AGENT_TIMEOUT,
    ANTHROPIC_DEFAULT_SONNET_MODEL,
    ANTHROPIC_DEFAULT_OPUS_MODEL,
    ANTHROPIC_DEFAULT_HAIKU_MODEL,
)



# ============================================================================
# Progress Utilities (moved from computer_use_tools.py for server-side use)
# ============================================================================

def format_elapsed_time(seconds: int) -> str:
    """Format elapsed time as human-readable string (e.g., '45s', '2m 15s')."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    if remaining_seconds == 0:
        return f"{minutes}m"
    return f"{minutes}m {remaining_seconds}s"


_TOOL_LABELS = {
    "Bash": "Command",
    "Read": "Reading",
    "Write": "Writing",
    "Edit": "Editing",
    "Grep": "Searching",
    "Glob": "Finding files",
    "WebSearch": "Web search",
    "WebFetch": "Loading page",
    "TodoWrite": "Tasks",
    "Agent": "Subtask",
    "ToolSearch": "Selecting tool",
}


def parse_last_action(lines: list) -> Optional[str]:
    """
    Parse JSONL lines from Claude session log and return last meaningful action.
    Returns whichever came last in the log (text or tool_use) to avoid showing
    stale text while a long tool is executing.
    """
    last_action = None

    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if data.get("type") == "assistant":
                content = data.get("message", {}).get("content", [])
                for item in content:
                    if item.get("type") == "text":
                        text = item.get("text", "")[:80]
                        text = text.replace('\n', ' ').strip()
                        if text:
                            last_action = text
                    elif item.get("type") == "tool_use":
                        name = item.get("name", "unknown")
                        inp = item.get("input", {})
                        detail = get_tool_detail(name, inp)
                        tool_label = _TOOL_LABELS.get(name, name)
                        if detail:
                            last_action = f"{tool_label}: {detail}"
                        else:
                            last_action = f"{tool_label}..."
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    return last_action


def get_tool_detail(name: str, inp: dict) -> Optional[str]:
    """Extract useful detail from tool input for status display."""
    try:
        # First check for description field (Claude fills this for our tools)
        desc = inp.get("description", "")
        if desc:
            return desc.replace('\n', ' ').strip()

        # Fallback to tool-specific extraction
        if name == "Bash":
            cmd = inp.get("command", "")
            return cmd.replace('\n', ' ').strip() if cmd else None
        elif name == "WebSearch":
            return inp.get("query", "")
        elif name == "Write":
            path = inp.get("file_path", "")
            return path.split("/")[-1] if path else None
        elif name == "Read":
            path = inp.get("file_path", "")
            return path.split("/")[-1] if path else None
        elif name == "Edit":
            path = inp.get("file_path", "")
            return path.split("/")[-1] if path else None
        elif name == "Grep":
            pattern = inp.get("pattern", "")
            return f'"{pattern}"' if pattern else None
        elif name == "Glob":
            return inp.get("pattern", "")
        elif name == "TodoWrite":
            todos = inp.get("todos", [])
            in_progress = [t for t in todos if t.get("status") == "in_progress"]
            if in_progress:
                return in_progress[0].get("content", "")
            return f"{len(todos)} tasks"
    except Exception:
        pass
    return None



# ============================================================================
# MCP Server Definition
# ============================================================================

# Static instructions kwarg — fallback when Tier 4's dynamic override is
# bypassed (client that ignores InitializeResult.instructions, or the
# render_system_prompt pre-render failed). Points at the other tiers so any
# client hitting this baseline learns where to fetch the real content.
_STATIC_INSTRUCTIONS = (
    "Computer Use tools: bash, file edits, browser, sub-agent — in an isolated "
    "Docker sandbox. Full per-session guide is at /home/assistant/README.md "
    "(call the view tool to read it). Uploaded files are exposed via "
    "resources/list."
)

mcp = FastMCP(
    name="computer-use-mcp",
    instructions=_STATIC_INSTRUCTIONS,
    streamable_http_path="/",       # Root path — mounted at /mcp in FastAPI
    stateless_http=True,            # Each request is independent (no session persistence)
    transport_security={            # Behind proxy (LiteLLM/nginx), any Host is valid
        "enable_dns_rebinding_protection": False,
    },
)


# ============================================================================
# Tier 4 — Dynamic InitializeResult.instructions
# ============================================================================
#
# The static `instructions=` kwarg above ships as a constant in every
# InitializeResult. We want per-chat content (file URLs, skills) to ride in
# that same field so clients like Claude Desktop / MCP Inspector (which
# render `instructions` directly) get dynamic content without any explicit
# prompts/get call.
#
# Mechanism (works ONLY because stateless_http=True):
#   1. Middleware awaits render_system_prompt(chat_id, user_email) BEFORE
#      dispatching the MCP handler and stores the result in
#      `current_instructions` ContextVar (see MCPContextMiddleware below).
#   2. `streamable_http_manager._handle_stateless_request` (verified at
#      .venv/.../mcp/server/streamable_http_manager.py:196) spins up a fresh
#      `server.run(..., initialization_options, stateless=True)` per HTTP
#      request, and `create_initialization_options()` is called INSIDE that
#      per-request task — after the middleware has run.
#   3. `lowlevel/server.py:188` reads `self.instructions` at that moment.
#      We override the property to return the ContextVar value.
#   4. `session.py:183` echoes it into `InitializeResult.instructions`.
#
# Stateful mode would break this: a long-lived session caches init_options at
# construction time. Do NOT flip stateless_http=False without re-reading the
# SDK source above.
#
# Private-API caveat: we swap `mcp._mcp_server.__class__` in place. FastMCP
# doesn't expose a public hook. Pin the `mcp` version in requirements.txt to
# protect against attribute renames.
from mcp.server.lowlevel.server import Server as _LowlevelServer


class _DynamicInstructionsServer(_LowlevelServer):
    """Subclass that reads `instructions` from the current-request ContextVar.

    Falls back to the static string if the middleware hasn't pre-rendered
    (e.g. a render exception, or a direct in-process call without ASGI)."""

    @property
    def instructions(self):  # type: ignore[override]
        return current_instructions.get() or self._static_instructions

    @instructions.setter
    def instructions(self, value):
        self._static_instructions = value


# Rebind class on the already-constructed lowlevel Server so the property
# override takes effect without reconstructing FastMCP. The base class stores
# `instructions` in `self.__dict__`; move it to the `_static_instructions`
# slot before swapping the class so the property getter can read it as the
# fallback.
#
# Defensive shape assertions — these guard against silent breakage when the
# `mcp` SDK changes the private attribute layout (e.g. moves `_mcp_server` to
# `_lowlevel_server`, or switches to __slots__). Without them, an SDK rename
# would silently drop us back to static instructions for every chat — Tier 4
# would just stop working with no error to debug.
assert hasattr(mcp, "_mcp_server"), (
    "FastMCP no longer exposes _mcp_server — Tier 4 dynamic instructions "
    "broke. Re-pin mcp in requirements.txt and update mcp_tools.py."
)
_existing_lowlevel_server = mcp._mcp_server  # private; pinned mcp version guards
assert isinstance(_existing_lowlevel_server, _LowlevelServer), (
    f"mcp._mcp_server is not a lowlevel Server (got {type(_existing_lowlevel_server)!r}). "
    "Tier 4 class-swap will not work. Re-pin mcp."
)
assert hasattr(_existing_lowlevel_server, "__dict__"), (
    "Lowlevel Server uses __slots__ — class-swap pop() will fail. Re-pin mcp."
)
_existing_instructions_value = _existing_lowlevel_server.__dict__.pop(
    "instructions", _STATIC_INSTRUCTIONS
)
_existing_lowlevel_server._static_instructions = _existing_instructions_value
_existing_lowlevel_server.__class__ = _DynamicInstructionsServer


async def send_progress(ctx: "Context", progress: float, total: float, message: str):
    """Send progress notification with related_request_id for stateless HTTP mode.

    Workaround for MCP SDK bug: ctx.report_progress() doesn't pass
    related_request_id, so notifications get lost in stateless_http mode
    (routed to non-existent GET SSE stream instead of request stream).
    """
    rc = ctx.request_context
    if not rc or not rc.meta or not rc.meta.progressToken:
        return
    await rc.session.send_progress_notification(
        progress_token=rc.meta.progressToken,
        progress=progress,
        total=total,
        message=message,
        related_request_id=str(rc.request_id),
    )


# Custom type for view_range
ViewRange = Annotated[
    Optional[List[int]],
    Field(
        default=None,
        min_length=2,
        max_length=2,
        description="Optional line range [start_line, end_line]. Use [start, -1] to view from start to end."
    )
]


# ---------------------------------------------------------------------------
# Output truncation & command semantics (inspired by Claude Code BashTool)
# ---------------------------------------------------------------------------

MAX_BASH_OUTPUT_CHARS = 30_000

# Commands where exit code 1 is NOT an error (semantic exit codes)
# grep/rg: 1=no matches, 2+=error
# find: 1=partial access, 2+=error
# diff: 1=files differ, 2+=error
# test/[: 1=condition false, 2+=error
COMMAND_SEMANTICS = {
    'grep':  {'threshold': 2, 'message': 'No matches found'},
    'rg':    {'threshold': 2, 'message': 'No matches found'},
    'find':  {'threshold': 2, 'message': 'Some directories were inaccessible'},
    'diff':  {'threshold': 2, 'message': 'Files differ'},
    'test':  {'threshold': 2, 'message': 'Condition is false'},
    '[':     {'threshold': 2, 'message': 'Condition is false'},
}


def _get_first_command(command: str) -> str:
    """Extract the first command name from a shell command string."""
    cmd = command.strip()
    # Skip env vars like VAR=val, sudo, etc.
    for token in cmd.split():
        if '=' in token:
            continue
        if token in ('sudo', 'env', 'nice', 'time', 'strace'):
            continue
        # Return basename (e.g. /usr/bin/grep -> grep)
        return token.rsplit('/', 1)[-1]
    return ''


def _apply_command_semantics(command: str, exit_code: int, output: str) -> str:
    """Apply command-specific exit code interpretation."""
    if exit_code == 0:
        return output if output else "[No output]"

    first_cmd = _get_first_command(command)
    semantic = COMMAND_SEMANTICS.get(first_cmd)

    if semantic and exit_code < semantic['threshold']:
        # Exit code is informational, not an error
        return output if output else semantic['message']

    # Default: return output or exit code
    return output if output else f"[Exit code: {exit_code}]"


def _truncate_output(output: str, max_chars: int = MAX_BASH_OUTPUT_CHARS) -> str:
    """Truncate large output, keeping head and tail."""
    if len(output) <= max_chars:
        return output
    half = max_chars // 2
    total = len(output)
    return (
        output[:half]
        + f"\n\n... [Output truncated: {total} chars total, showing first and last {half} chars.\n"
        + f"Use head/tail/view to read specific parts] ...\n\n"
        + output[-half:]
    )


@mcp.tool()
async def bash_tool(command: str, description: str, ctx: Context) -> str:
    """
    Run a bash command in the container.

    If you've lost track of your environment (chat_id, file URLs, available
    skills), re-read /home/assistant/README.md.

    Args:
        command: Bash command to run in container
        description: Why I'm running this command

    Returns:
        Command output (stdout/stderr)
    """
    chat_id, error = _validate_chat_id()
    if error:
        return error

    try:
        await _ensure_gitlab_token()

        timeout = int(os.getenv("COMMAND_TIMEOUT", "120"))

        try:
            container = await asyncio.wait_for(
                asyncio.to_thread(_get_or_create_container, chat_id),
                timeout=60,
            )
        except asyncio.TimeoutError:
            return "Error: Container creation timed out (60s). Docker may be overloaded."

        # Report progress during execution
        start_time = time.time()
        last_output_line: list[str] = [""]

        def _on_output_line(line: str) -> None:
            last_output_line[0] = line

        async def _progress_heartbeat():
            while True:
                await asyncio.sleep(15)
                elapsed = int(time.time() - start_time)
                msg = f"Running: {description} ({format_elapsed_time(elapsed)})"
                last = last_output_line[0]
                if last:
                    msg += f"\n→ {last}"
                await send_progress(ctx, elapsed, timeout, msg)

        heartbeat = asyncio.create_task(_progress_heartbeat())
        try:
            result = await asyncio.to_thread(
                execute_bash_streaming, container, command, timeout, _on_output_line
            )
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

        output = _apply_command_semantics(command, result["exit_code"], result["output"])
        return _truncate_output(output) + _get_default_chat_warning()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def str_replace(
    description: str,
    old_str: str,
    path: str,
    new_str: str = "",
    ctx: Context = None,  # injected by FastMCP; None when called directly
) -> str:
    """
    Replace a unique string in a file with another string.
    The string to replace must appear exactly once in the file.

    Args:
        description: Why I'm making this edit
        old_str: String to replace (must be unique in file)
        path: Path to the file to edit
        new_str: String to replace with (empty to delete)

    Returns:
        Success message or error
    """
    chat_id, error = _validate_chat_id()
    if error:
        return error

    if old_str == new_str:
        return "Error: old_str and new_str are identical. No changes would be made."

    try:
        await _ensure_gitlab_token()
        try:
            container = await asyncio.wait_for(
                asyncio.to_thread(_get_or_create_container, chat_id), timeout=60
            )
        except asyncio.TimeoutError:
            return "Error: Container creation timed out (60s)."

        script = """
import sys
import json

try:
    data = json.loads(sys.stdin.read())
    path = data['path']
    old_str = data['old_str']
    new_str = data['new_str']

    with open(path, 'r') as f:
        content = f.read()

    if old_str not in content:
        print(f"Error: old_str not found in {path}")
        sys.exit(1)

    count = content.count(old_str)
    if count > 1:
        print(f"Error: Found {count} occurrences of old_str in {path}. Add more surrounding context to make it unique.")
        sys.exit(1)

    new_content = content.replace(old_str, new_str, 1)

    with open(path, 'w') as f:
        f.write(new_content)

    print(f"Successfully replaced text in {path}")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
"""
        payload = json.dumps({"path": path, "old_str": old_str, "new_str": new_str})
        result = await asyncio.to_thread(_execute_python_with_stdin, container, script, payload)
        return result["output"] + _get_default_chat_warning()

    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def create_file(
    description: str,
    file_text: str,
    path: str,
    ctx: Context = None,
) -> str:
    """
    Create a new file with content in the container.

    Args:
        description: Why I'm creating this file. ALWAYS PROVIDE THIS PARAMETER FIRST.
        file_text: Content to write to the file. ALWAYS PROVIDE THIS PARAMETER SECOND.
        path: Path to the file to create. ALWAYS PROVIDE THIS PARAMETER LAST.

    Returns:
        Success message or error
    """
    chat_id, error = _validate_chat_id()
    if error:
        return error

    try:
        await _ensure_gitlab_token()
        try:
            container = await asyncio.wait_for(
                asyncio.to_thread(_get_or_create_container, chat_id), timeout=60
            )
        except asyncio.TimeoutError:
            return "Error: Container creation timed out (60s)."

        script = """
import sys
import json
import os

try:
    data = json.loads(sys.stdin.read())
    path = data['path']
    file_text = data['file_text']

    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, 'w') as f:
        f.write(file_text)

    print(f"Successfully created {path}")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
"""
        payload = json.dumps({"path": path, "file_text": file_text})
        result = await asyncio.to_thread(_execute_python_with_stdin, container, script, payload)
        output = result["output"] if result["success"] else f"Error: {result['output']}"
        return output + _get_default_chat_warning()

    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def view(
    description: str,
    path: str,
    view_range: Optional[List[int]] = None,
    ctx: Context = None,
) -> str:
    """
    View text files or directory listings.
    Binary files are detected and rejected with instructions to read SKILL documentation.

    If you've lost track of your environment (chat_id, file URLs, available
    skills), re-read /home/assistant/README.md.

    Supported path types:
    - Directories: Lists files and directories with details
    - Text files: Displays numbered lines. You can optionally specify a view_range.
    - Binary files (.xlsx, .docx, .pptx, .pdf, etc.): Returns error with SKILL.md instructions

    Args:
        description: Why I need to view this
        path: Absolute path to file or directory, e.g. `/repo/file.py` or `/repo`
        view_range: Optional line range [start_line, end_line]. Use [start, -1] to view from start to end.

    Returns:
        File contents, directory listing, or error message
    """
    chat_id, error = _validate_chat_id()
    if error:
        return error

    try:
        await _ensure_gitlab_token()
        try:
            container = await asyncio.wait_for(
                asyncio.to_thread(_get_or_create_container, chat_id), timeout=60
            )
        except asyncio.TimeoutError:
            return "Error: Container creation timed out (60s)."

        quoted_path = shlex.quote(path)

        # Image extensions — handled separately (resize+return as image content)
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

        # Binary file hints (non-image)
        binary_file_hints = {
            '.xlsx': 'Excel spreadsheet. Read SKILL first:\n  view /mnt/skills/public/xlsx/SKILL.md',
            '.xls': 'Excel spreadsheet (old). Read SKILL first:\n  view /mnt/skills/public/xlsx/SKILL.md',
            '.docx': 'Word document. Read SKILL first:\n  view /mnt/skills/public/docx/SKILL.md',
            '.pptx': 'PowerPoint. Read SKILL first:\n  view /mnt/skills/public/pptx/SKILL.md',
            '.pdf': 'PDF document. Read SKILL first:\n  view /mnt/skills/public/pdf/SKILL.md',
            '.zip': 'ZIP archive. Use: unzip -l {path}',
            '.tar': 'TAR archive. Use: tar -tvf {path}',
            '.gz': 'Gzip file. Use: gunzip -c {path} | head -n 100',
        }

        file_ext = None
        path_lower = path.lower()
        for ext in list(binary_file_hints.keys()) + list(image_extensions):
            if path_lower.endswith(ext):
                file_ext = ext
                break

        if file_ext and file_ext in image_extensions:
            # Image file — resize+compress in container, return as structured content
            try:
                py_code = (
                    "from PIL import Image; from io import BytesIO; import base64,sys; "
                    f"img=Image.open({path!r}); "
                    "mx=1280; "
                    "img.thumbnail((mx,mx),Image.Resampling.LANCZOS) if max(img.size)>mx else None; "
                    "img=img.convert('RGB') if img.mode in ('RGBA','P') else img; "
                    "b=BytesIO(); img.save(b,format='JPEG',quality=80); "
                    "sys.stdout.write(base64.b64encode(b.getvalue()).decode())"
                )
                resize_cmd = f"python3 -c {shlex.quote(py_code)}"
                b64_result = await asyncio.to_thread(_execute_bash, container, resize_cmd)
                if b64_result["exit_code"] != 0:
                    return f"Error viewing image {path}: {b64_result['output']}"
                image_b64 = b64_result["output"].strip()
                return [
                    {"type": "text", "text": f"Image: {path}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                ]
            except Exception as e:
                return f"Error processing image {path}: {e}"

        elif file_ext and file_ext in binary_file_hints:
            hint = binary_file_hints[file_ext].format(path=path)
            command = f"""
if [ -f {quoted_path} ]; then
    echo "Error: Cannot view binary file with 'cat'. This is a {file_ext} file."
    echo ""
    echo "{hint}"
    exit 1
elif [ -d {quoted_path} ]; then
    ls -lah {quoted_path}
else
    echo "Error: path not found"
    exit 1
fi
"""
        else:
            if view_range:
                start, end = view_range
                if end == -1:
                    cat_command = f"sed -n '{start},$p' {quoted_path} | cat -n"
                else:
                    cat_command = f"sed -n '{start},{end}p' {quoted_path} | cat -n"
            else:
                cat_command = f"cat -n {quoted_path}"

            command = f"""
if [ -f {quoted_path} ]; then
    {cat_command}
elif [ -d {quoted_path} ]; then
    ls -lah {quoted_path}
else
    echo "Error: path not found"
    exit 1
fi
"""

        result = await asyncio.to_thread(_execute_bash, container, command)
        output = result["output"] if result["output"] else "Error: No output"

        # Truncate if needed (30K limit, matching bash_tool MAX_BASH_OUTPUT_CHARS)
        if not view_range and len(output) > 30000:
            truncation_msg = f"\n\n... [File truncated - middle omitted. Total: {len(output)} chars. Use view_range.] ...\n\n"
            output = output[:15000] + truncation_msg + output[-15000:]

        return output + _get_default_chat_warning()

    except Exception as e:
        return f"Error: {str(e)}"


async def _format_sub_agent_result(
    output: str,
    model: str,
    max_turns: int,
    duration: float
) -> str:
    """Parse Claude JSON output and format result with session_id for resume."""
    response_text = ""
    cost = 0.0
    turns = 0
    is_error = False
    session_id = ""

    try:
        # Find the result JSON line in output
        for line in output.strip().split('\n'):
            line = line.strip()
            if '"type"' in line and '"result"' in line:
                try:
                    parsed = json.loads(line)
                    if parsed.get("type") == "result":
                        response_text = parsed.get("result", "")
                        cost = parsed.get("total_cost_usd", 0.0)
                        turns = parsed.get("num_turns", 0)
                        is_error = parsed.get("is_error", False)
                        session_id = parsed.get("session_id", "")
                        break
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[SUB-AGENT] Failed to parse JSON output: {e}")

    if not response_text:
        response_text = output

    status = "error" if is_error else "success"

    result = f"""**Sub-Agent Completed** ({status})
**Model:** {model} | **Turns:** {turns}/{max_turns} | **Cost:** ${cost:.4f} | **Duration:** {duration:.1f}s

{response_text}"""

    if session_id:
        result += f"\n\n**Session ID:** `{session_id}` (use resume_session_id to continue)"

    return result


@mcp.tool()
async def sub_agent(
    task: str,
    description: str,
    ctx: Context,
    model: str = "",
    max_turns: int = 0,
    working_directory: str = "/home/assistant",
    resume_session_id: str = ""
) -> str:
    """
    COSTLY: Spawns a separate Claude CLI session with its own API budget.
    Use ONLY as a last resort for complex CODE tasks requiring 10+ iterative tool calls.

    Justified uses:
    - Multi-file refactoring (5+ files) with test verification loops
    - Complex code review with automatic fixes across many files
    - Iterative test-fix cycles (run tests, analyze, fix, re-run until pass)

    Do NOT use for (handle these yourself):
    - Tasks completable in fewer than 10 tool calls
    - Creating presentations, documents, spreadsheets
    - Web research or information gathering
    - Simple code review, documentation, or analysis
    - Git operations or simple file edits

    Args:
        task: Detailed description of the task for the sub-agent to accomplish
        description: Why you are delegating this task to a sub-agent
        model: Model to use: 'sonnet' (default, fast) or 'opus' (powerful, better for complex tasks)
        max_turns: Maximum number of agentic turns (default from env, typically 25)
        working_directory: Working directory for the agent (default: /home/assistant)
        resume_session_id: Session ID to resume a previous sub-agent session (from previous result)

    Returns:
        Sub-agent's response with task results, cost, turn count, and session_id for resume
    """
    chat_id, error = _validate_chat_id()
    if error:
        return error

    user_email = current_user_email.get()

    # Use defaults from env if not specified
    if not model:
        model = SUB_AGENT_DEFAULT_MODEL
    if max_turns <= 0:
        max_turns = SUB_AGENT_MAX_TURNS
    DEFAULT_FALLBACK_MODEL = "claude-sonnet-4-6"
    ALIAS_MAP = {
        "sonnet": ANTHROPIC_DEFAULT_SONNET_MODEL or "claude-sonnet-4-6",
        "opus": ANTHROPIC_DEFAULT_OPUS_MODEL or "claude-opus-4-6",
        "haiku": ANTHROPIC_DEFAULT_HAIKU_MODEL or "claude-haiku-4-5",
    }
    requested = (model or "").strip()
    key = requested.lower()
    if key in ALIAS_MAP:
        model_id = ALIAS_MAP[key]
        model_display = key
    elif requested:
        model_id = requested
        model_display = requested
    else:
        model_id = ANTHROPIC_DEFAULT_SONNET_MODEL or DEFAULT_FALLBACK_MODEL
        model_display = "sonnet"
    model = model_id

    try:
        await _ensure_gitlab_token()
        container = await asyncio.to_thread(_get_or_create_container, chat_id)

        # Write ~/.mcp.json if MCP server names provided via header
        mcp_servers_str = current_mcp_servers.get()
        if mcp_servers_str:
            mcp_cfg = build_mcp_config(
                mcp_servers_str,
                current_anthropic_base_url.get(),
                user_email or "",
            )
            if mcp_cfg:
                write_cmd = build_mcp_config_write_script(mcp_cfg)
                await asyncio.to_thread(_execute_bash, container, write_cmd, 15)

        # Build the sub-agent system prompt with dynamic skills
        file_base_url = f"{PUBLIC_BASE_URL}/files/{chat_id}"
        plan_file = "/home/assistant/task_plan.md"
        skills = skill_manager.get_user_skills_sync(user_email) if user_email else skill_manager.get_user_skills_sync(None)
        skills_text = skill_manager.build_sub_agent_skills_text(skills)

        # ANTHROPIC_CUSTOM_HEADERS passes x-openwebui-user-email header for LiteLLM tracking
        headers_env = ""
        if user_email:
            headers_env = f"ANTHROPIC_CUSTOM_HEADERS={shlex.quote(f'x-openwebui-user-email: {user_email}')} "

        # Common flags: disallow interactive tools that don't work in headless mode
        base_flags = (
            f"--max-turns {max_turns} "
            f"--permission-mode bypassPermissions "
            f"--disallowedTools 'AskUserQuestion,ExitPlanMode' "
            f"--output-format json"
        )

        if resume_session_id:
            # === RESUME SESSION ===
            resume_prompt = f"Continue working on the task. If needed, re-read {plan_file} for full context."
            escaped_prompt = shlex.quote(resume_prompt)

            claude_command = (
                f"cd {shlex.quote(working_directory)} && "
                f"{headers_env}"
                f"claude -p {escaped_prompt} "
                f"--resume {shlex.quote(resume_session_id)} "
                f"{base_flags}"
            )
        else:
            # === NEW SESSION ===
            # Save task to plan file - source of truth for sub-agent (survives context compaction)
            write_plan_cmd = f"cat > {plan_file} << 'TASK_PLAN_EOF'\n{task}\nTASK_PLAN_EOF"
            await asyncio.to_thread(_execute_bash, container, write_plan_cmd, 30)

            system_prompt = f"""<critical_instruction>
Your task plan is saved at {plan_file}

BEFORE ANY ACTION:
1. Read {plan_file} to understand your full task
2. If context becomes compacted, re-read {plan_file} - it is your source of truth
3. The plan file contains all details you need

Never forget: {plan_file} has your complete instructions.
</critical_instruction>

<environment>
You are working in a Linux container (Ubuntu 24) as an autonomous sub-agent.
FILE LOCATIONS:
- User uploads: /mnt/user-data/uploads (read-only)
- Workspace: /home/assistant
- Outputs: /mnt/user-data/outputs (URL: {file_base_url}/)
</environment>

<available_skills>
IMPORTANT: Read the relevant SKILL.md BEFORE starting any task!

{skills_text}

Use `cat <skill-location>` to read skill instructions.
</available_skills>"""

            # Short prompt - full details in plan file
            short_task = f"Read and execute your task plan from {plan_file}"
            escaped_task = shlex.quote(short_task)
            escaped_system = shlex.quote(system_prompt)

            claude_command = (
                f"cd {shlex.quote(working_directory)} && "
                f"{headers_env}"
                f"claude -p {escaped_task} "
                f"--model {shlex.quote(model)} "
                f"--append-system-prompt {escaped_system} "
                f"{base_flags}"
            )

        # Create marker file BEFORE starting claude — used to find the new JSONL
        await asyncio.to_thread(
            _execute_bash, container,
            "touch /tmp/.sub_agent_start", 5
        )
        start_time = time.time()

        # Stream session logs via tail -f for real-time progress
        async def _stream_session_logs():
            """Monitor Claude's JSONL session log, send progress via SSE."""
            try:
                # Wait for NEW session JSONL file (newer than marker)
                jsonl_path = None
                for _ in range(60):  # Max 60s wait
                    await asyncio.sleep(1)
                    find_r = await asyncio.to_thread(
                        _execute_bash, container,
                        "find /home/assistant/.claude/projects/-home-assistant/ "
                        "-name '*.jsonl' -newer /tmp/.sub_agent_start 2>/dev/null | head -1", 5
                    )
                    path = (find_r.get("output") or "").strip()
                    if path:
                        jsonl_path = path
                        break

                if not jsonl_path:
                    # Fallback: heartbeat without log reading
                    while True:
                        await asyncio.sleep(15)
                        elapsed = int(time.time() - start_time)
                        await send_progress(
                            ctx, elapsed, SUB_AGENT_TIMEOUT,
                            f"Agent running... ({format_elapsed_time(elapsed)})"
                        )

                # Start tail -f in a thread, bridge to asyncio via queue
                import threading
                q = asyncio.Queue()
                loop = asyncio.get_event_loop()
                client = get_docker_client()

                def _tail_reader():
                    try:
                        exec_id = client.api.exec_create(
                            container.id, ["tail", "-n", "0", "-f", jsonl_path],
                            stdout=True, stderr=False
                        )
                        for chunk in client.api.exec_start(exec_id['Id'], stream=True):
                            loop.call_soon_threadsafe(q.put_nowait, chunk)
                    except Exception:
                        pass  # Container may have stopped

                threading.Thread(target=_tail_reader, daemon=True).start()

                buffer = ""
                while True:
                    try:
                        chunk = await asyncio.wait_for(q.get(), timeout=15)
                        buffer += chunk.decode('utf-8', errors='replace')
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            action = parse_last_action([line])
                            if action:
                                elapsed = int(time.time() - start_time)
                                msg = f"{action} ({format_elapsed_time(elapsed)})"
                                print(f"[SUB-AGENT-PROGRESS] {msg}")
                                await send_progress(ctx, elapsed, SUB_AGENT_TIMEOUT, msg)
                    except asyncio.TimeoutError:
                        # No new lines for 15s — send heartbeat
                        elapsed = int(time.time() - start_time)
                        await send_progress(
                            ctx, elapsed, SUB_AGENT_TIMEOUT,
                            f"Agent running... ({format_elapsed_time(elapsed)})"
                        )
            except asyncio.CancelledError:
                return
            except Exception:
                pass

        # Run Claude command + log streaming concurrently
        log_task = asyncio.create_task(_stream_session_logs())
        try:
            result = await asyncio.to_thread(
                _execute_bash,
                container,
                claude_command,
                SUB_AGENT_TIMEOUT
            )
        finally:
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass

        duration = time.time() - start_time
        output = result.get("output", "")
        exit_code = result.get("exit_code", 0)

        # Helper: find session_id from JSONL file created after marker
        async def _find_session_id() -> str:
            try:
                find_r = await asyncio.to_thread(
                    _execute_bash, container,
                    "find /home/assistant/.claude/projects/-home-assistant/ "
                    "-name '*.jsonl' -newer /tmp/.sub_agent_start 2>/dev/null | head -1", 5
                )
                jsonl_path = (find_r.get("output") or "").strip()
                if jsonl_path:
                    import re
                    m = re.search(r'([0-9a-f-]{36})\.jsonl$', jsonl_path)
                    if m:
                        return m.group(1)
            except Exception:
                pass
            return ""

        # Handle killed/crashed process (SIGKILL, SIGTERM, OOM, etc.)
        if exit_code in (137, 143, -9, -15) or (exit_code != 0 and not output.strip()):
            session_id = await _find_session_id()
            signal_name = {137: "SIGKILL", 143: "SIGTERM", -9: "SIGKILL", -15: "SIGTERM"}.get(
                exit_code, f"exit {exit_code}")
            msg = (
                f"**Sub-Agent Terminated** ({signal_name})\n"
                f"**Model:** {model_display} | **Duration:** {duration:.1f}s\n\n"
                f"Process was killed or crashed before producing results.\n"
            )
            if session_id:
                msg += f"\n**Session ID:** `{session_id}` (use resume_session_id to continue)"
            return msg

        # Check if timed out but Claude is still running
        if exit_code == 124:
            session_id = await _find_session_id()
            timeout_msg = (
                f"**Sub-Agent Timeout** ({SUB_AGENT_TIMEOUT}s)\n\n"
                f"Claude Code is still running in the container.\n"
                f"You can monitor progress in the SubAgent tab.\n\n"
                f"Results will be in /mnt/user-data/outputs/"
            )
            if session_id:
                timeout_msg += f"\n\n**Session ID:** `{session_id}` (use resume_session_id to continue)"
            try:
                check = await asyncio.to_thread(
                    _execute_bash, container,
                    "pgrep -f 'claude' > /dev/null 2>&1 && echo ALIVE || echo DEAD", 10)
                if "ALIVE" in check.get("output", ""):
                    return timeout_msg
            except Exception:
                pass
            return timeout_msg

        # Parse JSON result and format response
        result_text = await _format_sub_agent_result(output, model_display, max_turns, duration)
        return result_text + _get_default_chat_warning()

    except Exception as e:
        return f"Sub-agent error: {str(e)}"


# ============================================================================
# Helper functions for HTTP header integration
# ============================================================================

def set_context_from_headers(headers: dict):
    """Set context variables from HTTP headers.

    Supports both direct headers (x-chat-id) and OpenWebUI headers (x-openwebui-chat-id).
    Direct headers take priority over OpenWebUI headers.
    """
    # Chat ID (required) - check both formats
    # Normalize to lowercase: Docker container names are case-sensitive,
    # and browser URLs may contain uppercase hex in UUIDs
    if "x-chat-id" in headers:
        current_chat_id.set(headers["x-chat-id"].lower())
    elif "x-openwebui-chat-id" in headers:
        current_chat_id.set(headers["x-openwebui-chat-id"].lower())

    # User email - check both formats
    if "x-user-email" in headers:
        current_user_email.set(headers["x-user-email"])
    elif "x-openwebui-user-email" in headers:
        current_user_email.set(headers["x-openwebui-user-email"])

    # User name - check both formats (URL-decode: client URL-encodes to handle non-ASCII)
    if "x-user-name" in headers:
        current_user_name.set(urllib.parse.unquote(headers["x-user-name"]))
    elif "x-openwebui-user-name" in headers:
        current_user_name.set(urllib.parse.unquote(headers["x-openwebui-user-name"]))

    # GitLab token - check both formats
    if "x-gitlab-token" in headers:
        current_gitlab_token.set(headers["x-gitlab-token"])
    elif "x-openwebui-gitlab-token" in headers:
        current_gitlab_token.set(headers["x-openwebui-gitlab-token"])

    # GitLab host - check both formats
    if "x-gitlab-host" in headers:
        current_gitlab_host.set(headers["x-gitlab-host"])
    elif "x-openwebui-gitlab-host" in headers:
        current_gitlab_host.set(headers["x-openwebui-gitlab-host"])

    # Anthropic API key - check both formats
    if "x-anthropic-api-key" in headers:
        current_anthropic_auth_token.set(headers["x-anthropic-api-key"])
    elif "x-openwebui-anthropic-api-key" in headers:
        current_anthropic_auth_token.set(headers["x-openwebui-anthropic-api-key"])

    # Anthropic base URL - check both formats
    if "x-anthropic-base-url" in headers:
        current_anthropic_base_url.set(headers["x-anthropic-base-url"])
    elif "x-openwebui-anthropic-base-url" in headers:
        current_anthropic_base_url.set(headers["x-openwebui-anthropic-base-url"])

    # MCP Tokens URL - check both formats
    if "x-mcp-tokens-url" in headers:
        current_mcp_tokens_url.set(headers["x-mcp-tokens-url"])
    elif "x-openwebui-mcp-tokens-url" in headers:
        current_mcp_tokens_url.set(headers["x-openwebui-mcp-tokens-url"])

    # MCP Tokens API key - check both formats
    if "x-mcp-tokens-api-key" in headers:
        current_mcp_tokens_api_key.set(headers["x-mcp-tokens-api-key"])
    elif "x-openwebui-mcp-tokens-api-key" in headers:
        current_mcp_tokens_api_key.set(headers["x-openwebui-mcp-tokens-api-key"])

    # MCP server names for sub-agent (comma-separated) - check both formats
    if "x-mcp-servers" in headers:
        current_mcp_servers.set(headers["x-mcp-servers"])
    elif "x-openwebui-mcp-servers" in headers:
        current_mcp_servers.set(headers["x-openwebui-mcp-servers"])


class MCPAuthMiddleware:
    """ASGI middleware for Bearer token auth on MCP endpoint."""

    def __init__(self, app, api_key: Optional[str] = None):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.api_key:
            await self.app(scope, receive, send)
            return

        # Extract Authorization header
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()

        if not auth.startswith("Bearer ") or auth[7:] != self.api_key:
            # Return 401 Unauthorized
            response_body = b'{"error": "Unauthorized"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
            })
            return

        await self.app(scope, receive, send)


class MCPContextMiddleware:
    """ASGI middleware: HTTP headers → ContextVars before MCP handler.

    Also pre-renders the system prompt and stores it in `current_instructions`
    so the _DynamicInstructionsServer.instructions property can read it
    synchronously when building InitializeResult (Tier 4).
    Rendering is cache-backed (60s TTL per (chat_id, user_email)), so real
    cost on a hot key is a dict lookup.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
            set_context_from_headers(headers)

            # Pre-render system prompt for Tier 4 (dynamic instructions).
            # Swallow errors — fall back to the static _STATIC_INSTRUCTIONS
            # string that the _DynamicInstructionsServer getter returns when
            # current_instructions is None.
            try:
                chat_id = current_chat_id.get()
                user_email = current_user_email.get()
                rendered = await render_system_prompt(chat_id, user_email)
                current_instructions.set(rendered)
            except Exception as e:
                print(f"[MCP] render_system_prompt warning: {e}")
        await self.app(scope, receive, send)


def get_mcp_app(api_key: Optional[str] = None):
    """Get the MCP ASGI app with auth and context middleware for mounting."""
    app = mcp.streamable_http_app()
    # Wrap with context middleware (inner) then auth (outer)
    app = MCPContextMiddleware(app)
    app = MCPAuthMiddleware(app, api_key=api_key)
    return app
