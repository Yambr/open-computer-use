# Comparison: Open Computer Use vs open-webui/open-terminal

Both projects are self-hosted and give LLMs a place to run code. They solve the same core problem with different architectures. Claude.ai and OpenAI Operator are cloud-only, not self-hosted — we drew inspiration from them, but a detailed comparison isn't useful here. See the overview table for a quick reference.

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
| **Image size** | ~11 GB (full stack) | 4 GB / 430 MB / 230 MB | N/A | N/A |

---

## Architecture and Isolation

**Open Computer Use** creates a new Docker container for every chat session. If the AI breaks something (installs wrong packages, corrupts files, fills disk), only that chat is affected. Next chat starts fresh. Containers are cleaned up automatically after idle timeout. Resource limits (2 GB RAM, 1 CPU) are enforced per container.

**open-terminal** runs a single container (or bare metal process) shared across sessions. Multi-user mode creates OS-level user accounts with isolated home directories (`chmod 2770` + group membership), file ownership enforcement via `sudo chown`, and path validation to prevent cross-user access. For container-per-user isolation, the separate [Terminals](https://github.com/open-webui/terminals) project manages dedicated open-terminal containers per user.

**Trade-off:** Open Computer Use provides stronger isolation at the cost of higher resource usage (~200-500 MB per session). open-terminal is lighter but shares kernel, network, and system resources between users. open-terminal's own documentation [notes](https://github.com/open-webui/open-terminal#built-in-multi-user-isolation) that single-container multi-user mode is not designed for production multi-user deployments.

---

## MCP Tools: 5 vs 15

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
| **Privilege escalation** | `no-new-privileges:true` | Passwordless sudo (full image only; slim/alpine have no sudo) |
| **Resource limits** | Per-container (2 GB RAM, 1 CPU default) | OS-level only |
| **Egress firewall** | Configurable (Docker network policies) | Built-in DNS whitelist (dnsmasq + iptables + ipset), CAP_NET_ADMIN dropped after setup |
| **API key auth** | Bearer token (MCP_API_KEY) | Bearer token, constant-time comparison (hmac.compare_digest) |
| **Path traversal** | Sanitized chat_id + safe_path validation | resolve_path + is_path_allowed validation |
| **Skill/upload mounts** | Read-only | N/A |

---

## What Open Computer Use offers that open-terminal doesn't

- **Live shared browser** — Playwright + CDP streaming: AI automates via CDP, user watches and interacts in real-time (clicks, types passwords, scrolls) in the same Chromium instance. Not screenshot-based.
- **Document creation skills** — 13 built-in skills with scripts and templates for generating professional documents:
  - **PPTX**: HTML/CSS → PowerPoint via custom `html2pptx` library, or template-based editing with `inventory.py` (extract shapes), `replace.py` (smart text replacement), `thumbnail.py` (visual validation)
  - **DOCX**: create from scratch with `docx-js`, or edit existing with tracked changes (OOXML redlining via `<w:ins>`/`<w:del>` tags)
  - **XLSX**: formula-based spreadsheets with `openpyxl`, automatic recalculation via LibreOffice UNO (`recalc.py`), error scanning (#REF!, #DIV/0!)
  - **PDF**: create with ReportLab (pre-registered Cyrillic/Emoji fonts), extract tables with tabula-py/camelot, fill forms, merge/split
  - open-terminal can extract text from 11 document formats but has no document creation pipeline
- **Claude Code sub-agent** — delegate complex multi-step tasks to Claude Code running autonomously inside the container. Supports model selection (sonnet/opus), session resume after timeout, cost/turns tracking, and auto-configured MCP servers.
- **Server-side file preview** — preview panel renders DOCX (via Mammoth), XLSX (multi-sheet tables), PDF (page-by-page canvas), PPTX (slide navigation), Markdown, images, and code with syntax highlighting. Works from any MCP client, not tied to Open WebUI's UI.
- **Container-per-chat isolation** — every chat gets a fresh Docker container with its own filesystem, network, and resource limits. Containers auto-cleanup after idle timeout. No cross-session contamination.
- **Persistent terminal** — ttyd + tmux: terminal sessions survive disconnects, user can switch between chat and terminal freely, or leave the chat interface entirely and work in the container via direct URL.
- **Skill auto-injection** — skills with scripts, templates, and examples are mounted read-only into containers and injected into the system prompt. The AI gets structured instructions, not just text. Per-user custom skills via Settings Wrapper API.
- **Pre-installed stack** — 200+ packages: LibreOffice suite, Playwright + Chromium, OCR (Tesseract), computer vision (OpenCV), image processing (ImageMagick, Pillow, sharp), GitLab CLI (glab), fonts (DejaVu, Noto CJK/Emoji for PDF/reports), ML libraries (JAX, ONNX Runtime, MediaPipe). open-terminal's full image has ~50 packages.
- **Vision AI** — `describe-image` skill for multi-modal image analysis (charts, diagrams, screenshots) via Vision API.
- **Multi-client MCP support** — tested with Open WebUI, Claude Desktop, n8n, LiteLLM, and custom HTTP clients. open-terminal also supports multiple transports (stdio + streamable-http via FastMCP) but is primarily tested with Open WebUI.
- **Container resurrection** — if a container is removed (e.g. by cron), saved metadata allows recreating it with the same volumes, environment, and MCP config.
- **Smart tool output** — bash_tool streams progress with 15s heartbeats, caps output at 30K chars (first/last 15K), handles semantic exit codes (grep returning 1 is "no match", not error).

## What open-terminal offers that we don't

- **Jupyter notebooks** — per-session kernels via nbclient, create and execute notebooks through the API
- **Bare metal mode** — `pip install open-terminal`, no Docker needed
- **Port proxy** — HTTP reverse-proxy to localhost services for web development
- **Lightweight image variants** — slim (430 MB, Debian) and alpine (230 MB) for minimal footprint
- **Document text extraction** — reads 11 formats as plain text: PDF, DOCX, PPTX, XLSX, XLS, RTF, ODT, ODS, ODP, EPUB, EML
- **Process stdin** — send input to running processes (interactive CLI tools)
- **Terminal sessions** — real PTY terminals via WebSocket with resize support
- **Session CWD tracking** — per-session working directory, all file/execute operations resolve relative paths against it
- **Runtime package installation** — install apt/pip/npm packages at container startup via environment variables
- **Docker-in-Docker** — Docker CLI + Compose + Buildx pre-installed, mount the socket for full DinD
- **System prompt endpoint** — `/system` returns environment-aware prompt for LLM grounding
- **TOML config files** — configure via `~/.config/open-terminal/config.toml` or `/etc/open-terminal/config.toml`
- **Log management** — per-process JSONL logs with configurable retention (7 days default) and flush tuning
- **Simpler setup** — single `docker run` command
- **Built-in MCP server** — `open-terminal mcp` via FastMCP, supports stdio and streamable-http transports

---

## When to choose what

**Choose Open Computer Use** for: production multi-user deployments with per-chat isolation, live browser automation, document creation (PPTX, DOCX, XLSX, PDF), Claude Code sub-agent delegation, server-side file preview, and workflows that span multiple MCP clients.

**Choose open-terminal** for: lightweight code execution, bare metal usage, Jupyter notebooks, port proxying for web development, minimal resource footprint, and simple single-container personal setups.

**Use both together:** Open WebUI supports connecting to both simultaneously. Use open-terminal for quick code execution and Open Computer Use for complex workflows that need browser, skills, or sub-agents.
