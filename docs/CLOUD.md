# Cloud (managed Yambr)

This page exists so GitHub visitors know a managed version exists. It is intentionally thin — the canonical cloud reference is **[docs.yambr.com](https://docs.yambr.com)** and the source of truth for keys, budgets and limits is **[app.yambr.com](https://app.yambr.com)**. If you self-host, see [INSTALL.md](INSTALL.md) instead.

## The four Yambr services

| Service | URL | Role |
|---------|-----|------|
| Dashboard | [app.yambr.com](https://app.yambr.com) | Sign in (GitHub / Google), manage keys, spend |
| MCP endpoint | `https://api.yambr.com/mcp/computer_use` | Public Streamable-HTTP MCP — tools only |
| Hosted chat | [chat.yambr.com](https://chat.yambr.com) | Open WebUI with Computer Use pre-wired, models included |
| Artifact host | `https://cu.yambr.com` | Sandbox file/preview URLs |

Yambr publishes the MCP tool endpoint; it is **not** an LLM gateway. On `api.yambr.com` you bring your own model provider. On `chat.yambr.com` models are bundled as a free convenience.

## Which path?

- **Just want to try it?** Open [chat.yambr.com](https://chat.yambr.com), sign in with GitHub or Google.
- **Want to plug Computer Use into your own agent?** Get a key from [app.yambr.com](https://app.yambr.com), point your MCP client at `https://api.yambr.com/mcp/computer_use` with a `Bearer` header. Client-specific configs (Claude Desktop, OpenAI Agents SDK, n8n, LiteLLM, curl) live under [docs.yambr.com/integrations](https://docs.yambr.com).
- **Want full control / air-gap / heavy use?** See [INSTALL.md](INSTALL.md).

A bare `GET https://api.yambr.com/mcp/computer_use` returns `500` — that's expected, the endpoint requires `POST` with MCP headers. Not a service outage.

## See also

- [docs.yambr.com/quickstart](https://docs.yambr.com/quickstart) — the three starting paths, with copy-paste snippets
- [docs.yambr.com/platform/overview](https://docs.yambr.com/platform/overview) — how the four services fit together
- [docs.yambr.com/platform/api-keys](https://docs.yambr.com/platform/api-keys) — keys, budgets, rotation
- [MCP.md](MCP.md) — MCP protocol reference (applies to both hosted and self-hosted)
