# Computer Use Tools — Open WebUI Integration

Thin MCP client proxy that connects Open WebUI to the Computer Use Server. All container management, skills, and execution happen server-side — this tool just forwards requests via MCP Streamable HTTP.

## Architecture

```
Open WebUI (browser)
    │
    ▼
computer_use_tools.py  ──MCP over HTTP──►  Computer Use Server (:8081)
    (this tool)                                  │
                                                 ▼
                                          Docker containers
                                          (one per chat session)
```

The tool is a **stateless proxy** — it doesn't manage Docker directly. It sends MCP `tools/call` requests to the server, which handles container lifecycle, file serving, skills, and sub-agents.

## Installation

See [main README](../../README.md#open-webui-integration) for full setup. Quick version:

1. **Workspace > Tools** → Create → paste `computer_use_tools.py`
2. Set **Tool ID** to `ai_computer_use` (required for filter integration)
3. Configure Valves: `ORCHESTRATOR_URL` = internal URL of Computer Use server (e.g. `http://computer-use-server:8081` in Docker)
4. Install companion filter: `computer_link_filter.py` (Workspace > Functions)

The `docker-compose.webui.yml` stack does this automatically via `init.sh`.

## Configuration (Valves)

| Valve | Default | Description |
|-------|---------|-------------|
| `ORCHESTRATOR_URL` | `http://computer-use-server:8081` | Internal URL of Computer Use server (MCP endpoint + file uploads). Not browser-facing. |
| `MCP_API_KEY` | _(empty)_ | Bearer token for `/mcp` endpoint authentication |
| `DEBUG_LOGGING` | `false` | Verbose debug logging |

All other settings (container limits, timeouts, Docker image, skills) are configured server-side via `.env`.

## Tools Provided

| Tool | MCP Method | Description |
|------|-----------|-------------|
| `bash_tool` | `bash_tool` | Execute bash commands in the sandbox container |
| `create_file` | `create_file` | Create or overwrite files |
| `str_replace` | `str_replace` | Edit files by replacing text |
| `view` | `view` | Read files or list directories (supports line ranges) |
| `sub_agent` | `sub_agent` | Delegate complex tasks to Claude Code |

Each tool call includes HTTP headers with user context (`X-Chat-Id`, `X-User-Email`, `X-User-Name`, `X-Mcp-Servers`).

## Key Implementation Details

- **Lazy MCP client**: `_MCPClient` is created on first use and recreated when `ORCHESTRATOR_URL` changes (valves load after `__init__`)
- **File sync**: When a command references `/mnt/user-data/uploads`, uploaded files are synced to the server before execution
- **MCP server discovery**: `_get_user_mcp_server_names()` reads Open WebUI's `TOOL_SERVER_CONNECTIONS` and passes available MCP server names to the orchestrator via `X-Mcp-Servers` header — used for Claude Code sub-agent configuration
- **SSE progress**: Tool calls stream progress updates via Server-Sent Events
- **Timeouts**: Client-side timeouts (`CLIENT_HTTP_TIMEOUT=660s`, `SUB_AGENT_CLIENT_TIMEOUT=3660s`) are set higher than server-side to avoid premature disconnects

## Companion Filter

The `computer_link_filter.py` function is **required** alongside this tool:

- **Inlet** (system prompt injection): Adds `<available_skills>` XML block so the model knows which skills exist
- **Outlet** (response post-processing): Detects file URLs in responses and injects preview links, "View file" and "Download archive" buttons

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Could not connect to Computer Use Server" | Check `ORCHESTRATOR_URL` valve. Inside Docker-compose: use `http://computer-use-server:8081` (service DNS). |
| Tools not showing in chat | Enable tool in chat settings. Set **Function Calling = Native** in model settings |
| Skills not in system prompt | Install and enable `computer_link_filter.py` globally |
| File preview not working | Check `PUBLIC_BASE_URL` env var on the Computer Use server (it's baked into /system-prompt links and returned to the filter via response header — no separate filter Valve). |
| Sub-agent not starting | Set `ANTHROPIC_AUTH_TOKEN` in server `.env` |
