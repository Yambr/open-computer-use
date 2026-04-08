# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Docker container management for Computer Use.

Handles:
- Docker client initialization (local socket)
- Container lifecycle (get/create/start)
- Network management (compose network, CDP proxy)
- Command execution (bash, python with stdin)
- Shutdown timer (idle timeout)

Extracted from mcp_tools.py to reduce file size and separate concerns.
"""

import os
import re
import json
import shlex
import time
import datetime
from pathlib import Path
from typing import Optional

import aiohttp
import docker
from docker.utils.socket import frames_iter, demux_adaptor, consume_socket_output

import skill_manager
from context_vars import (
    current_chat_id, current_user_email, current_user_name,
    current_gitlab_token, current_gitlab_host,
    current_anthropic_auth_token, current_anthropic_base_url,
    current_mcp_tokens_url, current_mcp_tokens_api_key, current_mcp_servers,
)

DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "unix:///var/run/docker.sock")
DOCKER_IMAGE = os.getenv("DOCKER_IMAGE", "open-computer-use:latest")
CONTAINER_MEM_LIMIT = os.getenv("CONTAINER_MEM_LIMIT", "2g")
CONTAINER_CPU_LIMIT = float(os.getenv("CONTAINER_CPU_LIMIT", "1.0"))
COMMAND_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", "120"))
ENABLE_NETWORK = os.getenv("ENABLE_NETWORK", "true").lower() == "true"
USER_DATA_BASE_PATH = os.getenv("USER_DATA_BASE_PATH", "/tmp/computer-use-data")
FILE_SERVER_URL = os.getenv("FILE_SERVER_URL", "http://computer-use-server:8081")
CONTAINER_IDLE_TIMEOUT = int(os.getenv("CONTAINER_IDLE_TIMEOUT", "600"))
DEBUG_LOGGING = os.getenv("DEBUG_LOGGING", "false").lower() == "true"
ORCHESTRATOR_CONTAINER_NAME = os.getenv("ORCHESTRATOR_CONTAINER_NAME", "computer-use-server")
BASE_DATA_DIR = Path(os.getenv("BASE_DATA_DIR", "/data"))

# MCP Tokens Wrapper for GitLab token fetching
MCP_TOKENS_URL = os.getenv("MCP_TOKENS_URL", "")
MCP_TOKENS_API_KEY = os.getenv("MCP_TOKENS_API_KEY", "")

# Sub-agent configuration
SUB_AGENT_DEFAULT_MODEL = os.getenv("SUB_AGENT_DEFAULT_MODEL", "sonnet")
SUB_AGENT_MAX_TURNS = int(os.getenv("SUB_AGENT_MAX_TURNS", "50"))
SUB_AGENT_TIMEOUT = int(os.getenv("SUB_AGENT_TIMEOUT", "3600"))

# Claude Code model ID overrides (supports LiteLLM/Azure Foundry model IDs)
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "")
ANTHROPIC_DEFAULT_SONNET_MODEL = os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "")
ANTHROPIC_DEFAULT_OPUS_MODEL = os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL", "")
ANTHROPIC_DEFAULT_HAIKU_MODEL = os.getenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "")
CLAUDE_CODE_SUBAGENT_MODEL = os.getenv("CLAUDE_CODE_SUBAGENT_MODEL", "")

# Claude Code gateway compatibility flags
CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS = os.getenv("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "")
DISABLE_PROMPT_CACHING = os.getenv("DISABLE_PROMPT_CACHING", "")
DISABLE_PROMPT_CACHING_SONNET = os.getenv("DISABLE_PROMPT_CACHING_SONNET", "")
DISABLE_PROMPT_CACHING_OPUS = os.getenv("DISABLE_PROMPT_CACHING_OPUS", "")
DISABLE_PROMPT_CACHING_HAIKU = os.getenv("DISABLE_PROMPT_CACHING_HAIKU", "")

# Anthropic API (shared LiteLLM proxy key — fallback when no header provided)
ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

# Vision API for describe-image / upd-processing skills
VISION_API_KEY = os.getenv("VISION_API_KEY", "")
VISION_API_URL = os.getenv("VISION_API_URL", "")
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o")
