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
SUB_AGENT_MAX_TURNS = int(os.getenv("SUB_AGENT_MAX_TURNS", "25"))
SUB_AGENT_TIMEOUT = int(os.getenv("SUB_AGENT_TIMEOUT", "3600"))

# Anthropic API (shared LiteLLM proxy key — fallback when no header provided)
ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

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

# Vision API for describe-image / upd-processing skills
VISION_API_KEY = os.getenv("VISION_API_KEY", "")
VISION_API_URL = os.getenv("VISION_API_URL", "")
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o")



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



def build_mcp_config(server_names_csv: str, base_url: str, user_email: str = "") -> dict | None:
    """Build Claude Code ~/.mcp.json config from comma-separated server names.

    URLs are templated as {base_url}/mcp/{server_name} (LiteLLM MCP proxy pattern).
    Authorization uses ANTHROPIC_AUTH_TOKEN env var (resolved inside container at write time).

    Returns dict ready for json.dumps, or None if no servers specified.
    """
    # Blocklist: prevent recursive sub_agent loops
    BLOCKED_SERVERS = {"docker_ai", "docker-ai"}

    names = [s.strip() for s in server_names_csv.split(",") if s.strip() and s.strip() not in BLOCKED_SERVERS]
    if not names:
        return None

    base = base_url.rstrip("/")
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

    anthropic_key = current_anthropic_auth_token.get() or ANTHROPIC_AUTH_TOKEN
    anthropic_base = current_anthropic_base_url.get() or ANTHROPIC_BASE_URL
    if anthropic_key:
        extra_env["ANTHROPIC_AUTH_TOKEN"] = anthropic_key
        extra_env["ANTHROPIC_BASE_URL"] = anthropic_base

    for _name, _value in CLAUDE_CODE_PASSTHROUGH_ENVS:
        if _value:
            extra_env[_name] = _value

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

    return container


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
