# Architecture & Features Deep Dive

How Open Computer Use works under the hood, and how it differs from Claude.ai, Open Terminal, and other sandboxed AI environments.

## Shared Browser

![Shared Browser](shared-browser.svg)

One Chromium instance inside the sandbox container, shared between three actors:

| Actor | Access | What they do |
|-------|--------|--------------|
| **AI Agent** | Playwright CDP | Navigates, clicks, fills forms, scrapes data |
| **User (side panel)** | CDP stream (read-only viewer) | Watches AI actions in real-time |
| **User (directly)** | Same browser, full input | Types credentials, navigates to pages, interacts |

**Why this matters:** The user can enter sensitive information (passwords, 2FA codes, private data) directly into the browser — the AI never sees the raw credentials, only the resulting page state. This is a true shared workspace, not a screenshot relay.

### vs. Claude.ai
Claude.ai uses **screenshot-based** browser interaction — the AI takes a screenshot, decides where to click, takes another screenshot. The user sees static images, not a live stream. There's no way for the user to type into the AI's browser.

### vs. Open Terminal
Open Terminal provides a **native file browser** but doesn't expose a shared browser with live streaming. The browser (if any) is agent-only.

## File Flow & Preview

![File Flow](file-flow.svg)

### How files work

1. **AI creates files** inside the sandbox container (`/mnt/user-data/outputs/`)
2. **Computer Use Server** serves files via HTTP (`/api/outputs/{chat_id}/filename`)
3. **Chat shows links** — the AI's response contains clickable HTTP URLs to the files
4. **Side panel renders preview** — docx, pdf, xlsx, images, code are rendered inline
5. **User downloads** by clicking the link or using the archive/zip endpoint

### Key design: files don't go back into the chat

Unlike Claude.ai where artifacts live inside the conversation, our files live on the **server**. The chat only contains links. This means:

- **No file size limits** in chat — the server handles arbitrarily large files
- **Direct access** — open any file URL in a new browser tab
- **Zip download** — download all outputs as a single archive
- **No re-upload** — files don't flow back into Open WebUI's storage

### vs. Claude.ai
Claude.ai has **artifacts** embedded in the conversation. Files are part of the chat context. Our approach keeps files separate — the server is the source of truth.

### vs. Open Terminal
Open Terminal uses a **native file browser** that shows the container filesystem directly. Our side panel is a **preview renderer** that fetches from the Computer Use Server and displays in an iframe (with HTML rendering for office documents, syntax highlighting for code, etc.).

## Claude Code CLI — When Chat Isn't Enough

The sandbox container has **Claude Code CLI pre-installed**. Users can access it in two ways:

1. **Via sub_agent tool** — the AI delegates complex tasks to Claude Code autonomously
2. **Via terminal tab** — the user opens the terminal in the side panel and runs Claude Code manually

### When to use the terminal

- Complex refactoring that requires many file edits
- Debugging with interactive tools (gdb, pdb, node inspect)
- Git operations (rebase, merge, cherry-pick)
- Running Claude Code with specific flags or prompts
- Working with MCP servers that the chat model doesn't support
- Simply preferring a CLI workflow

### How it works

```
User's browser ←WebSocket→ Computer Use Server ←WebSocket→ Container (ttyd:7681 → tmux → bash)
```

- **tmux** keeps the session alive — disconnect and reconnect without losing state
- **Claude Code** has access to all configured MCP servers (auto-generated `~/.mcp.json`)
- User can **switch between chat and terminal** freely — both modify the same container filesystem

### The escape hatch

Users can leave Open WebUI entirely:
- Open the server URL directly in a browser tab
- Navigate to `/terminal/{chat_id}/` for a full-screen terminal
- SSH into the container (if configured)
- Work with files, run code, use Claude Code CLI — all independent of the chat interface

## Preview & Artifacts Panel

The side panel (artifacts panel) in Open WebUI serves three functions:

| Tab | Content | Source |
|-----|---------|--------|
| **Files** | Preview of created documents (docx → HTML, pdf inline, xlsx table, images, code) | Computer Use Server `/api/outputs/{chat_id}/` |
| **Browser** | Live CDP stream of Chromium in the sandbox | Computer Use Server `/browser/{chat_id}/` |
| **Sub-Agent** | Terminal (ttyd) + Claude Code process dashboard | Computer Use Server `/terminal/{chat_id}/` |

### How preview rendering works

1. AI creates a file (e.g. `report.docx`) via `create_file` tool
2. The filter function detects the file URL in the response
3. Side panel opens automatically with the preview URL
4. Server renders preview: LibreOffice converts docx → HTML, pdf is embedded, images are displayed
5. User sees the result inline without downloading

### vs. Open Terminal
Open Terminal uses the **IDE's native file explorer** — files appear in the file tree and open in editor tabs. Our approach uses a **preview renderer** that works in any browser, without an IDE.

### vs. Claude.ai
Claude.ai renders **artifacts** (HTML, React, SVG) inline in the chat. Our side panel is separate from the chat and supports a wider range of file types (office documents, PDFs, archives, etc.) via the preview renderer on the Computer Use Server.

## File Transfer & Sync

### How data flows between components

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Volume: user-data-{chat_id}                         │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐    │
│  │   uploads/    │   │   outputs/   │   │  .claude/    │    │
│  │   (read-only) │   │  (read-write)│   │  (sessions)  │    │
│  └──────────────┘   └──────────────┘   └──────────────┘    │
└────────────────────────────┬────────────────────────────────┘
                             │ bind mount
                ┌────────────┴────────────┐
                │    Sandbox Container    │
                │  /mnt/user-data/...     │
                └────────────┬────────────┘
                             │ HTTP
                ┌────────────┴────────────┐
                │  Computer Use Server    │
                │  /api/outputs/{id}/     │
                └────────────┬────────────┘
                             │ links
                ┌────────────┴────────────┐
                │    Open WebUI (chat)    │
                │  clickable URLs         │
                └─────────────────────────┘
```

### Key points

- **Everything is on the server** — Docker volumes, not local filesystem
- **Container sees volumes as mounts** — `/mnt/user-data/uploads/` (user uploads, read-only) and `/mnt/user-data/outputs/` (AI outputs, read-write)
- **Server serves files via HTTP** — no direct filesystem access from the browser
- **Chat only has links** — lightweight, no file data in the conversation
- **Volume persists** — survives container restarts, available until cleanup

### vs. Open Terminal
Open Terminal mounts files in a way visible to the **IDE file browser**. Our approach is HTTP-first — all file access goes through the Computer Use Server API.

### vs. Claude.ai
Claude.ai uses **project files** that are uploaded into the conversation context. Our files live in Docker volumes and are accessed via HTTP — separate from the chat context, no size limits.

## Summary: Architecture Comparison

| Aspect | Open Computer Use | Claude.ai | Open Terminal |
|--------|-------------------|-----------|---------------|
| **Browser** | Shared Chromium + CDP live stream | Screenshot-based | Agent-only |
| **User input in browser** | Yes (type directly) | No | No |
| **File access** | HTTP links from server | In-chat artifacts | IDE file browser |
| **File preview** | Preview rendering (side panel) | Inline artifacts | IDE editor tabs |
| **Terminal** | ttyd + tmux (persistent, side panel) | N/A | Integrated terminal |
| **Claude Code** | Pre-installed CLI, interactive TTY | N/A | N/A |
| **Escape hatch** | Open server URLs, work independently | N/A | N/A |
| **File storage** | Docker volumes (server-side) | Chat context | Local/cloud mount |
| **Self-hosted** | Yes | No | No |
| **Any LLM** | Yes (OpenAI-compatible) | Claude only | Claude only |

## Detailed Comparison: Open Computer Use vs open-webui/open-terminal

[Open Terminal](https://github.com/open-webui/open-terminal) is a separate open-source project that also gives AI models code execution. Both solve "LLMs need somewhere to run code" but with different architectures.

| | Open Computer Use | open-webui/open-terminal |
|---|---|---|
| **In one sentence** | MCP server with managed Docker workspaces — browser, terminal, skills, sub-agents | Lightweight remote shell with file management via REST API |

### Quick Comparison

| Feature | Open Computer Use | open-webui/open-terminal |
|---------|-------------------|--------------------------|
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
| **Image variants** | Single full image (~11 GB virtual / ~4.5 GB disk) | 3 variants: full (4 GB), slim (430 MB), alpine (230 MB) |
| **Setup** | `docker compose up` | `docker run` or `pip install` |

### Architecture & Isolation

**Open Computer Use** creates a new Docker container for every chat session. If the AI breaks something — installs wrong packages, corrupts files, fills disk — only that chat is affected. Next chat starts fresh. Containers are cleaned up automatically after idle timeout.

**open-webui/open-terminal** runs a single container (or bare metal process) shared across sessions. Multi-user mode creates OS-level user accounts with `chmod 700` home directories for file isolation. The project docs explicitly note this is "not designed for production multi-user deployments" — all users share the same kernel, network, and system resources.

**Trade-off**: Open Computer Use provides stronger isolation at the cost of higher resource usage (~200-500 MB per session). open-webui/open-terminal is more lightweight but less isolated.

### MCP Tools: 5 vs 19

The two projects take opposite approaches.

**Open Computer Use** — 5 high-level tools:

| Tool | Description |
|------|-------------|
| `bash_tool` | Run commands with progress streaming and timeout |
| `view` | Read files/directories, resize images for context |
| `create_file` | Create files with content |
| `str_replace` | Edit files via find-and-replace |
| `sub_agent` | Delegate complex tasks to Claude Code |

**open-webui/open-terminal** — 19 granular tools from its REST API:

| Category | Tools |
|----------|-------|
| Files | list, read, write, display, replace, upload, delete, move, mkdir, archive |
| Search | grep, glob |
| Processes | run, list, status, input, kill |
| Network | list ports, port proxy |

**Trade-off**: Fewer powerful primitives (AI uses `bash_tool` for search, process management) vs. fine-grained operations that don't require shell knowledge.

### Security

| Aspect | Open Computer Use | open-webui/open-terminal |
|--------|-------------------|--------------------------|
| **Isolation** | Docker containers (kernel namespaces) | OS user accounts (`chmod 700`) |
| **Privilege escalation** | `no-new-privileges:true` | Passwordless sudo for container user |
| **Resource limits** | Per-container (2 GB RAM, 1 CPU default) | None (OS-level only) |
| **Network isolation** | Configurable | Egress firewall (iptables) |
| **Skill/upload mounts** | Read-only | N/A |

### What open-webui/open-terminal Has That We Don't

- **Jupyter notebooks** — create and execute notebooks with per-session kernels
- **Bare metal mode** — `pip install open-terminal`, no Docker needed
- **Port proxy** — reverse-proxy to localhost services for web dev
- **Lightweight variants** — 230 MB alpine image for edge/CI
- **Document text extraction** — reads 11 formats as text
- **Process stdin** — send input to running processes
- **Simpler setup** — single `docker run` command

### When to Choose What

**Choose Open Computer Use** for: production multi-user, live browser, document creation skills, Claude Code sub-agent, multiple MCP clients, cloud agent workflows.

**Choose open-webui/open-terminal** for: lightweight code execution, bare metal, Jupyter, port proxying, minimal footprint, simple single-container personal use.

**Use both together**: Open WebUI supports connecting to both simultaneously — open-webui/open-terminal for quick code execution, Open Computer Use for complex workflows.

## Docker Image Size

The sandbox image (`open-computer-use:latest`) is **~11 GB** uncompressed. Here's why:

| Component | Estimated Size |
|-----------|---------------|
| Ubuntu 24.04 base | ~80 MB |
| APT packages (LibreOffice, ffmpeg, JDK 21, tesseract, fonts, build-essential, graphviz, pandoc, ghostscript...) | ~1,800 MB |
| Python pip packages (opencv x3, jax+jaxlib, scipy, scikit-learn, pandas, mediapipe, onnxruntime, matplotlib, playwright, reportlab...) | ~1,200 MB |
| Node.js npm packages (mermaid-cli, sharp, react, typescript, pdf-lib, pptxgenjs... installed globally + /home/node_modules) | ~700 MB |
| Playwright Chromium browser | ~450 MB |
| Claude Code CLI + Playwright CLI | ~110 MB |
| Bun, Node.js 22, glab, ttyd, skills, fonts | ~160 MB |
| **Total (estimated layers)** | **~4,500 MB** |

> **Why `docker images` may show ~11 GB:** Docker reports the *virtual size* which includes all layers before squashing. Intermediate build layers (apt cache, pip cache, npm cache) inflate the number even though `apt-get clean` and `rm -rf` run later. The actual disk usage is closer to 4.5-5 GB. Use `docker system df -v` to see real disk consumption.

### Top candidates for size reduction

| Optimization | Potential savings |
|-------------|-------------------|
| Remove build-essential/gcc after pip install (multi-stage build) | ~300 MB |
| Keep only `opencv-python-headless`, drop `opencv-python` + `opencv-contrib-python` | ~200 MB |
| Deduplicate npm packages (global + /home/node_modules overlap) | ~300 MB |
| Evaluate jax + jaxlib necessity | ~250 MB |
| Drop `fonts-noto-cjk` if CJK not needed | ~120 MB |
| **Total potential savings** | **~1,170 MB** |
