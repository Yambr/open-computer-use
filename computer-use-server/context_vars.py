"""Context variables for request-scoped data (set from HTTP headers)."""

from contextvars import ContextVar
from typing import Optional

current_chat_id: ContextVar[str] = ContextVar("current_chat_id", default="default")
current_user_email: ContextVar[Optional[str]] = ContextVar("current_user_email", default=None)
current_user_name: ContextVar[Optional[str]] = ContextVar("current_user_name", default=None)
current_gitlab_token: ContextVar[Optional[str]] = ContextVar("current_gitlab_token", default=None)
current_gitlab_host: ContextVar[str] = ContextVar("current_gitlab_host", default="gitlab.com")
current_anthropic_auth_token: ContextVar[Optional[str]] = ContextVar("current_anthropic_auth_token", default=None)
current_anthropic_base_url: ContextVar[str] = ContextVar("current_anthropic_base_url", default="https://api.anthropic.com/")
current_mcp_tokens_url: ContextVar[str] = ContextVar("current_mcp_tokens_url", default="")
current_mcp_tokens_api_key: ContextVar[str] = ContextVar("current_mcp_tokens_api_key", default="")
current_mcp_servers: ContextVar[str] = ContextVar("current_mcp_servers", default="")
