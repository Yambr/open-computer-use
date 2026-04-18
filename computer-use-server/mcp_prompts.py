# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Tier 5 — Native MCP `prompts` primitive exposing the Computer Use system prompt.

Clients can call `prompts/list` to discover `system`, then `prompts/get("system", {...})`
to fetch the rendered text. OpenAI Agents SDK's documented fallback path:

    server = MCPServerStreamableHttp(...)
    result = await server.get_prompt("system", {"chat_id": "demo"})
    agent = Agent(instructions=result.messages[0].content.text, mcp_servers=[server])

Header priority (consistent with the HTTP /system-prompt endpoint):
  request header (via ContextVars, already populated by MCPContextMiddleware)
  > explicit argument
  > "default".

Role is `user` because MCP spec restricts PromptMessage.role to {user, assistant}
(see .venv/.../mcp/server/fastmcp/prompts/base.py:25). The integrator feeds the
returned text into Agent.instructions where role is irrelevant.

Wired into the server by importing this module after `mcp` is defined — see
the `import mcp_prompts  # noqa: F401` in app.py.
"""

# FastMCP UserMessage lives in the `.base` submodule; the package `__init__`
# only re-exports Prompt + PromptManager (verified in
# .venv/.../mcp/server/fastmcp/prompts/__init__.py).
from mcp.server.fastmcp.prompts.base import UserMessage

from mcp_tools import mcp
from context_vars import current_chat_id, current_user_email
from system_prompt import render_system_prompt


@mcp.prompt(
    name="system",
    description="Computer Use system prompt for the current chat (per-session guide).",
)
async def system_prompt_prompt(
    chat_id: str | None = None,
    user_email: str | None = None,
) -> list[UserMessage]:
    """
    Return the rendered Computer Use system prompt as a single user-role message.

    Arguments are optional; when omitted we fall back to X-Chat-Id /
    X-User-Email headers (already in ContextVars). When both a header and an
    argument are present, the HEADER wins — same rule as the HTTP
    /system-prompt endpoint, so callers that set both don't get surprise
    asymmetry across delivery channels.
    """
    ctx_chat_id = current_chat_id.get()
    # current_chat_id has default="default" — treat that as "no header" so an
    # explicit chat_id argument can take effect in purely in-process calls.
    header_chat_id = ctx_chat_id if ctx_chat_id and ctx_chat_id != "default" else None
    effective_chat_id = header_chat_id or chat_id or "default"

    effective_user_email = current_user_email.get() or user_email

    text = await render_system_prompt(effective_chat_id, effective_user_email)
    return [UserMessage(content=text)]
