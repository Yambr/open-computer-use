# Open Computer Use vs Open Terminal

Both projects give AI models the ability to execute code and manage files. They solve the same core problem — "LLMs need somewhere to run code" — but with very different architectures, scopes, and trade-offs.

This document is a fair, technical comparison to help you choose the right tool for your use case.

| | [Open Computer Use](https://github.com/Yambr/open-computer-use) | [Open Terminal](https://github.com/open-webui/open-terminal) |
|---|---|---|
| **In one sentence** | MCP server with managed Docker workspaces — browser, terminal, skills, sub-agents | Lightweight remote shell with file management via REST API |

## Quick Comparison

| Feature | Open Computer Use | Open Terminal |
|---------|-------------------|---------------|
| **Isolation model** | Container per chat | Shared container (OS users) |
| **Production multi-user** | Yes (1,000+ MAU) | "Not designed for production" (per docs) |
| **Live browser** | Playwright + CDP streaming | No |
| **Skills system** | 13 built-in + custom | No |
| **Sub-agent** | Claude Code with MCP auto-configured | No |
| **Document creation** | PPTX, XLSX, DOCX, PDF skills | No (has format extraction libs) |
| **MCP tools** | 5 (bash, view, create, edit, sub-agent) | 19 (file ops, process mgmt, ports, grep, glob) |
| **Pre-installed packages** | 200+ (LibreOffice, Playwright, Tesseract, FFmpeg...) | ~50 (data science, build tools, ffmpeg) |
| **MCP client support** | Any (Open WebUI, Claude Desktop, n8n, LiteLLM) | Open WebUI only |
| **Jupyter notebooks** | No | Yes |
| **Bare metal mode** | No (Docker only) | Yes (`pip install open-terminal`) |
| **Port proxy** | No | Yes (reverse-proxy to localhost) |
| **Resource limits** | Per-container (RAM, CPU) | OS-level only |
| **Network isolation** | Configurable | No |
| **Security hardening** | `no-new-privileges`, read-only skill mounts | OS user permissions (`chmod 700`) |
| **Image variants** | Single full image (~2 GB) | 3 variants: full (4 GB), slim (430 MB), alpine (230 MB) |
| **Setup** | `docker compose up` | `docker run` or `pip install` |

## Architecture & Isolation

**Open Computer Use** creates a new Docker container for every chat session. If the AI breaks something — installs wrong packages, corrupts files, fills disk — only that chat is affected. Next chat starts fresh. Containers are cleaned up automatically after idle timeout.

**Open Terminal** runs a single container (or bare metal process) shared across sessions. Multi-user mode creates OS-level user accounts with `chmod 700` home directories for file isolation. The project docs explicitly note this is "not designed for production multi-user deployments" — all users share the same kernel, network, and system resources.

**Trade-off**: Open Computer Use provides stronger isolation at the cost of higher resource usage (~200-500 MB per session). Open Terminal is more lightweight but less isolated.

## Browser Capabilities

**Open Computer Use** includes Playwright with Chromium and proxies the Chrome DevTools Protocol to the client. Users see the AI browsing in real-time — not screenshots, but a live stream of the browser session. The AI can navigate pages, fill forms, extract data, and take screenshots. Users can also take over the browser manually at any point.

**Open Terminal** has no browser capabilities. It focuses purely on terminal and file operations.

## Skills System

This is the biggest architectural difference and our core thesis on how AI scales in organizations.

**Open Computer Use** has a skills system where each skill is a documented workflow (a `SKILL.md` file with scripts and templates) that gets auto-injected into the AI's system prompt based on the task. 13 skills ship out of the box:

| Skill | What it does |
|-------|-------------|
| pptx | Create/edit PowerPoint with html2pptx |
| docx | Create/edit Word documents |
| xlsx | Create/edit Excel with formulas |
| pdf | Create, fill forms, extract, merge PDFs |
| sub-agent | Delegate to Claude Code |
| playwright-cli | Browser automation and scraping |
| describe-image | Vision API image analysis |
| frontend-design | Build production-grade UIs |
| webapp-testing | Test web apps with Playwright |
| doc-coauthoring | Structured document co-authoring |
| test-driven-development | TDD methodology enforcement |
| skill-creator | Create custom skills |
| gitlab-explorer | Explore GitLab repositories |

### Skills as a platform

The real power is user-created skills. Here's the workflow we see in production:

1. **Create**: A user solves a task with AI — say, verifying a compliance document
2. **Package**: They wrap that workflow into a skill (instructions + scripts + templates)
3. **Scale**: Every colleague gets that skill with one click via the portal
4. **Automate**: Once the skill is proven, it works in cloud agents (n8n, OpenAI Agents SDK) without changes — same MCP server, same skills, no portal needed

The portal is the launchpad where users debug and refine their workflows. Cloud agents are where those workflows run in production, hands-free.

**Open Terminal** has no skills system. Capabilities depend on what's installed in the container.

## Sub-agents

**Open Computer Use** can spawn Claude Code as an autonomous sub-agent inside the sandbox. Claude Code gets its own interactive terminal with all the user's MCP servers and skills auto-configured. It can read files, write code, run tests, fix errors, and return a finished result — all without human intervention.

**Open Terminal** does not have sub-agent capabilities.

## MCP Tools

The two projects take opposite approaches to tool design.

**Open Computer Use** exposes 5 high-level tools:

| Tool | Description |
|------|-------------|
| `bash_tool` | Run commands with progress streaming and timeout |
| `view` | Read files/directories, resize images for context |
| `create_file` | Create files with content |
| `str_replace` | Edit files via find-and-replace |
| `sub_agent` | Delegate complex tasks to Claude Code |

**Open Terminal** auto-exposes 19 granular tools from its REST API:

| Category | Tools |
|----------|-------|
| Files | list, read, write, display, replace, upload, delete, move, mkdir, archive |
| Search | grep, glob |
| Processes | run, list, status, input, kill |
| Network | list ports, port proxy |

**Trade-off**: Open Computer Use's approach gives the AI fewer, more powerful primitives — the AI uses `bash_tool` for search, process management, etc. Open Terminal gives the AI fine-grained operations that don't require shell knowledge. Both work; the right choice depends on your model's strengths.

## Pre-installed Packages

**Open Computer Use** ships a comprehensive image (~2 GB) with 200+ packages:

- **Languages**: Python 3.12, Node.js 22, Java 21, Bun
- **Documents**: LibreOffice, Pandoc, python-docx, python-pptx, openpyxl
- **PDF**: pypdf, pdf-lib, reportlab, tabula-py, ghostscript
- **Images**: Pillow, OpenCV, ImageMagick, sharp, librsvg
- **Web**: Playwright (Chromium), Mermaid CLI
- **AI**: Claude Code CLI, Playwright MCP
- **OCR**: Tesseract
- **Media**: FFmpeg
- **Diagrams**: Graphviz, Mermaid

**Open Terminal** offers 3 image variants:

- **`latest`** (~4 GB): Node.js, gcc, ffmpeg, LaTeX, Docker CLI, data science libs (numpy, pandas, scipy, scikit-learn, matplotlib, Jupyter)
- **`slim`** (~430 MB): git, curl, jq
- **`alpine`** (~230 MB): git, curl, jq

**Trade-off**: Open Computer Use is bigger but has everything pre-installed. Open Terminal's `slim`/`alpine` variants are much smaller but require installing packages at runtime. Open Terminal's `latest` includes data science and Jupyter; Open Computer Use does not include Jupyter.

## Security

| Aspect | Open Computer Use | Open Terminal |
|--------|-------------------|---------------|
| **Isolation** | Docker containers (kernel namespaces) | OS user accounts (`chmod 700`) |
| **Privilege escalation** | `no-new-privileges:true` | Passwordless sudo for container user |
| **Resource limits** | Per-container (2 GB RAM, 1 CPU default) | None (OS-level only) |
| **Network isolation** | Configurable (`ENABLE_NETWORK=false`) | Egress firewall (iptables) |
| **Skill/upload mounts** | Read-only | N/A |
| **Auth** | Bearer token + X-Chat-Id | Bearer token (HMAC timing-safe) |

Both projects run as non-root users inside their containers. Both use API key authentication.

## Client Compatibility

**Open Computer Use** speaks standard MCP over Streamable HTTP. Any MCP-compatible client works:

| Client | Status |
|--------|--------|
| Open WebUI | Tested in production |
| Claude Desktop | Works |
| n8n | Works |
| LiteLLM | Works |
| OpenAI Agents SDK | Works |
| Custom clients | Any HTTP client with MCP JSON-RPC |

**Open Terminal** integrates directly with Open WebUI via its Settings → Integrations panel. It also exposes an MCP server (auto-generated from its REST API) but is primarily designed for Open WebUI.

## What Open Terminal Has That We Don't

To be fair, Open Terminal has several features we don't:

- **Jupyter notebooks** — create and execute notebooks with per-session kernels
- **Bare metal mode** — `pip install open-terminal` and run on your machine, no Docker needed
- **Port proxy** — reverse-proxy to localhost services, useful for web dev
- **Lightweight variants** — 230 MB alpine image for edge/CI
- **Document text extraction** — reads 11 formats (PDF, DOCX, XLSX, PPTX, RTF, XLS, ODT, ODS, ODP, EPUB, EML) as text
- **Process management** — stdin input to running processes, status polling
- **Simpler setup** — single `docker run` command

## When to Choose What

### Choose Open Computer Use if you need:

- Per-session isolation for multiple users in production
- Live browser automation (web scraping, testing, form filling)
- Document creation with professional formatting (PPTX, DOCX, PDF)
- Skills system for packaging and scaling workflows across a team
- Claude Code sub-agent for autonomous complex tasks
- Integration with multiple MCP clients (not just Open WebUI)
- Running AI workflows in cloud agents (n8n, OpenAI Agents SDK)

### Choose Open Terminal if you need:

- Lightweight, low-overhead code execution
- Running directly on host without Docker
- Jupyter notebook support
- Port proxying for web development
- Minimal resource footprint (230 MB alpine image)
- Simple single-container setup for personal use or small trusted groups

### Use both together

The projects are not mutually exclusive. Open Terminal can handle quick code execution tasks while Open Computer Use handles complex workflows that need browser access, document creation, or skill-based automation. Open WebUI supports connecting to both simultaneously.

## Links

- **Open Computer Use**: [github.com/Yambr/open-computer-use](https://github.com/Yambr/open-computer-use)
- **Open Terminal**: [github.com/open-webui/open-terminal](https://github.com/open-webui/open-terminal)
- **Open WebUI**: [github.com/open-webui/open-webui](https://github.com/open-webui/open-webui)
