# Cloud (managed Yambr)

This doc is for people who **don't want to self-host**. If you're running `docker compose up`, see [INSTALL.md](INSTALL.md) instead — that path is first-class and always will be.

The managed version lives at **[yambr.com](https://yambr.com)**. The canonical cloud reference is **[docs.yambr.com](https://docs.yambr.com)** — this page is just the quick on-ramp.

## The four Yambr services

| Service | URL | Role |
|---------|-----|------|
| Dashboard | [app.yambr.com](https://app.yambr.com) | Sign in, request key, manage keys, live spend tracking |
| MCP endpoint | `https://api.yambr.com/mcp/computer_use` | Public Streamable-HTTP MCP — the **tool server** |
| Hosted chat | [chat.yambr.com](https://chat.yambr.com) | Managed Open WebUI with Computer Use pre-wired (models included) |
| Artifact host | `https://cu.yambr.com` | Sandbox file/preview URLs (the URL itself is the access token) |

> Yambr publishes one public surface: the Computer Use MCP endpoint. Model inference stays on your own provider — **you bring your own model provider, Yambr doesn't resell inference**.

## Two hosted paths

The cloud gives you two clearly distinct options. Pick based on whether you want models included or not.

### Path A — `chat.yambr.com` (free end-to-end demo)

Managed Open WebUI with Computer Use pre-installed globally. Yambr pays for the LLM models too, as a convenience for browser users. Zero setup.

1. Open [chat.yambr.com](https://chat.yambr.com)
2. Sign in with GitHub or Google (no email/password, no SMS)
3. Pick a model from the dropdown, start chatting

Drag files into chat input — they're mounted at `/home/assistant/uploads/{chat_id}/` inside the sandbox. Artifacts auto-render. Large tool results stream without truncation. Per-chat sandbox isolation (different chats = separate containers).

### Path B — `api.yambr.com/mcp/computer_use` (tools only, bring your own LLM)

A public MCP endpoint you point any agent/MCP client at. Your LLM traffic goes to *your* provider (OpenAI, Anthropic, OpenRouter…); your Yambr key unlocks the Computer Use sandbox, nothing else.

**Issue a key:**

1. Sign in at [app.yambr.com](https://app.yambr.com) via GitHub or Google (no email + password flow)
2. Request access — approvals are a light manual review ("we eyeball requests and approve most of them quickly"). Urgent? Ping [@yambrcom](https://t.me/yambrcom) on Telegram
3. Once approved, create a key from the dashboard. The full key `sk-yambr-...` is shown **once** — store it in a secret manager immediately. After that the dashboard only shows `sk-...{last-4}`
4. Default budget: **$10 / 30 days rolling**. Up to 5 keys per account. Max 5 concurrent requests per key — `429` on exhaustion of either cap. Reissue rotates the key but keeps the budget and alias slot

> Treat Yambr keys like database passwords: never commit them to git, never ship them to a browser, rotate on exposure.

## Client configs

Every config below targets `https://api.yambr.com/mcp/computer_use`. The `X-Chat-Id` header identifies the sandbox — **keep it stable for a persistent sandbox; rotate it to start fresh**.

### Claude Desktop

File path:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "yambr-computer-use": {
      "url": "https://api.yambr.com/mcp/computer_use",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer sk-yambr-...",
        "X-Chat-Id": "claude-desktop"
      }
    }
  }
}
```

Restart Claude Desktop after editing.

### OpenAI Agents SDK (Python)

```python
import os
from agents import Agent, Runner
from agents.mcp import MCPServerStreamableHttp

yambr_mcp = MCPServerStreamableHttp(
    params={
        "url": "https://api.yambr.com/mcp/computer_use",
        "headers": {"Authorization": f"Bearer {os.environ['YAMBR_API_KEY']}"},
    },
    name="yambr-computer-use",
)

agent = Agent(
    name="computer-user",
    model="gpt-4o",
    mcp_servers=[yambr_mcp],
)

result = await Runner.run(agent, "Build me a landing page for a coffee shop")
print(result.final_output)
```

### n8n

Add an **MCP Tool** node → URL `https://api.yambr.com/mcp/computer_use`, auth `Bearer sk-yambr-...`, extra header `X-Chat-Id: {{ $json.chat_id }}`.

### Plain curl

```bash
curl -sD - -X POST "https://api.yambr.com/mcp/computer_use" \
  -H "Authorization: Bearer sk-yambr-..." \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Chat-Id: my-session" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"my-client","version":"1.0"}}}'
```

> A bare `GET https://api.yambr.com/mcp/computer_use` returns `500` — that's expected, MCP requires `POST` + the headers above. Not a service outage.

### Open WebUI

If you want the hosted Computer Use tools inside your *own* Open WebUI: either use **[chat.yambr.com](https://chat.yambr.com)** (already wired up, models included) or **self-host** the full stack via [INSTALL.md](INSTALL.md). Pointing a third-party Open WebUI at `api.yambr.com` isn't a documented path today.

## Pricing & limits (at a glance)

| What | Value |
|------|-------|
| Sign-in providers | GitHub, Google (no email + password, no SMS) |
| Default budget per key | $10 / 30-day rolling window |
| Keys per account | Up to 5 |
| Concurrent requests per key | 5 (429 on overflow) |
| Budget exhaustion | 429 until the rolling window resets |
| Key visibility after creation | `sk-...{last-4}` only — full key shown once |
| Key rotation | Reissue keeps budget + alias; old value 401s immediately |

Budgets, model lists, and approval flow are the authoritative truth on [app.yambr.com](https://app.yambr.com) and [docs.yambr.com](https://docs.yambr.com) — numbers here can drift.

## See also

- [docs.yambr.com](https://docs.yambr.com) — full cloud docs: platform overview, access model, API keys, dashboard tour, per-integration guides
- [docs.yambr.com/platform/access-model](https://docs.yambr.com/platform/access-model) — which surfaces are public vs convenience
- [docs.yambr.com/quickstart](https://docs.yambr.com/quickstart) — the three starting paths in one page
- [INSTALL.md](INSTALL.md) — self-host Quick Start
- [MCP.md](MCP.md) — MCP protocol reference (applies to both hosted and self-hosted)
