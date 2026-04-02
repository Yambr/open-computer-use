# Comparison: Open Computer Use vs open-webui/open-terminal

Both projects are self-hosted and give LLMs a place to run code. They solve the same core problem with two fundamentally different architectural approaches — both for the technical stack and for the AI/user interaction model. This is not a "which is better" document; it's a map of trade-offs to help you pick the right tool for your use case.

> **Note:** We respect the open-terminal team and their work. If you spot any inaccuracies in this comparison, please [open an issue](https://github.com/Yambr/open-computer-use/issues) — we want this to be fair and factual.

Claude.ai and OpenAI Operator are cloud-only, not self-hosted — we drew inspiration from them, but a detailed comparison isn't useful here. See the overview table for a quick reference.

## Overview

| Feature | Open Computer Use | [open-terminal](https://github.com/open-webui/open-terminal) | Claude.ai | OpenAI Operator |
|---------|-------------------|---------------|-----------|-----------------|
| **Self-hosted** | Yes | Yes | No | No |
| **Any LLM** | Yes (OpenAI-compatible) | Any (via Open WebUI) | Claude only | GPT only |
| **Code execution** | Full Linux sandbox | Sandbox / bare metal | Sandbox | No |
| **Live browser** | CDP streaming (shared, interactive) | No | Screenshot-based | Screenshot-based |
| **Terminal** | ttyd + tmux (persistent, side panel) | PTY + WebSocket | IDE + terminal | N/A |
| **Sub-agent** | Claude Code CLI, interactive TTY + MCP | N/A | Built-in | N/A |
| **Skills system** | 13 built-in (auto-injected) + custom | Open WebUI native (text-only) | Custom instructions | N/A |
| **Document creation** | PPTX, DOCX, XLSX, PDF via skills | No | Via code | N/A |
| **File preview** | Server-side rendering (DOCX, PDF, PPTX, XLSX, code) | Client-side (via Open WebUI) | IDE | N/A |
| **Container isolation** | Docker (runc), per chat | Shared container (OS-level users) | Docker (gVisor) | N/A |
| **MCP server** | Streamable HTTP | FastMCP (stdio + streamable-http) | N/A | N/A |
| **Image size** | ~11 GB (full stack) | ~2 GB / ~200 MB / ~100 MB | N/A | N/A |
| **Setup complexity** | Docker Compose + reverse proxy + env config | Single `docker run` or `pip install` | N/A | N/A |
| **Jupyter notebooks** | No | Yes (per-session kernels via nbclient) | No | No |
| **Bare metal** | No (Docker required) | Yes (`pip install open-terminal`) | No | No |
| **Port proxy** | No | Yes (HTTP reverse-proxy to localhost services) | No | No |
| **Ecosystem** | Multi-client MCP server (Open WebUI, n8n, OpenAI Agents SDK, LiteLLM) | Native Open WebUI integration + enterprise orchestrator ([Terminals](https://github.com/open-webui/terminals)) | N/A | N/A |

---

## Architecture and Isolation

**Open Computer Use** creates a new Docker container for every chat session. If the AI breaks something (installs wrong packages, corrupts files, fills disk), only that chat is affected. Next chat starts fresh. Containers are cleaned up automatically after idle timeout. Resource limits (2 GB RAM, 1 CPU) are enforced per container.

**open-terminal** runs a single container (or bare metal process) shared across sessions. Multi-user mode creates OS-level user accounts with isolated home directories (`chmod 2770` + group membership), file ownership enforcement via `sudo chown`, and path validation to prevent cross-user access. For container-per-user isolation, the separate [Terminals](https://github.com/open-webui/terminals) project manages dedicated open-terminal containers per user.

**Why this matters:** Non-technical users + AI agent executing arbitrary code is the worst case for a shared environment. The user doesn't control what the agent does, and the agent can do anything — install packages, fill disk, corrupt files, spawn processes. Container-per-chat means each session is disposable: if something breaks, only that chat is affected, and the next one starts clean.

**Trade-off:** Each container has a 2 GB RAM limit (configurable via `CONTAINER_MEM_LIMIT`). This is a ceiling, not an allocation — an idle container or one running simple commands uses very little memory. Heavy tasks like Chromium or LibreOffice consume more, up to the limit. open-terminal is lighter but shares kernel, network, and system resources between users. open-terminal's own documentation [notes](https://github.com/open-webui/open-terminal#built-in-multi-user-isolation) that single-container multi-user mode is not designed for production multi-user deployments.

---

## MCP Tools

The two projects take opposite approaches to tool design.

**Open Computer Use** exposes 5 high-level tools:

| Tool | Description |
|------|-------------|
| `bash_tool` | Run commands with real-time progress streaming, 15s heartbeats, 30K char output cap, timeout handling |
| `view` | Read files/directories with line numbers, auto-resize images to base64, detect binary formats |
| `create_file` | Create files with auto-parent-directory creation |
| `str_replace` | Edit files via find-and-replace with uniqueness validation |
| `sub_agent` | Delegate to Claude Code with model selection, session resume, MCP auto-config, cost tracking |

**open-terminal** exposes 15 core MCP tools via FastMCP (+ 4 notebook tools when enabled):

| Category | Tools |
|----------|-------|
| Files | list, read, write, display, replace, upload, grep, glob |
| Processes | execute, list, status, input, kill |
| Notebooks | create session, execute cell, get session, delete session |

**Trade-off:** Fewer powerful primitives (the AI uses `bash_tool` for search, process management, and anything else) vs. fine-grained operations that don't require shell knowledge.

---

## Security

| Aspect | Open Computer Use | open-terminal |
|--------|-------------------|---------------|
| **Isolation** | Docker containers (kernel namespaces) | OS user accounts (chmod 2770 + group membership) |
| **Privilege escalation** | Non-root user with passwordless sudo; `no-new-privileges` flag | Non-root user with passwordless sudo (full image); no sudo in slim/alpine |
| **Resource limits** | Per-container (2 GB RAM, 1 CPU default) | OS-level only |
| **Egress firewall** | Configurable (Docker network policies) | Built-in DNS whitelist (dnsmasq + iptables + ipset), CAP_NET_ADMIN dropped after setup |
| **API key auth** | Bearer token (MCP_API_KEY) | Bearer token, constant-time comparison (hmac.compare_digest) |
| **Path traversal** | Sanitized chat_id + safe_path validation | resolve_path + is_path_allowed validation |
| **Skill/upload mounts** | Read-only | N/A |

---

## What Open Computer Use offers that open-terminal doesn't

- **Document creation skills** — 13 built-in skills with scripts and templates for generating professional documents:
  - **PPTX**: HTML/CSS → PowerPoint via custom `html2pptx` library, or template-based editing with `inventory.py` (extract shapes), `replace.py` (smart text replacement), `thumbnail.py` (visual validation)
  - **DOCX**: create from scratch with `docx-js`, or edit existing with tracked changes (OOXML redlining via `<w:ins>`/`<w:del>` tags)
  - **XLSX**: formula-based spreadsheets with `openpyxl`, automatic recalculation via LibreOffice UNO (`recalc.py`), error scanning (#REF!, #DIV/0!)
  - **PDF**: create with ReportLab (pre-registered Cyrillic/Emoji fonts), extract tables with tabula-py/camelot, fill forms, merge/split
- **Skill auto-injection** — skills with scripts, templates, and examples are mounted read-only into containers and injected into the system prompt. The AI gets structured instructions, not just text. Per-user custom skills via Settings Wrapper API.
- **Live shared browser** — Playwright + CDP streaming: AI automates via CDP, user watches and interacts in real-time (clicks, types passwords, scrolls) in the same Chromium instance. Not screenshot-based.
- **Claude Code sub-agent** — delegate complex multi-step tasks to Claude Code running autonomously inside the container. Supports model selection (sonnet/opus), session resume after timeout, cost/turns tracking, and auto-configured MCP servers.
- **Server-side file preview** — preview panel renders DOCX (via Mammoth), XLSX (multi-sheet tables), PDF (page-by-page canvas), PPTX (slide navigation), Markdown, images, and code with syntax highlighting. Works from any MCP client, not tied to Open WebUI's UI.
- **Container-per-chat isolation** — every chat gets a fresh Docker container with its own filesystem, network, and resource limits. Containers auto-cleanup after idle timeout. No cross-session contamination.
- **Persistent terminal** — ttyd + tmux: terminal sessions survive disconnects, user can switch between chat and terminal freely, or leave the chat interface entirely and work in the container via direct URL.
- **Pre-installed stack** — ~180 packages: LibreOffice suite, Playwright + Chromium, OCR (Tesseract), computer vision (OpenCV), image processing (ImageMagick, Pillow, sharp), GitLab CLI (glab), fonts (DejaVu, Noto CJK/Emoji for PDF/reports), ML libraries (JAX, ONNX Runtime, MediaPipe). Image size is ~11 GB vs open-terminal's ~2 GB / ~200 MB / ~100 MB.
- **Vision AI** — `describe-image` skill for multi-modal image analysis (charts, diagrams, screenshots) via Vision API.
- **Multi-client MCP support** — tested with Open WebUI, n8n, OpenAI Agents SDK, and LiteLLM. open-terminal also supports multiple transports (stdio + streamable-http via FastMCP) but is primarily tested with Open WebUI.
- **Container resurrection** — if a container is removed (e.g. by cron), saved metadata allows recreating it with the same volumes, environment, and MCP config.
- **Smart tool output** — bash_tool streams progress with 15s heartbeats, caps output at 30K chars (first/last 15K), handles semantic exit codes (grep returning 1 is "no match", not error).

## What open-terminal offers that we don't

- **Jupyter notebooks** — per-session kernels via nbclient, create and execute notebooks through the API
- **Bare metal mode** — `pip install open-terminal`, no Docker needed
- **Port proxy** — HTTP reverse-proxy to localhost services for web development
- **Lightweight image variants** — slim (~200 MB, Debian) and alpine (~100 MB) for minimal footprint
- **Document text extraction as API** — dedicated endpoint reads 11 formats as plain text (PDF, DOCX, PPTX, XLSX, XLS, RTF, ODT, ODS, ODP, EPUB, EML)
- **Process stdin** — send input to running processes (interactive CLI tools)
- **Session CWD tracking** — per-session working directory for the API, since open-terminal is stateless between requests
- **Runtime package installation via env vars** — `OPEN_TERMINAL_PACKAGES="cowsay"` installs apt/pip/npm packages at container startup without rebuilding the image
- **Docker-in-Docker** — Docker CLI + Compose + Buildx pre-installed, mount the socket for full DinD
- **TOML config files** — configure via `~/.config/open-terminal/config.toml` or `/etc/open-terminal/config.toml`
- **Log management** — per-process JSONL logs with configurable retention (7 days default) and flush tuning
- **Simpler setup** — single `docker run` command

---

## When to choose what

**Choose Open Computer Use** for workflows that need browser automation, document creation, or Claude Code sub-agent. Container-per-chat isolation gives each session its own filesystem, network, and resource limits. Works across MCP clients (Open WebUI, n8n, OpenAI Agents SDK, LiteLLM).

**Choose open-terminal** for terminal-first workflows, especially in Open WebUI environments. Native integration with the Open WebUI ecosystem, minimal setup (single `docker run` or `pip install`), Jupyter notebooks, port proxying, and image variants from ~100 MB to ~2 GB. For multi-user deployments, the [Terminals](https://github.com/open-webui/terminals) project provides enterprise-grade container orchestration.

**Use both together:** Open WebUI supports connecting to both simultaneously — choose per task based on what each does best.
