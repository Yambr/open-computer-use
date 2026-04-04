# MCP Server Integration

The Computer Use Server exposes a standard [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) endpoint that works with any MCP-compatible client.

This server is published in the [MCP Registry](https://github.com/modelcontextprotocol/registry) as `io.github.yambr/open-computer-use`.

## Deployment Prerequisite

This is a **self-hosted** MCP server. You must deploy it before connecting:

```bash
git clone https://github.com/yambr/open-computer-use.git
cd open-computer-use
docker build --platform linux/amd64 -t open-computer-use:latest .
docker compose up -d
```

The MCP endpoint will be available at `http://localhost:8081/mcp`.

### Session isolation modes

The server supports three modes controlled by the `SINGLE_USER_MODE` environment variable. This determines how `X-Chat-Id` headers are handled and whether sessions get isolated containers.

| `SINGLE_USER_MODE` | `X-Chat-Id` sent | Behavior |
|---------------------|-------------------|----------|
| _(not set)_ | Yes | Normal: isolated container per chat ID |
| _(not set)_ | No | Lenient: uses shared `default` container + appends a warning to every tool response |
| `true` | _(any)_ | Single-user: always uses one `default` container, no warnings, header ignored |
| `false` | Yes | Strict multi-user: isolated container per chat ID |
| `false` | No | **Error** — `X-Chat-Id` is required, tool call rejected |

**Default behavior (no env var):** the server accepts requests without `X-Chat-Id` but appends a note to every tool response explaining the options. This makes onboarding easy — things work immediately, and the warning guides users toward the right setup.

#### Single-user mode (recommended for Claude Desktop)

If you're the only user, set `SINGLE_USER_MODE=true` in `.env`. All sessions share one persistent container — no headers needed:

```bash
echo "SINGLE_USER_MODE=true" >> .env
docker compose restart
```

#### Strict multi-user mode (recommended for production)

For shared deployments, set `SINGLE_USER_MODE=false`. Every request must include `X-Chat-Id` — requests without it are rejected with an error:

```bash
echo "SINGLE_USER_MODE=false" >> .env
docker compose restart
```

MCP clients (Open WebUI, LiteLLM, n8n) typically pass chat/session IDs automatically via `X-Chat-Id` or `X-OpenWebUI-Chat-Id` headers.

## Endpoint

```
POST http://localhost:8081/mcp
```

## Authentication

Set the `MCP_API_KEY` environment variable and pass it as a Bearer token:

```
Authorization: Bearer <MCP_API_KEY>
```

Leave `MCP_API_KEY` empty for development (no auth required).

## Available Tools

| Tool | Description |
|------|-------------|
| `bash_tool` | Execute bash commands in isolated Docker container |
| `view` | View files and directories |
| `create_file` | Create new files |
| `str_replace` | Edit files via text replacement |
| `sub_agent` | Delegate tasks to autonomous Claude Code agent |

## Required Headers

> **`X-Chat-Id` is mandatory.** Without it, the server returns an error. Every request must include a unique session identifier.

| Header | Description | Required |
|--------|-------------|----------|
| `X-Chat-Id` | **Session identifier** — one sandbox container per chat ID | **Yes** |
| `Authorization` | `Bearer <MCP_API_KEY>` — required if `MCP_API_KEY` is set | Conditional |
| `X-User-Email` | User email (for per-user skills, token lookup, logging) | No |
| `X-User-Name` | Display name (URL-encoded) | No |
| `X-MCP-Servers` | Comma-separated MCP server names for Claude Code sub-agent | No |

## Usage Examples

### Initialize Session

```bash
curl -sD - -X POST "http://localhost:8081/mcp" \
  -H "Authorization: Bearer $MCP_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Chat-Id: my-session" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"my-client","version":"1.0"}}}'
```

Save the `mcp-session-id` header from the response.

### Call a Tool

```bash
curl -s -X POST "http://localhost:8081/mcp" \
  -H "Authorization: Bearer $MCP_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -H "X-Chat-Id: my-session" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"bash_tool","arguments":{"command":"echo Hello from sandbox","description":"test"}}}'
```

### List Tools

```bash
curl -s -X POST "http://localhost:8081/mcp" \
  -H "Authorization: Bearer $MCP_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -H "X-Chat-Id: my-session" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}'
```

## Integration with LLM Frameworks

### LiteLLM

```yaml
mcp_servers:
  computer_use:
    url: "http://computer-use-server:8081/mcp"
    transport: "http"
    auth_type: "bearer_token"
    auth_value: "<MCP_API_KEY>"
    extra_headers:
      X-Chat-Id: "{chat_id}"
      X-User-Email: "{user_email}"
```

### Claude Desktop (claude_desktop_config.json)

```json
{
  "mcpServers": {
    "computer-use": {
      "url": "http://localhost:8081/mcp",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer <MCP_API_KEY>",
        "X-Chat-Id": "desktop-session"
      }
    }
  }
}
```

## MCP Servers for Claude Code Sub-Agent

When the `sub_agent` tool launches Claude Code inside a sandbox container, it can be configured with MCP servers. This allows Claude Code to access external tools (databases, APIs, other MCP servers) during autonomous task execution.

### How it works

1. **Client sends MCP server names** via HTTP header when calling the Computer Use Server
2. **Computer Use Server** writes `~/.mcp.json` inside the sandbox container
3. **Claude Code** reads the config and connects to the specified MCP servers
4. **Authorization** uses `ANTHROPIC_AUTH_TOKEN` from the container environment (no secrets in config)

### Header format

Pass MCP server names as a comma-separated list:

```
X-MCP-Servers: server1,server2,server3
```

Or the Open WebUI-style header:

```
X-OpenWebUI-MCP-Servers: server1,server2,server3
```

### URL pattern

Server URLs are templated as `{ANTHROPIC_BASE_URL}/mcp/{server_name}` — this follows the LiteLLM MCP proxy pattern where LiteLLM acts as a gateway to multiple MCP servers.

### Example: LiteLLM with multiple MCP servers

If LiteLLM is configured with MCP servers `github`, `jira`, `slack`:

```yaml
# LiteLLM config
mcp_servers:
  github:
    url: "http://github-mcp:3000/mcp"
  jira:
    url: "http://jira-mcp:3001/mcp"
  slack:
    url: "http://slack-mcp:3002/mcp"
```

Passing `X-MCP-Servers: github,jira` will make these servers available to Claude Code inside the sandbox.

### Generated ~/.mcp.json

```json
{
  "mcpServers": {
    "github": {
      "type": "http",
      "url": "https://llm-api.example.com/mcp/github",
      "headers": {
        "x-openwebui-user-email": "user@example.com",
        "Authorization": "Bearer <ANTHROPIC_AUTH_TOKEN>"
      }
    }
  }
}
```

### Security notes

- The server name `docker_ai` / `docker-ai` is blocked to prevent recursive sub-agent loops
- Authorization tokens are resolved at runtime from container environment, not stored in the config file
- MCP servers are auto-approved in Claude Code's `settings.local.json` so it doesn't prompt for permission

### Open WebUI integration (planned)

Currently, the Open WebUI tool (`computer_use_tools.py`) does not pass MCP server headers. To use this feature, either:

1. Use a custom MCP client that sets the `X-MCP-Servers` header
2. Or add MCP server forwarding to the Open WebUI tool (contributions welcome)

## Dynamic Configuration Endpoints

The server provides API endpoints that MCP clients should use to get up-to-date configuration instead of hardcoding values.

### GET /system-prompt

Returns the full system prompt as plain text with current skills and correct file URLs.

```bash
curl "http://localhost:8081/system-prompt?chat_id=my-session&user_email=user@example.com"
```

| Parameter | Description | Required |
|-----------|-------------|----------|
| `chat_id` | Session ID — server constructs file download URLs from this | Recommended |
| `user_email` | Returns prompt with user-specific skills | No |

### GET /skill-list

Returns available skills as formatted text for sub-agent delegation.

```bash
curl "http://localhost:8081/skill-list?user_email=user@example.com"
```

### GET /mcp-info

Returns MCP endpoint metadata as JSON: available tools, required headers, endpoint URL.

```bash
curl "http://localhost:8081/mcp-info" -H "Authorization: Bearer $MCP_API_KEY"
```

**Best practice:** Fetch the system prompt dynamically via `/system-prompt?chat_id={id}` at session start. This ensures the AI model gets correct file URLs and the latest skill set. See [System Prompt Reference](system-prompt.md) for details.

## Browser Viewer (CDP)

Each sandbox container runs Chromium with CDP exposed. Access the live browser:

```
GET http://localhost:8081/browser/{chat_id}/status
GET http://localhost:8081/browser/{chat_id}/json
WebSocket: ws://localhost:8081/browser/{chat_id}/devtools/page/{page_id}
```

## Terminal Access

Interactive terminal via WebSocket:

```
GET http://localhost:8081/terminal/{chat_id}/status
GET http://localhost:8081/terminal/{chat_id}/start-ttyd
WebSocket: ws://localhost:8081/terminal/{chat_id}/ws
```
