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
import sys
import re
import json
import shlex
import time
import datetime
from pathlib import Path
from types import SimpleNamespace
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
from system_prompt import render_system_prompt_sync

DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "unix:///var/run/docker.sock")
DOCKER_IMAGE = os.getenv("DOCKER_IMAGE", "open-computer-use:latest")
CONTAINER_MEM_LIMIT = os.getenv("CONTAINER_MEM_LIMIT", "2g")
CONTAINER_CPU_LIMIT = float(os.getenv("CONTAINER_CPU_LIMIT", "1.0"))
COMMAND_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", "120"))
ENABLE_NETWORK = os.getenv("ENABLE_NETWORK", "true").lower() == "true"
USER_DATA_BASE_PATH = os.getenv("USER_DATA_BASE_PATH", "/tmp/computer-use-data")
# Public URL of the orchestrator — the single source of truth for browser-facing
# preview/archive links. Baked into /system-prompt so the model writes correct
# clickable URLs, and returned to the Open WebUI filter via the X-Public-Base-URL
# response header so outlet() decorations also use it.
#
# Internal-DNS default is only reachable from inside the compose network. Users
# must override with a browser-reachable URL (http://localhost:8081 for local
# dev, https://cu.example.com for prod) for the preview panel to work.
# See docs/openwebui-filter.md.
PUBLIC_BASE_URL_DEFAULT = "http://computer-use-server:8081"
# Normalize: treat empty string as unset (docker-compose's `${VAR:-}` always sets
# the env var, so os.getenv's default only fires when VAR is truly absent —
# empty string would otherwise bypass the startup warning). Also strip any
# trailing slash so downstream concatenations never produce `//files/...`.
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or PUBLIC_BASE_URL_DEFAULT).rstrip("/")
CONTAINER_IDLE_TIMEOUT = int(os.getenv("CONTAINER_IDLE_TIMEOUT", "600"))
DEBUG_LOGGING = os.getenv("DEBUG_LOGGING", "false").lower() == "true"
ORCHESTRATOR_CONTAINER_NAME = os.getenv("ORCHESTRATOR_CONTAINER_NAME", "computer-use-server")
BASE_DATA_DIR = Path(os.getenv("BASE_DATA_DIR", "/data"))

# MCP Tokens Wrapper for GitLab token fetching
MCP_TOKENS_URL = os.getenv("MCP_TOKENS_URL", "")
MCP_TOKENS_API_KEY = os.getenv("MCP_TOKENS_API_KEY", "")

# Sub-agent configuration — per-CLI default models (D-03/D-04).
# The legacy single SUB_AGENT_DEFAULT_MODEL global was removed in Phase 2;
# the deprecation grace window from Phase 1 D-10 is over. The per-CLI env
# vars (CLAUDE_/CODEX_/OPENCODE_SUB_AGENT_DEFAULT_MODEL) are read directly
# by the resolver in cli_runtime.py — no module-level constants needed
# here. The resolver raises a clear ValueError when caller passes no model
# AND the per-CLI env is unset (opencode/codex only; claude falls back to
# the canonical 'sonnet' alias).
SUB_AGENT_MAX_TURNS = int(os.getenv("SUB_AGENT_MAX_TURNS", "25"))
SUB_AGENT_TIMEOUT = int(os.getenv("SUB_AGENT_TIMEOUT", "3600"))

# Anthropic API (shared LiteLLM proxy key — fallback when no header provided)
# NB: os.getenv falls back to the default only when the var is UNSET. In docker
# compose with `${VAR:-}` the var is always set to "", so treat empty == unset.
ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"

# Claude Code model ID overrides (pass through only when set on host — GATEWAY-02)
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "")
ANTHROPIC_DEFAULT_SONNET_MODEL = os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "")
ANTHROPIC_DEFAULT_OPUS_MODEL = os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL", "")
ANTHROPIC_DEFAULT_HAIKU_MODEL = os.getenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "")
CLAUDE_CODE_SUBAGENT_MODEL = os.getenv("CLAUDE_CODE_SUBAGENT_MODEL", "")
# Claude Code gateway compatibility flags (set to "1" to disable — GATEWAY-02)
CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS = os.getenv("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "")
DISABLE_PROMPT_CACHING = os.getenv("DISABLE_PROMPT_CACHING", "")
DISABLE_PROMPT_CACHING_SONNET = os.getenv("DISABLE_PROMPT_CACHING_SONNET", "")
DISABLE_PROMPT_CACHING_OPUS = os.getenv("DISABLE_PROMPT_CACHING_OPUS", "")
DISABLE_PROMPT_CACHING_HAIKU = os.getenv("DISABLE_PROMPT_CACHING_HAIKU", "")

# Tuple (not dict) for deterministic iteration order in tests — GATEWAY-03.
CLAUDE_CODE_PASSTHROUGH_ENVS = (
    ("ANTHROPIC_MODEL", ANTHROPIC_MODEL),
    ("ANTHROPIC_DEFAULT_SONNET_MODEL", ANTHROPIC_DEFAULT_SONNET_MODEL),
    ("ANTHROPIC_DEFAULT_OPUS_MODEL", ANTHROPIC_DEFAULT_OPUS_MODEL),
    ("ANTHROPIC_DEFAULT_HAIKU_MODEL", ANTHROPIC_DEFAULT_HAIKU_MODEL),
    ("CLAUDE_CODE_SUBAGENT_MODEL", CLAUDE_CODE_SUBAGENT_MODEL),
    ("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS),
    ("DISABLE_PROMPT_CACHING", DISABLE_PROMPT_CACHING),
    ("DISABLE_PROMPT_CACHING_SONNET", DISABLE_PROMPT_CACHING_SONNET),
    ("DISABLE_PROMPT_CACHING_OPUS", DISABLE_PROMPT_CACHING_OPUS),
    ("DISABLE_PROMPT_CACHING_HAIKU", DISABLE_PROMPT_CACHING_HAIKU),
)

# Codex passthrough envs (Phase 6 — only injected when SUBAGENT_CLI=codex).
# Per AUTH-01 — closes Pitfall 1 (auth bleed across CLIs).
CODEX_PASSTHROUGH_ENVS = (
    ("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "")),
    ("OPENAI_BASE_URL", os.getenv("OPENAI_BASE_URL", "")),
    ("CODEX_MODEL", os.getenv("CODEX_MODEL", "")),
    ("AZURE_OPENAI_API_KEY", os.getenv("AZURE_OPENAI_API_KEY", "")),
    ("AZURE_OPENAI_ENDPOINT", os.getenv("AZURE_OPENAI_ENDPOINT", "")),
    ("AZURE_OPENAI_API_VERSION", os.getenv("AZURE_OPENAI_API_VERSION", "")),
    # Operator-supplied codex config override (see docs/cli-config-templates.md
    # "Codex — custom OpenAI-compat gateway" recipe). Appended to the canonical
    # ~/.codex/config.toml block by the Dockerfile entrypoint when set, so
    # operators can route codex through a self-hosted gateway without forking.
    # Without this entry the override never crosses the orchestrator → sandbox
    # boundary. Same gap as #77; included here for codex parity.
    ("CODEX_CONFIG_EXTRA", os.getenv("CODEX_CONFIG_EXTRA", "")),
)

# OpenCode passthrough envs (Phase 6 — only injected when SUBAGENT_CLI=opencode).
# Includes OPENAI_API_KEY and ANTHROPIC_API_KEY because OpenCode itself supports
# multiple providers; the allowlist is per-CLI, not per-provider.
OPENCODE_PASSTHROUGH_ENVS = (
    ("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", "")),
    ("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "")),
    ("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", "")),
    ("OPENCODE_MODEL", os.getenv("OPENCODE_MODEL", "")),
    # Operator-supplied OpenCode config override (see docs/cli-config-templates.md
    # "OpenCode — custom OpenAI-compat provider" recipe). Replaces /tmp/opencode.json
    # verbatim when set, so operators can route the opencode sub-agent through a
    # self-hosted gateway (LiteLLM, OpenLLM, etc.) for proxy-only deployments.
    # Without this entry the override never crosses the orchestrator → sandbox
    # boundary and the entrypoint heredoc falls through to the canonical
    # 3-provider default. Closes #77.
    ("OPENCODE_CONFIG_EXTRA", os.getenv("OPENCODE_CONFIG_EXTRA", "")),
)

# Sub-agent CLI runtime selector (CLI-01, CLI-02). Read once at module load
# and propagated to every spawned container via extra_env (D5 shape a).
# Empty/unset → "claude" (backwards-compat invariant). Invalid value → hard
# fail at module load (D1) so a typo in .env is visible in the very first
# `docker compose up` log line, never silently runs the wrong CLI.
_ALLOWED_CLIS = {"claude", "codex", "opencode"}
_raw_subagent_cli = os.getenv("SUBAGENT_CLI", "").strip().lower()
if _raw_subagent_cli and _raw_subagent_cli not in _ALLOWED_CLIS:
    print(
        f"[computer-use-server] FATAL: SUBAGENT_CLI={_raw_subagent_cli!r} "
        f"is not one of {{claude, codex, opencode}}.",
        file=sys.stderr,
    )
    sys.exit(1)
SUBAGENT_CLI = _raw_subagent_cli or "claude"

# Active passthrough set selected by SUBAGENT_CLI — AUTH-01 / Pitfall 1.
# Single source of truth for "which auth env vars cross the orchestrator->sandbox
# boundary for this runtime". `_create_container` reads this once per container.
_PASSTHROUGH_BY_CLI = {
    "claude": CLAUDE_CODE_PASSTHROUGH_ENVS,
    "codex": CODEX_PASSTHROUGH_ENVS,
    "opencode": OPENCODE_PASSTHROUGH_ENVS,
}

# Vision API for describe-image / upd-processing skills
VISION_API_KEY = os.getenv("VISION_API_KEY", "")
VISION_API_URL = os.getenv("VISION_API_URL", "")
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o")


def warn_if_public_base_url_is_default() -> bool:
    """Emit a one-time startup warning when PUBLIC_BASE_URL is still the
    hardcoded internal-DNS default.

    The default (http://computer-use-server:8081) is only reachable from inside
    the compose network. Since the public URL is now baked into /system-prompt
    and returned to the filter via response header, a default value means the
    preview panel will never appear — the browser cannot resolve the internal
    DNS name.

    Returns True if a warning was emitted (useful for tests), False otherwise.
    Called once from FastAPI lifespan startup — do not call per-request.
    """
    if PUBLIC_BASE_URL == PUBLIC_BASE_URL_DEFAULT:
        print(
            "[computer-use-server] WARNING: PUBLIC_BASE_URL is still the "
            f"hardcoded default ({PUBLIC_BASE_URL_DEFAULT!r}). This URL is only "
            "reachable from inside the compose network — the Open WebUI preview "
            "panel will never appear until you set it to a browser-reachable URL.\n"
            "  Fix: in .env, set PUBLIC_BASE_URL=http://<browser-reachable-host>:8081.\n"
            "  Docs: https://github.com/Yambr/open-computer-use/blob/main/docs/openwebui-filter.md"
        )
        return True
    return False


def warn_if_mcp_api_key_missing() -> bool:
    """Emit a one-time startup warning when MCP_API_KEY is empty.

    An empty MCP_API_KEY makes every /mcp endpoint publicly callable without
    authentication — fine for local dev, dangerous for any deployment the
    internet can reach. Warn loudly so the condition does not silently survive
    a prod rollout.

    Returns True if a warning was emitted (useful for tests), False otherwise.
    Called once from FastAPI lifespan startup — do not call per-request.
    """
    if not os.getenv("MCP_API_KEY", ""):
        print(
            "[computer-use-server] WARNING: MCP_API_KEY is empty — the /mcp "
            "endpoints accept ANY caller with no auth. Acceptable for local "
            "development, unsafe for anything reachable from the internet.\n"
            "  Fix: set MCP_API_KEY in .env to a long random string and mirror "
            "it in the Open WebUI tool Valve (Admin → Tools → Computer Use → "
            "Valves → MCP_API_KEY)."
        )
        return True
    return False


def warn_subagent_cli() -> bool:
    """Emit a one-line banner naming the active sub-agent CLI runtime.

    Always prints (informational, not gated on a default) so operators have
    visible confirmation that SUBAGENT_CLI took effect after a docker compose
    restart. Mirrors warn_if_public_base_url_is_default's bool-return
    contract so app.py lifespan can collect emission flags for future
    telemetry. Closes the UX gap from PITFALLS.md UX table row 1.

    Returns True (always emitted, kept for symmetry with sibling warn_*).
    Called once from FastAPI lifespan startup — do not call per-request.
    """
    print(f"[MCP] Sub-agent runtime: {SUBAGENT_CLI}")
    return True


async def _fetch_gitlab_token(email: str, mcp_tokens_url: str, mcp_tokens_api_key: str) -> Optional[str]:
    """
    Fetch decrypted GitLab token from MCP Tokens Wrapper service.

    Args:
        email: User email address
        mcp_tokens_url: URL of MCP Tokens Wrapper service
        mcp_tokens_api_key: Internal API key for authentication

    Returns:
        GitLab token string or None if not found/error
    """
    if not mcp_tokens_api_key:
        print("[GITLAB] MCP_TOKENS_API_KEY not configured, skipping token fetch")
        return None

    if not email:
        print("[GITLAB] No email provided, skipping token fetch")
        return None

    url = f"{mcp_tokens_url}/api/internal/tokens/{email}/gitlab"
    headers = {"X-Internal-Api-Key": mcp_tokens_api_key}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    data = await response.json()
                    token = data.get("token")
                    if token:
                        print(f"[GITLAB] Token fetched for {email}")
                        return token
                elif response.status == 404:
                    print(f"[GITLAB] No token found for {email}")
                else:
                    print(f"[GITLAB] Error fetching token: HTTP {response.status}")
    except asyncio.TimeoutError:
        print(f"[GITLAB] Timeout fetching token for {email}")
    except Exception as e:
        print(f"[GITLAB] Error fetching token: {e}")

async def _ensure_gitlab_token():
    """
    Ensure GitLab token is available, fetching from MCP Tokens Wrapper if needed.

    Priority:
    1. Token from header (current_gitlab_token already set)
    2. Fetch from MCP Tokens Wrapper by user email
    3. No token (continue without GitLab auth)
    """
    # If token already set from header, use it
    if current_gitlab_token.get():
        return

    # Try to fetch from MCP Tokens Wrapper
    user_email = current_user_email.get()
    mcp_tokens_url = current_mcp_tokens_url.get() or MCP_TOKENS_URL
    mcp_tokens_api_key = current_mcp_tokens_api_key.get() or MCP_TOKENS_API_KEY

    if user_email and mcp_tokens_url and mcp_tokens_api_key:
        token = await _fetch_gitlab_token(user_email, mcp_tokens_url, mcp_tokens_api_key)
        if token:
            current_gitlab_token.set(token)



# Global Docker client (lazy init)
_docker_client: Optional[docker.DockerClient] = None



def build_mcp_config(server_names_csv: str, base_url: Optional[str], user_email: str = "") -> dict | None:
    """Build Claude Code ~/.mcp.json config from comma-separated server names.

    URLs are templated as {base_url}/mcp/{server_name} (LiteLLM MCP proxy pattern).
    Authorization uses ANTHROPIC_AUTH_TOKEN env var (resolved inside container at write time).

    Returns dict ready for json.dumps, or None if no servers specified.

    ``base_url`` may be None or empty; both fall back to the module-level
    ANTHROPIC_BASE_URL constant so callers can pass the ContextVar value
    directly without a manual fallback.
    """
    # Blocklist: prevent recursive sub_agent loops
    BLOCKED_SERVERS = {"docker_ai", "docker-ai"}

    names = [s.strip() for s in server_names_csv.split(",") if s.strip() and s.strip() not in BLOCKED_SERVERS]
    if not names:
        return None

    base = (base_url or ANTHROPIC_BASE_URL or "https://api.anthropic.com").rstrip("/")
    servers = {}
    for name in names:
        servers[name] = {
            "type": "http",
            "url": f"{base}/mcp/{name}",
            "headers": {
                "x-openwebui-user-email": user_email,
            },
        }
    return {"mcpServers": servers}


def build_mcp_config_write_script(mcp_config: dict) -> str:
    """Build a shell command that writes ~/.mcp.json inside a container.

    ANTHROPIC_AUTH_TOKEN is resolved from the container's env at runtime,
    so no secrets are baked into the script itself.
    Uses base64 to avoid shell/JSON escaping issues.
    """
    import base64
    config_b64 = base64.b64encode(json.dumps(mcp_config).encode()).decode()
    return (
        f"python3 -c '"
        f"import json,os,base64;"
        f"c=json.loads(base64.b64decode(\"{config_b64}\"));"
        f"k=os.environ.get(\"ANTHROPIC_AUTH_TOKEN\",\"\");"
        f"[s[\"headers\"].__setitem__(\"Authorization\",\"Bearer \"+k)"
        f" for s in c[\"mcpServers\"].values() if \"headers\" in s];"
        f"json.dump(c,open(os.path.expanduser(\"~/.mcp.json\"),\"w\"),indent=2);"
        # Auto-approve MCP servers in settings.local.json so Claude Code doesn't ask
        f"p=os.path.expanduser(\"~/.claude/settings.local.json\");"
        f"sl=json.load(open(p)) if os.path.exists(p) else {{}};"
        f"sl[\"enabledMcpjsonServers\"]=list(c[\"mcpServers\"].keys());"
        f"json.dump(sl,open(p,\"w\"),indent=2)"
        f"'"
    )


def get_docker_client() -> docker.DockerClient:
    """Get or create Docker client connected to local socket."""
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.DockerClient(base_url=DOCKER_SOCKET)
        _docker_client.ping()
        print(f"[MCP] Connected to Docker at {DOCKER_SOCKET}")
    return _docker_client


def _build_container_env(extra_env: Optional[dict] = None) -> dict:
    """Build environment variables dict for container."""
    env = {
        "NPM_CONFIG_PREFIX": "/usr/local/lib/node_modules_global",
    }
    if extra_env:
        env.update(extra_env)
    return env


# Cached compose network name (detected once, reused)
_compose_network_name: Optional[str] = None


def _get_compose_network_name(force_refresh: bool = False) -> Optional[str]:
    """Find the Docker compose network that computer-use-orchestrator is on (for CDP proxy access)."""
    global _compose_network_name
    if _compose_network_name is not None and not force_refresh:
        return _compose_network_name

    client = get_docker_client()
    try:
        fs = client.containers.get(ORCHESTRATOR_CONTAINER_NAME)
        fs.reload()
        for name in fs.attrs["NetworkSettings"]["Networks"]:
            if name != "bridge":
                _compose_network_name = name
                print(f"[MCP] Detected compose network: {name}")
                return name
    except Exception as e:
        print(f"[MCP] Could not detect compose network: {e}")
    return None


def get_container_cdp_address(chat_id: str) -> Optional[str]:
    """Get the IP address of a chat's container on the compose network (for CDP proxy).

    After deploy (docker-compose down/up), running containers may still be on the
    old compose network with an unreachable IP. This function detects the mismatch
    and reconnects the container to the current compose network.
    """
    chat_id = chat_id.lower()
    client = get_docker_client()
    sanitized_id = re.sub(r'[^a-zA-Z0-9_.-]', '-', chat_id)
    container_name = f"owui-chat-{sanitized_id}"
    try:
        c = client.containers.get(container_name)
        c.reload()
        if c.status != "running":
            return None

        compose_net = _get_compose_network_name()
        networks = c.attrs["NetworkSettings"]["Networks"]

        # If container is on the current compose network, use that IP
        if compose_net and compose_net in networks:
            ip = networks[compose_net].get("IPAddress")
            if ip:
                return ip

        # Container running but NOT on compose network → fix and retry
        if compose_net and compose_net not in networks:
            print(f"[MCP] {container_name} not on compose network {compose_net}, reconnecting...")
            _fix_dead_networks(client, c)
            c.reload()
            networks = c.attrs["NetworkSettings"]["Networks"]
            if compose_net in networks:
                ip = networks[compose_net].get("IPAddress")
                if ip:
                    return ip

        # Fallback: first non-bridge IP
        for net_name, net_data in networks.items():
            if net_name != "bridge" and net_data.get("IPAddress"):
                return net_data["IPAddress"]
        ip = c.attrs["NetworkSettings"]["IPAddress"]
        return ip if ip else None
    except Exception:
        return None


def _fix_dead_networks(client, container):
    """Disconnect from dead networks and reconnect to compose network.

    After docker-compose down/up (deploy), networks are recreated with new IDs.
    Stopped containers still reference old (dead) networks, causing start() to fail.
    Same logic as restart-container endpoint in app.py.
    """
    try:
        container.reload()
        old_nets = list(container.attrs.get("NetworkSettings", {}).get("Networks", {}).keys())
        for net_name in old_nets:
            try:
                net = client.networks.get(net_name)
                net.disconnect(container, force=True)
            except Exception:
                pass  # Network already dead — ignore
        compose_net = _get_compose_network_name(force_refresh=True)
        if compose_net:
            try:
                net = client.networks.get(compose_net)
                net.connect(container)
            except Exception as e:
                print(f"[MCP] Warning: could not connect to {compose_net}: {e}")
    except Exception as e:
        print(f"[MCP] Warning: network fix failed: {e}")


def _get_or_create_container(chat_id: str) -> docker.models.containers.Container:
    """Get existing container or create new one for this chat."""
    chat_id = chat_id.lower()
    client = get_docker_client()

    # Sanitize chat_id for Docker container naming
    sanitized_id = re.sub(r'[^a-zA-Z0-9_.-]', '-', chat_id)
    container_name = f"owui-chat-{sanitized_id}"

    try:
        container = client.containers.get(container_name)
        container.reload()

        if container.status == "exited":
            _fix_dead_networks(client, container)
            container.start()
            print(f"[MCP] Started existing container: {container_name}")
        elif container.status == "running":
            if DEBUG_LOGGING:
                print(f"[MCP] Reusing running container: {container_name}")
        else:
            container.start()
            print(f"[MCP] Started container in state '{container.status}': {container_name}")

        return container

    except docker.errors.NotFound:
        print(f"[MCP] Creating new container: {container_name}")
        return _create_container(chat_id, container_name)


def _create_container(chat_id: str, container_name: str) -> docker.models.containers.Container:
    """Create a new persistent container for this chat."""
    client = get_docker_client()

    # Build extra env from context variables
    extra_env = {
        "GITLAB_HOST": current_gitlab_host.get(),
    }

    gitlab_token = current_gitlab_token.get()
    if gitlab_token:
        extra_env["GITLAB_TOKEN"] = gitlab_token
        print(f"[MCP] Injecting GITLAB_TOKEN into container environment")

    # Phase 3 gateway-path injection — only active when SUBAGENT_CLI=claude
    # (AUTH-01: no Anthropic gateway vars bleed into codex/opencode containers).
    if SUBAGENT_CLI == "claude":
        anthropic_key = current_anthropic_auth_token.get() or ANTHROPIC_AUTH_TOKEN
        anthropic_base = current_anthropic_base_url.get() or ANTHROPIC_BASE_URL
        if anthropic_key:
            extra_env["ANTHROPIC_AUTH_TOKEN"] = anthropic_key
            extra_env["ANTHROPIC_BASE_URL"] = anthropic_base

    # Inject only the active CLI's auth allowlist (AUTH-01 / Pitfall 1: no
    # auth bleed across CLIs — e.g. when SUBAGENT_CLI=opencode, OPENAI_API_KEY
    # and OPENROUTER_API_KEY land in extra_env but ANTHROPIC_* gateway vars
    # do NOT, even if set on the host).
    for _name, _value in _PASSTHROUGH_BY_CLI[SUBAGENT_CLI]:
        if _value:
            extra_env[_name] = _value

    # Sub-agent runtime selector (CLI-01) — propagated to every container so
    # the Phase 7 .bashrc autostart `exec "${SUBAGENT_CLI:-claude}"` can read it
    # and `docker inspect <sandbox>` shows the chosen runtime in Env.
    extra_env["SUBAGENT_CLI"] = SUBAGENT_CLI

    # OpenCode reads its config from $OPENCODE_CONFIG. Pin it to /tmp so docker
    # exec'd subprocesses (e.g. mcp_tools.sub_agent dispatch) inherit it — the
    # entrypoint `export OPENCODE_CONFIG=/tmp/opencode.json` only affects the
    # entrypoint shell session, NOT subsequent `docker exec` invocations.
    # Without this pin, OpenCode would fall back to ~/.local/share/opencode/auth.json
    # and reopen the Pitfall 7 leak vector. ROADMAP success #2: `docker inspect`
    # must show this env in the container Env.
    if SUBAGENT_CLI == "opencode":
        extra_env["OPENCODE_CONFIG"] = "/tmp/opencode.json"
        # Propagate request-scoped X-Anthropic-Api-Key into the env name OpenCode
        # expects (`{env:ANTHROPIC_API_KEY}` per docs/multi-cli.md and the
        # entrypoint heredoc in Dockerfile). Without this, header-authenticated
        # runs lose their credential when SUBAGENT_CLI=opencode because the claude
        # branch above is not active. Process-level ANTHROPIC_AUTH_TOKEN env is
        # the host-level fallback (covered by OPENCODE_PASSTHROUGH_ENVS — but the
        # request-scoped header path was missed). Per CodeRabbit PR#75 review.
        request_scoped_anthropic = current_anthropic_auth_token.get()
        if request_scoped_anthropic:
            extra_env["ANTHROPIC_API_KEY"] = request_scoped_anthropic

    # Vision API for describe-image / upd-processing skills
    if VISION_API_KEY:
        extra_env["VISION_API_KEY"] = VISION_API_KEY
        extra_env["VISION_API_URL"] = VISION_API_URL
        extra_env["VISION_MODEL"] = VISION_MODEL

    user_name = current_user_name.get()
    user_email = current_user_email.get()
    if user_name:
        extra_env["GIT_AUTHOR_NAME"] = user_name
        extra_env["GIT_COMMITTER_NAME"] = user_name
    if user_email:
        extra_env["GIT_AUTHOR_EMAIL"] = user_email
        extra_env["GIT_COMMITTER_EMAIL"] = user_email
        # Anthropic-specific custom header — only emit for the claude runtime
        # so codex / opencode containers do not get spurious anthropic env.
        if SUBAGENT_CLI == "claude":
            extra_env["ANTHROPIC_CUSTOM_HEADERS"] = f"x-openwebui-user-email: {user_email}"

    # Workspace volume for this chat
    workspace_volume = f"chat-{chat_id}-workspace"

    # Host paths for user data
    chat_data_path = os.path.join(USER_DATA_BASE_PATH, chat_id)
    uploads_path = os.path.join(chat_data_path, "uploads")
    outputs_path = os.path.join(chat_data_path, "outputs")

    # Create directories on Docker host with correct permissions
    try:
        print(f"[MCP] Creating directories: {uploads_path}, {outputs_path}")
        client.containers.run(
            image=DOCKER_IMAGE,
            command=f"bash -c 'mkdir -p {shlex.quote(uploads_path)} {shlex.quote(outputs_path)} && chmod -R 777 {shlex.quote(chat_data_path)}'",
            volumes={"/tmp": {"bind": "/tmp", "mode": "rw"}},
            remove=True,
            detach=False,
            user="root"
        )
    except Exception as e:
        print(f"[MCP] Warning: Failed to create directories: {e}")

    # Check if using custom image (has entrypoint) or standard image
    use_entrypoint = "computer-use" in DOCKER_IMAGE or "open-computer-use" in DOCKER_IMAGE

    if use_entrypoint:
        # Production: use entrypoint script
        command = ["bash", "-c", "/home/assistant/.entrypoint.sh bash -c 'trap \"exit 0\" SIGTERM SIGINT; tail -f /dev/null & wait $!'"]
        working_dir = "/home/assistant"
        user = "assistant:assistant"
    else:
        # Development/test: simple bash loop
        command = ["bash", "-c", "trap 'exit 0' SIGTERM SIGINT; tail -f /dev/null & wait $!"]
        working_dir = "/root"
        user = None  # Use image default

    config = {
        "image": DOCKER_IMAGE,
        "name": container_name,
        "hostname": f"chat-{chat_id[:8]}",
        "command": command,
        "detach": True,
        "stdin_open": True,
        "tty": True,
        "mem_limit": CONTAINER_MEM_LIMIT,
        "nano_cpus": int(CONTAINER_CPU_LIMIT * 1_000_000_000),
        "working_dir": working_dir,
        "environment": _build_container_env(extra_env),
        "volumes": {
            workspace_volume: {"bind": working_dir, "mode": "rw"},
            uploads_path: {"bind": "/mnt/user-data/uploads", "mode": "ro"},
            outputs_path: {"bind": "/mnt/user-data/outputs", "mode": "rw"},
            **skill_manager.get_skill_mounts(
                skill_manager.get_user_skills_sync(current_user_email.get())
            ),
        },
        "labels": {
            "managed-by": "mcp-computer-use-orchestrator",
            "chat-id": chat_id,
            "tool": "computer-use-mcp"
        },
        "security_opt": ["no-new-privileges:true"],
    }

    if user:
        config["user"] = user

    if not ENABLE_NETWORK:
        config["network_disabled"] = True

    try:
        container = client.containers.create(**config)
    except docker.errors.APIError as e:
        if e.status_code == 409:
            # Container name exists (stale after deploy) — remove and retry
            print(f"[MCP] [409] Removing stale container: {container_name}")
            try:
                old = client.containers.get(container_name)
                old.remove(force=True)
            except Exception:
                pass
            container = client.containers.create(**config)
        else:
            raise
    container.start()

    # Connect to compose network so computer-use-orchestrator can proxy CDP (port 9222) to this container
    try:
        compose_net = _get_compose_network_name()
        if compose_net:
            client.networks.get(compose_net).connect(container)
            if DEBUG_LOGGING:
                print(f"[MCP] Connected {container_name} to network {compose_net}")
    except Exception as e:
        print(f"[MCP] Warning: Could not connect to compose network: {e}")

    print(f"[MCP] Created and started new container: {container_name}")

    # Save metadata for resurrection after container removal by cron
    save_container_meta(
        chat_id,
        current_user_email.get(),
        current_user_name.get(),
        current_mcp_servers.get(),
    )

    # Write MCP config on creation so terminal users have it immediately
    try:
        mcp_servers_str = current_mcp_servers.get()
        if mcp_servers_str:
            mcp_cfg = build_mcp_config(
                mcp_servers_str,
                current_anthropic_base_url.get(),
                current_user_email.get() or "",
            )
            if mcp_cfg:
                write_cmd = build_mcp_config_write_script(mcp_cfg)
                _execute_bash(container, write_cmd, 15)
                print(f"[MCP] Wrote MCP config on container creation: {mcp_servers_str}")
    except Exception as e:
        print(f"[MCP] Warning: MCP setup on create failed: {e}")

    # Tier 2 — write /home/assistant/README.md with the rendered system prompt
    # so the model can always recover its environment via `view` regardless of
    # what the client did (or didn't do) with prompts/get and InitializeResult.
    #
    # Safe to call asyncio.run here: _create_container runs inside
    # asyncio.to_thread (see all call sites in mcp_tools.py) → worker thread
    # with no running event loop → no nested-loop error.
    try:
        _, workdir = _get_container_user_and_workdir()
        readme_text = render_system_prompt_sync(chat_id, current_user_email.get())
        _write_file_to_container(container, workdir, "README.md", readme_text)
        print(f"[MCP] Wrote {workdir}/README.md ({len(readme_text)} chars)")
    except Exception as e:
        print(f"[MCP] Warning: README.md write failed: {e}")

    # Tier 6 — initial sync of uploaded files into MCP resources registry.
    # Lazy import to avoid circular (mcp_resources → mcp_tools → docker_manager).
    try:
        from mcp_resources import sync_chat_resources_sync
        n = sync_chat_resources_sync(chat_id)
        if n:
            print(f"[MCP] Registered {n} upload resource(s) for chat {chat_id}")
    except Exception as e:
        print(f"[MCP] Warning: MCP resources sync failed: {e}")

    # Pitfall 7 defense — scrub OpenCode auth.json from volume on container
    # creation (handles resurrected containers from previous opencode-auth-login
    # experiments). Best-effort — silent on failure (absence is normal).
    try:
        container.exec_run(
            "rm -f /home/assistant/.local/share/opencode/auth.json",
            user="assistant",
        )
    except Exception:
        pass

    return container


def _write_file_to_container(container, dirpath: str, filename: str, text: str) -> None:
    """
    Write a UTF-8 text file into the container at `dirpath/filename` using
    Docker's put_archive API. Cleaner than `exec cat > file` — no shell
    escaping, no interference from shell initialisation.
    """
    import io, tarfile, time as _t
    data = text.encode("utf-8")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=filename)
        info.size = len(data)
        info.mtime = int(_t.time())
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    # put_archive returns False on extraction failure (e.g. dirpath does not
    # exist) and True on success. Without this check the caller logs success
    # even though the file was never written. APIError still propagates as
    # an exception per docker-py docs.
    if not container.put_archive(dirpath, buf.getvalue()):
        raise RuntimeError(
            f"put_archive returned False writing {dirpath}/{filename} "
            f"to container {container.short_id} — target dir may not exist"
        )


def _get_container_user_and_workdir() -> tuple:
    """Get user and workdir based on Docker image type."""
    use_entrypoint = "computer-use" in DOCKER_IMAGE or "open-computer-use" in DOCKER_IMAGE
    if use_entrypoint:
        return "assistant", "/home/assistant"
    else:
        return None, "/root"  # None = use container default


def _reset_shutdown_timer(container, timeout: int = None):
    """Reset container auto-shutdown timer.

    Args:
        container: Docker container instance
        timeout: Custom timeout in seconds. If None, uses CONTAINER_IDLE_TIMEOUT.
                 Used by long-running commands (e.g. sub_agent) to prevent
                 the idle timer from killing the container mid-execution.
    """
    user, _ = _get_container_user_and_workdir()
    exec_kwargs = {} if user is None else {"user": user}

    effective_timeout = timeout if timeout else CONTAINER_IDLE_TIMEOUT

    # Atomic timer reset: flock serializes concurrent resets so only one timer exists.
    # The outer bash PID (MYPID=$$) is tracked in the file.
    # When a new reset arrives: kill children (sleep) FIRST, then the bash parent.
    # Order matters: killing bash first reparents sleep to PID 1, making pkill -P miss it.
    # flock is released before sleep starts, so it doesn't block future resets.
    timer_cmd = (
        f"bash -c '"
        f"MYPID=$$; "
        f"(flock -x 9; "
        f"OLD=$(cat /tmp/.shutdown-timer-pid 2>/dev/null); "
        f'[ -n "$OLD" ] && pkill -P "$OLD" 2>/dev/null; '
        f'[ -n "$OLD" ] && kill "$OLD" 2>/dev/null; '
        f"echo $MYPID > /tmp/.shutdown-timer-pid"
        f") 9>/tmp/.shutdown-timer-lock; "
        f"sleep {effective_timeout} && kill 1"
        f"'"
    )
    container.exec_run(timer_cmd, detach=True, **exec_kwargs)


def _execute_bash(container, command: str, timeout: int = None) -> dict:
    """Execute bash command in container with timeout."""
    user, workdir = _get_container_user_and_workdir()

    try:
        cmd_timeout = timeout if timeout is not None else COMMAND_TIMEOUT
        # Ensure shutdown timer won't kill container before command finishes
        shutdown_timeout = max(CONTAINER_IDLE_TIMEOUT, cmd_timeout + 60)
        _reset_shutdown_timer(container, shutdown_timeout)
        timed_command = f"timeout {cmd_timeout} bash -c {shlex.quote(command)}"

        exec_result = container.exec_run(
            cmd=["bash", "-c", timed_command],
            stdout=True,
            stderr=True,
            demux=True,
            workdir=workdir
        )

        stdout_data, stderr_data = exec_result.output if exec_result.output else (b"", b"")
        stdout = stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
        stderr = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""

        output = ""
        if stdout:
            output += stdout
        if stderr:
            if output:
                output += "\n"
            output += stderr

        if exec_result.exit_code == 124:
            output += f"\n[Command timed out after {cmd_timeout} seconds]"

        return {
            "exit_code": exec_result.exit_code,
            "output": output,
            "success": exec_result.exit_code == 0
        }

    except Exception as e:
        return {
            "exit_code": -1,
            "output": f"Execution error: {str(e)}",
            "success": False
        }


# ---------------------------------------------------------------------------
# ADAPT-05 / Phase 5: capture variant of _execute_bash.
#
# _execute_bash returns {output, exit_code, success} where stdout+stderr are
# concatenated. Adapter parse_result(stdout, stderr, returncode) needs them
# separated, so cli_runtime.dispatch uses this helper instead. Same docker
# exec semantics (timeout, shutdown-timer reset, demux=True), different
# return shape.
#
# Returns a SimpleNamespace so callers can do `.stdout`, `.stderr`,
# `.returncode` (matches subprocess.CompletedProcess shape — adapter parsers
# are written against that idiom). SimpleNamespace is imported at the top of
# the module (PEP 8 — do NOT inline the import here).
# ---------------------------------------------------------------------------
def _execute_bash_capture(container, command: str, timeout: int = None):
    """Execute bash in container; return SimpleNamespace(stdout, stderr, returncode).

    Stdout/stderr are kept separate (unlike _execute_bash which concatenates).
    Used by cli_runtime.dispatch to feed adapter.parse_result, which is
    written against the subprocess.CompletedProcess (stdout, stderr,
    returncode) shape.

    SECURITY (Phase 5 threat model T-05-05-01): the `command` argument is
    passed straight to bash -c via shlex.quote — caller is responsible for
    having shlex.quote'd every shell-significant value. cli_runtime.dispatch
    constructs the command from `shlex.quote`'d argv elements; do not call
    this helper with operator-controlled raw strings.
    """
    user, workdir = _get_container_user_and_workdir()
    try:
        cmd_timeout = timeout if timeout is not None else COMMAND_TIMEOUT
        shutdown_timeout = max(CONTAINER_IDLE_TIMEOUT, cmd_timeout + 60)
        _reset_shutdown_timer(container, shutdown_timeout)
        timed_command = f"timeout {cmd_timeout} bash -c {shlex.quote(command)}"

        exec_result = container.exec_run(
            cmd=["bash", "-c", timed_command],
            stdout=True,
            stderr=True,
            demux=True,
            workdir=workdir,
        )

        stdout_data, stderr_data = exec_result.output if exec_result.output else (b"", b"")
        stdout = stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
        stderr = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""

        return SimpleNamespace(
            stdout=stdout,
            stderr=stderr,
            returncode=exec_result.exit_code,
        )
    except Exception as e:
        return SimpleNamespace(
            stdout="",
            stderr=f"Execution error: {str(e)}",
            returncode=-1,
        )


def execute_bash_streaming(container, command: str, timeout: int, on_output_line=None) -> dict:
    """Execute bash in container with streaming output.

    Calls on_output_line(line) for each non-empty output line as it arrives.
    Returns dict with output (full text), exit_code, success.
    """
    user, workdir = _get_container_user_and_workdir()
    try:
        cmd_timeout = timeout - 5 if timeout > 10 else timeout
        shutdown_timeout = max(CONTAINER_IDLE_TIMEOUT, cmd_timeout + 60)
        _reset_shutdown_timer(container, shutdown_timeout)

        timed_command = f"timeout {cmd_timeout} bash -c {shlex.quote(command)}"
        client = container.client

        exec_id = client.api.exec_create(
            container.id,
            ["bash", "-c", timed_command],
            stdout=True,
            stderr=True,
            workdir=workdir,
        )["Id"]

        chunks = []
        remainder = ""
        for chunk in client.api.exec_start(exec_id, stream=True):
            decoded = chunk.decode("utf-8", errors="replace")
            chunks.append(decoded)
            if on_output_line:
                lines = (remainder + decoded).split("\n")
                remainder = lines[-1]
                for line in lines[:-1]:
                    stripped = line.strip()
                    if stripped:
                        on_output_line(stripped[:120])

        if on_output_line and remainder.strip():
            on_output_line(remainder.strip()[:120])

        output = "".join(chunks)
        info = client.api.exec_inspect(exec_id)
        exit_code = info.get("ExitCode") or 0

        if exit_code == 124:
            output += f"\n[Command timed out after {cmd_timeout} seconds]"

        return {"output": output, "exit_code": exit_code, "success": exit_code == 0}

    except Exception as e:
        return {"exit_code": -1, "output": f"Execution error: {str(e)}", "success": False}


def _get_meta_path(chat_id: str) -> Path:
    """Path to .meta.json for this chat on the host filesystem."""
    from security import sanitize_chat_id
    chat_id = sanitize_chat_id(chat_id)
    return BASE_DATA_DIR / chat_id / ".meta.json"


def save_container_meta(chat_id: str, user_email: str, user_name: str,
                        mcp_servers: str):
    """Persist non-secret metadata needed to recreate a container after removal.

    NO secrets/tokens stored — they come from computer-use-orchestrator ENV at resurrect time.
    """
    meta = {
        "user_email": user_email or "",
        "user_name": user_name or "",
        "mcp_servers": mcp_servers or "",
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    meta_path = _get_meta_path(chat_id)
    try:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        print(f"[META] Saved metadata: {meta_path}")
    except Exception as e:
        print(f"[META] Warning: failed to save metadata: {e}")


def load_container_meta(chat_id: str) -> Optional[dict]:
    """Load saved metadata for container recreation. Returns dict or None."""
    meta_path = _get_meta_path(chat_id)
    try:
        if meta_path.exists():
            return json.loads(meta_path.read_text())
    except Exception as e:
        print(f"[META] Warning: failed to load metadata: {e}")
    return None


def _execute_python_with_stdin(container, script: str, data: str) -> dict:
    """Execute Python script in container with data passed through stdin."""
    import socket as sock_module

    _reset_shutdown_timer(container)
    user, workdir = _get_container_user_and_workdir()

    try:
        exec_create_kwargs = {
            "stdin": True,
            "stdout": True,
            "stderr": True,
            "workdir": workdir,
        }
        if user:
            exec_create_kwargs["user"] = user

        exec_id = container.client.api.exec_create(
            container.id,
            ["timeout", str(COMMAND_TIMEOUT), "python3", "-c", script],
            **exec_create_kwargs
        )['Id']

        sock = container.client.api.exec_start(exec_id, socket=True)

        data_bytes = data.encode('utf-8')

        if hasattr(sock, '_sock'):
            sock._sock.sendall(data_bytes)
            sock._sock.shutdown(sock_module.SHUT_WR)
        else:
            sock.sendall(data_bytes)
            if hasattr(sock, 'shutdown_write'):
                sock.shutdown_write()

        gen = frames_iter(sock, tty=False)
        gen = (demux_adaptor(*frame) for frame in gen)
        stdout_data, stderr_data = consume_socket_output(gen, demux=True)

        sock.close()

        exec_info = container.client.api.exec_inspect(exec_id)
        exit_code = exec_info['ExitCode']

        stdout = stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
        stderr = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""

        output = ""
        if stdout:
            output += stdout
        if stderr:
            if output:
                output += "\n"
            output += stderr

        if exit_code == 124:
            output += f"\n[Command timed out after {COMMAND_TIMEOUT} seconds]"

        return {
            "exit_code": exit_code,
            "output": output,
            "success": exit_code == 0
        }

    except Exception as e:
        return {
            "exit_code": -1,
            "output": f"Execution error: {str(e)}",
            "success": False
        }
