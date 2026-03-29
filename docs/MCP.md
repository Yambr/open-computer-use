# MCP Server Integration

The Computer Use Server exposes a standard [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) endpoint that works with any MCP-compatible client.

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

| Header | Description | Required |
|--------|-------------|----------|
| `X-Chat-Id` | Session identifier (one container per chat) | Yes |
| `X-User-Email` | User email (for GitLab token, logging) | No |
| `X-User-Name` | Display name | No |

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
