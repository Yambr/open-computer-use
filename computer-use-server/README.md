# Computer Use Server

MCP orchestrator that manages isolated Docker sandbox containers. Provides tools for executing commands, editing files, browsing the web, and delegating tasks to Claude Code sub-agents.

## Architecture

```
Client (Open WebUI / Claude Desktop / curl)
    │
    │  MCP over Streamable HTTP
    ▼
┌─────────────────────────────────┐
│  Computer Use Server (:8081)    │
│                                 │
│  app.py        — FastAPI app    │
│  mcp_tools.py  — MCP tools     │
│  docker_manager.py — containers │
│  skill_manager.py  — skills    │
│  system_prompt.py  — prompts   │
└────────────┬────────────────────┘
             │ Docker Socket
             ▼
┌─────────────────────────────────┐
│  Sandbox Container              │
│  (one per chat session)         │
│  Ubuntu 24.04 + tools           │
└─────────────────────────────────┘
```

## Modules

| Module | Purpose |
|--------|---------|
| `app.py` | FastAPI application: MCP endpoint, file serving, browser/terminal proxy, system prompt API |
| `mcp_tools.py` | MCP tool definitions: `bash_tool`, `view`, `create_file`, `str_replace`, `sub_agent` |
| `docker_manager.py` | Container lifecycle: create, stop, cleanup, health checks, volume mounts |
| `skill_manager.py` | Skill registry: fetch user skills, cache ZIPs, generate system prompt XML |
| `system_prompt.py` | System prompt templates with skill injection |
| `context_vars.py` | Per-request context (chat_id, user_email, etc.) via ContextVar |
| `docs_html.py` | HTML documentation page generator |

## API Endpoints

### MCP
- `POST /mcp` — MCP Streamable HTTP endpoint (main interface)

### Files
- `GET /files/{chat_id}/{filename}` — Download output file
- `GET /files/{chat_id}/archive` — Download all outputs as ZIP
- `GET /api/outputs/{chat_id}` — List output files with metadata
- `POST /api/uploads/{chat_id}/{filename}` — Upload file to container

### Browser (CDP Proxy)
- `GET /browser/{chat_id}/status` — Browser status
- `GET /browser/{chat_id}/json` — CDP targets
- `WebSocket /browser/{chat_id}/devtools/page/{page_id}` — CDP WebSocket proxy

### Terminal
- `GET /terminal/{chat_id}/status` — Terminal/container status
- `POST /terminal/{chat_id}/start-ttyd` — Start terminal session
- `WebSocket /terminal/{chat_id}/ws` — Terminal WebSocket proxy

### System
- `GET /health` — Health check
- `GET /system-prompt` — Get system prompt (with dynamic skills)
- `GET /skill-list` — List available skills

## Configuration

All via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_API_KEY` | _(empty)_ | Bearer token for MCP endpoint auth |
| `DOCKER_IMAGE` | `open-computer-use:latest` | Sandbox container image |
| `COMMAND_TIMEOUT` | `120` | Bash command timeout (seconds) |
| `SUB_AGENT_TIMEOUT` | `3600` | Sub-agent timeout (seconds) |
| `USER_DATA_BASE_PATH` | `/tmp/computer-use-data` | Host path for file exchange |
| `BASE_DATA_DIR` | `/data` | Server-side path to chat data |
| `CONTAINER_MEM_LIMIT` | `2g` | Container memory limit |
| `CONTAINER_CPU_LIMIT` | `1.0` | Container CPU limit |
| `CONTAINER_IDLE_TIMEOUT` | `600` | Auto-stop idle containers (seconds) |
| `ENABLE_NETWORK` | `true` | Container network access |
| `MCP_TOKENS_URL` | _(empty)_ | Settings wrapper URL (optional) |
| `MCP_TOKENS_API_KEY` | _(empty)_ | Settings wrapper auth key |

## Running Standalone

```bash
cd computer-use-server
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8081
```

Requires Docker socket access and a built workspace image.

## Docker

```bash
docker compose up --build computer-use-server
```

See [docker-compose.yml](../docker-compose.yml) for the full stack configuration.
