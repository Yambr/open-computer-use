# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Context variables for request-scoped data (set from HTTP headers)."""

from contextvars import ContextVar
from typing import Optional

current_chat_id: ContextVar[str] = ContextVar("current_chat_id", default="default")
current_user_email: ContextVar[Optional[str]] = ContextVar("current_user_email", default=None)
current_user_name: ContextVar[Optional[str]] = ContextVar("current_user_name", default=None)
current_gitlab_token: ContextVar[Optional[str]] = ContextVar("current_gitlab_token", default=None)
current_gitlab_host: ContextVar[str] = ContextVar("current_gitlab_host", default="gitlab.com")
current_anthropic_auth_token: ContextVar[Optional[str]] = ContextVar("current_anthropic_auth_token", default=None)
current_anthropic_base_url: ContextVar[Optional[str]] = ContextVar("current_anthropic_base_url", default=None)
current_mcp_tokens_url: ContextVar[str] = ContextVar("current_mcp_tokens_url", default="")
current_mcp_tokens_api_key: ContextVar[str] = ContextVar("current_mcp_tokens_api_key", default="")
current_mcp_servers: ContextVar[str] = ContextVar("current_mcp_servers", default="")

# Pre-rendered system prompt for this request. Set by MCPContextMiddleware
# after awaiting render_system_prompt(); read synchronously by the lowlevel
# Server's @property def instructions when building InitializeResult.
# See .venv/.../mcp/server/lowlevel/server.py:188 — that property must be
# sync, so we pre-compute the string here.
current_instructions: ContextVar[Optional[str]] = ContextVar("current_instructions", default=None)
