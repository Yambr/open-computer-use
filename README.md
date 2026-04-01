# Open Computer Use

[![Build](https://github.com/Yambr/open-computer-use/actions/workflows/build.yml/badge.svg)](https://github.com/Yambr/open-computer-use/actions/workflows/build.yml)
[![CodeQL](https://github.com/Yambr/open-computer-use/actions/workflows/codeql.yml/badge.svg)](https://github.com/Yambr/open-computer-use/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/Yambr/open-computer-use)](https://github.com/Yambr/open-computer-use/releases)
[![License](https://img.shields.io/github/license/Yambr/open-computer-use)](LICENSE)
[![Stars](https://img.shields.io/github/stars/Yambr/open-computer-use)](https://github.com/Yambr/open-computer-use/stargazers)
[![Issues](https://img.shields.io/github/issues/Yambr/open-computer-use)](https://github.com/Yambr/open-computer-use/issues)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

MCP server that gives any LLM its own computer — managed Docker workspaces with live browser, terminal, code execution, document skills, and autonomous sub-agents. Self-hosted, open-source, pluggable into any model.

![Demo: AI reads GitHub README and creates a landing page](docs/demo-landing-page.gif)

## What is this?

An MCP server that gives any LLM a fully-equipped Ubuntu sandbox with isolated Docker containers. Think of it as your AI's computer — it can do everything a developer can do:

- **Execute code** — bash, Python, Node.js, Java in isolated containers
- **Create documents** — Word, Excel, PowerPoint, PDF with professional styling via skills
- **Browse the web** — Playwright + live CDP browser streaming (you see what AI sees in real-time)
- **Run Claude Code** — autonomous sub-agent with interactive terminal, MCP servers auto-configured
- **Use 13+ skills** — battle-tested workflows for document creation, web testing, design, and more

### Key differentiators

| Feature | Open Computer Use | Claude.ai (Claude Code web) | [open-webui/open-terminal](https://github.com/open-webui/open-terminal) | OpenAI Operator |
|---------|-------------------|-----------|---------------|-----------------|
| **Self-hosted** | Yes | No | Yes | No |
| **Any LLM** | Yes (OpenAI-compatible) | Claude only | Any (via Open WebUI) | GPT only |
| **Code execution** | Full Linux sandbox | Sandbox (Claude Code web) | Sandbox / bare metal | No |
| **Live browser view** | CDP streaming (shared) | Screenshot-based | No | Screenshot-based |
| **User input in browser** | Yes (type directly) | No | No | Yes (take over) |
| **File access** | HTTP links from server | Side panel artifacts | REST API file ops | N/A |
| **File preview** | Preview rendering (side panel) | Side panel artifacts + IDE | File display tool | N/A |
| **Terminal** | ttyd + tmux (persistent, side panel) | Claude Code web (IDE + terminal) | Process management tools | N/A |
| **Claude Code** | Pre-installed CLI, interactive TTY + MCP | Claude Code web (built-in) | N/A | N/A |
| **Skills system** | 13 built-in + custom | Built-in skills + custom instructions | N/A | N/A |
| **Escape hatch** | Open server URLs, work independently | N/A | Bare metal mode | N/A |
| **Container isolation** | Docker (runc), per chat | Docker | Shared container (OS users) | N/A |

Works with **any MCP-compatible client**: Open WebUI, Claude Desktop, LiteLLM, n8n, or your own integration.

> **Pro tip**: Create skills with Claude Code in the terminal, then use them with any model in the chat. Skills are model-agnostic — write once, use everywhere.

### Shared browser — user and AI on one Chromium

![Shared Browser](docs/shared-browser.svg)

One browser, three users: AI navigates via Playwright, you watch live via CDP, and you can type directly (e.g. login credentials). See [docs/FEATURES.md](docs/FEATURES.md#shared-browser) for details.

![Browser Viewer](docs/screenshots/03-browser-viewer.png)

### File flow — server storage, chat gets links

![File Flow](docs/file-flow.svg)

Files live in Docker volumes on the server. Chat shows clickable HTTP links — no size limits, no re-upload. See [docs/FEATURES.md](docs/FEATURES.md#file-flow--preview) for the full pipeline.

![File Preview](docs/screenshots/02-file-preview.png)

### Claude Code CLI — escape hatch from chat

![Claude Code Terminal](docs/screenshots/04-sub-agent-terminal.png)

Pre-installed in every sandbox. Open terminal, run Claude Code, or leave OpenWebUI entirely and work in the container. See [docs/FEATURES.md](docs/FEATURES.md#claude-code-cli--when-chat-isnt-enough).

### Sub-agent dashboard — monitor and control

![Sub-Agent Dashboard](docs/screenshots/06-sub-agent-dashboard.png)

### Docker image size

The sandbox image is **~11 GB** uncompressed. See [docs/FEATURES.md](docs/FEATURES.md#docker-image-size) for a full breakdown.

See [docs/FEATURES.md](docs/FEATURES.md) for architecture deep dive, [detailed comparison with open-webui/open-terminal](docs/FEATURES.md#detailed-comparison-open-computer-use-vs-open-webuiopen-terminal), and [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md) for all screenshots.

## Architecture

![Architecture](docs/architecture.svg)

## Quick Start

```bash
git clone https://github.com/Yambr/open-computer-use.git
cd open-computer-use
cp .env.example .env
# Edit .env — set OPENAI_API_KEY (or any OpenAI-compatible provider)

# 1. Start Computer Use Server (builds workspace image on first run, ~15 min)
docker compose up --build

# 2. Start Open WebUI (in another terminal)
docker compose -f docker-compose.webui.yml up --build
```

Open http://localhost:3000 — Open WebUI with Computer Use ready to go.

> **Note:** Two separate docker-compose files: `docker-compose.yml` (Computer Use Server) and `docker-compose.webui.yml` (Open WebUI). They communicate via `localhost:8081`. This mirrors real deployments where the server and UI run on different hosts.

### Model Settings (important!)

After adding a model in Open WebUI, go to **Model Settings** and set:

| Setting | Value | Why |
|---------|-------|-----|
| **Function Calling** | `Native` | Required for Computer Use tools to work |
| **Stream Chat Response** | `On` | Enables real-time output streaming |

Without `Function Calling: Native`, the model won't invoke Computer Use tools.

## What's Inside the Sandbox

![Sandbox Contents](docs/sandbox-contents.svg)

| Category | Tools |
|----------|-------|
| **Languages** | Python 3.12, Node.js 22, Java 21, Bun |
| **Documents** | LibreOffice, Pandoc, python-docx, python-pptx, openpyxl |
| **PDF** | pypdf, pdf-lib, reportlab, tabula-py, ghostscript |
| **Images** | Pillow, OpenCV, ImageMagick, sharp, librsvg |
| **Web** | Playwright (Chromium), Mermaid CLI |
| **AI** | Claude Code CLI, Playwright MCP |
| **OCR** | Tesseract (configurable languages) |
| **Media** | FFmpeg |
| **Diagrams** | Graphviz, Mermaid |
| **Dev** | TypeScript, tsx, git |

## Skills

13 built-in public skills + 14 examples:

| Skill | Description |
|-------|-------------|
| **pptx** | Create/edit PowerPoint presentations with html2pptx |
| **docx** | Create/edit Word documents with tracked changes |
| **xlsx** | Create/edit Excel spreadsheets with formulas |
| **pdf** | Create, fill forms, extract, merge PDFs |
| **sub-agent** | Delegate complex tasks to Claude Code |
| **playwright-cli** | Browser automation and web scraping |
| **describe-image** | Vision API image analysis |
| **frontend-design** | Build production-grade UIs |
| **webapp-testing** | Test web applications with Playwright |
| **doc-coauthoring** | Structured document co-authoring workflow |
| **test-driven-development** | TDD methodology enforcement |
| **skill-creator** | Create custom skills |
| **gitlab-explorer** | Explore GitLab repositories |

**14 example skills**: web-artifacts-builder, copy-editing, social-content, canvas-design, algorithmic-art, theme-factory, mcp-builder, and more.

See [docs/SKILLS.md](docs/SKILLS.md) for details.

## MCP Integration

The server speaks standard MCP over Streamable HTTP. Connect it to anything:

```bash
# Test with curl
curl -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -H "X-Chat-Id: test" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

See [docs/MCP.md](docs/MCP.md) for full integration guide (LiteLLM, Claude Desktop, custom clients).

## Configuration

All settings via `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | LLM API key (any OpenAI-compatible) |
| `OPENAI_API_BASE_URL` | — | Custom API base URL (OpenRouter, etc.) |
| `MCP_API_KEY` | — | Bearer token for MCP endpoint |
| `DOCKER_IMAGE` | `open-computer-use:latest` | Sandbox container image |
| `COMMAND_TIMEOUT` | `120` | Bash tool timeout (seconds) |
| `SUB_AGENT_TIMEOUT` | `3600` | Sub-agent timeout (seconds) |
| `POSTGRES_PASSWORD` | `openwebui` | PostgreSQL password |
| `VISION_API_KEY` | — | Vision API key (for describe-image) |
| `ANTHROPIC_AUTH_TOKEN` | — | Anthropic key (for Claude Code sub-agent) |
| `MCP_TOKENS_URL` | — | Settings Wrapper URL (optional, see below) |
| `MCP_TOKENS_API_KEY` | — | Settings Wrapper auth key |

### Custom Skills & Token Management (optional)

By default, all 13 built-in skills are available to everyone. For per-user skill access and custom skills, deploy the **Settings Wrapper** — see [settings-wrapper/README.md](settings-wrapper/README.md).

**Personal Access Tokens (PATs):** The settings wrapper can also store encrypted per-user PATs for external services (GitLab, Confluence, Jira, etc.). The server fetches them by user email and injects into the sandbox — so each user's AI has access to their repos/docs without sharing credentials. The server-side code for token injection is implemented (`docker_manager.py`), but the Open WebUI tool doesn't pass the required headers yet. This is on the roadmap — if you need PAT management, [open an issue](https://github.com/Yambr/open-computer-use/issues).

## MCP Client Integrations

The Computer Use Server speaks standard **MCP over Streamable HTTP** — any MCP-compatible client can connect. Open WebUI is the primary tested frontend, but not the only option.

| Client | How to connect | Status |
|--------|---------------|--------|
| [**Open WebUI**](https://github.com/open-webui/open-webui) | Docker Compose stack included, auto-configured | Tested in production |
| [**Claude Desktop**](https://claude.ai/download) | Add to `claude_desktop_config.json` — see [docs/MCP.md](docs/MCP.md) | Works |
| [**n8n**](https://n8n.io) | MCP Tool node → `http://computer-use-server:8081/mcp` | Works |
| [**LiteLLM**](https://github.com/BerriAI/litellm) | MCP proxy config — see [docs/MCP.md](docs/MCP.md) | Works |
| **Custom client** | Any HTTP client with MCP JSON-RPC — see curl examples in [docs/MCP.md](docs/MCP.md) | Works |

## Open WebUI Integration

> **[Open WebUI](https://github.com/open-webui/open-webui)** is an extensible, self-hosted AI interface. We use it as the primary frontend because it supports tool calling, function filters, and artifacts — everything needed for Computer Use.

**Compatibility:** Tested with Open WebUI v0.8.11–0.8.12. Set `OPENWEBUI_VERSION` in `.env` to pin a specific version.

**Why not a fork?** We intentionally did not fork Open WebUI. Instead, everything is bolted on via the official plugin API (tools + functions) and build-time patches for missing features. This means you can use any stock [Open WebUI](https://github.com/open-webui/open-webui) version — just install the tool and filter. Patches are optional quality-of-life fixes applied at Docker build time.

The `openwebui/` directory contains:

- **tools/** — MCP client tool (thin proxy to Computer Use Server). **Required** — this is the bridge between Open WebUI and the sandbox.
- **functions/** — System prompt injector + file link rewriter + archive button. **Required** — without it the model doesn't know about skills and file URLs.
- **patches/** — Build-time fixes for artifacts, error handling, file preview. **Optional** but recommended — improves UX significantly.
- **init.sh** — Auto-installs tool + filter on first startup. **Optional** — you can install manually via Workspace UI instead.
- **Dockerfile** — Builds a patched Open WebUI image with auto-init. **Optional** — use stock Open WebUI + manual setup if you prefer.

### How auto-init works

On first `docker compose up`, the init script automatically:

1. Creates an admin user (`admin@open-computer-use.dev` / `admin`)
2. Installs the Computer Use tool via `POST /api/v1/tools/create`
3. Installs the Computer Use filter via `POST /api/v1/functions/create`
4. Configures tool valves (`FILE_SERVER_URL=http://computer-use-server:8081`)
5. Enables the filter globally

A marker file (`.computer-use-initialized`) prevents re-running on subsequent starts.

> **Note:** Open WebUI doesn't support pre-installed tools from the filesystem — they must be loaded via the REST API. The init script automates this so you don't have to do it manually.

### Manual setup (if not using docker-compose)

If you run Open WebUI separately, you need to manually:

1. Go to **Workspace > Tools** → Create new tool → paste contents of `openwebui/tools/computer_use_tools.py`
2. Set **Tool ID** to `ai_computer_use` (required for filter to work)
3. Configure **Valves**: `FILE_SERVER_URL` = your Computer Use Server URL
4. Go to **Workspace > Functions** → Create new function → paste `openwebui/functions/computer_link_filter.py`
5. Enable the filter globally (toggle in Functions list)
6. In your model settings, set **Function Calling** = `Native`

The docker-compose stack handles all of this automatically.

## Security Notes

> **Production tested** with 1000+ users on Open WebUI in a self-hosted environment. For public-facing deployments, see the hardening roadmap below.

### Current model

- **Docker socket**: The server needs Docker socket access to manage sandbox containers. This grants significant host access — run in a trusted environment only.
- **MCP_API_KEY**: Set a strong random key in production. Without it, anyone with network access to port 8081 can execute arbitrary commands in containers.
- **Sandbox isolation**: Each chat session runs in a separate container with resource limits (2GB RAM, 1 CPU). Containers use standard Docker runtime (runc), not gVisor — they share the host kernel. For stronger isolation, consider switching to gVisor runtime (see roadmap). Containers have network access by default.
- **POSTGRES_PASSWORD**: Change the default password in `.env` for production.

### Known limitations

- **Unauthenticated file/preview endpoints**: `/files/{chat_id}/`, `/api/outputs/{chat_id}`, `/browser/{chat_id}/`, `/terminal/{chat_id}/` — accessible to anyone who knows the chat ID. Chat IDs are UUIDs (hard to guess but not a real security boundary).
- **No per-user auth on server**: The MCP server trusts whoever sends a valid `MCP_API_KEY`. User identity (`X-User-Email`) is passed by the client but not verified server-side.
- **Credentials in HTTP headers**: API keys (GitLab, Anthropic, MCP tokens) are passed as HTTP headers from client to server. Safe within Docker network, but use HTTPS if exposing externally.
- **Default admin credentials**: `admin@open-computer-use.dev` / `admin` — change immediately in multi-user setups.

### Security roadmap

We plan to address these in future releases:

- [ ] **Per-session signed tokens** for file/preview/terminal endpoints (replace chat ID as auth)
- [ ] **Server-side user verification** via Open WebUI JWT validation
- [ ] **HTTPS support** with automatic TLS certificates
- [ ] **Audit logging** for all tool calls and file access
- [ ] **Network policies** for sandbox containers (restrict egress by default)
- [ ] **Secret management** — move credentials from headers to encrypted server-side storage
- [ ] **gVisor (runsc) runtime** — optional container sandboxing for stronger isolation (like Claude.ai)

Ideas? Open a [GitHub Issue](https://github.com/Yambr/open-computer-use/issues). Want to contribute? See [CONTRIBUTING.md](CONTRIBUTING.md) or reach out on Telegram [@yambrcom](https://t.me/yambrcom).

## Development

```bash
# Build workspace image locally
docker build --platform linux/amd64 -t open-computer-use:latest .

# Run tests
./tests/test-docker-image.sh open-computer-use:latest
./tests/test-no-corporate.sh
./tests/test-project-structure.sh

# Build and run full stack
docker compose up --build
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome!

## Community

- **Issues & Ideas**: [GitHub Issues](https://github.com/Yambr/open-computer-use/issues)
- **Telegram**: [@yambrcom](https://t.me/yambrcom)

## License

[MIT](LICENSE)
