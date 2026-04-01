# Comparison with Alternatives

How Open Computer Use compares to [open-webui/open-terminal](https://github.com/open-webui/open-terminal), Claude.ai (Claude Code web), and OpenAI Operator.

## Overview

| Feature | Open Computer Use | Claude.ai (Claude Code web) | [open-terminal](https://github.com/open-webui/open-terminal) | OpenAI Operator |
|---------|-------------------|-----------|---------------|-----------------|
| **Self-hosted** | Yes | No | Yes | No |
| **Any LLM** | Yes (OpenAI-compatible) | Claude only | Any (via Open WebUI) | GPT only |
| **Code execution** | Full Linux sandbox | Sandbox (Claude Code web) | Sandbox / bare metal | No |
| **Live browser** | CDP streaming (shared, interactive) | Screenshot-based | No | Screenshot-based |
| **Terminal** | ttyd + tmux (persistent, side panel) | Claude Code web (IDE + terminal) | PTY + WebSocket | N/A |
| **Sub-agent** | Claude Code CLI, interactive TTY + MCP | Claude Code web (built-in) | N/A | N/A |
| **Skills system** | 13 built-in (auto-injected) + custom | Built-in skills + custom instructions | Open WebUI native (text-only) | N/A |
| **File preview** | Server-side rendering (side panel) | Side panel artifacts + IDE | Client-side (via Open WebUI) | N/A |
| **Container isolation** | Docker (runc), per chat | Docker (gVisor) | Shared container (OS-level users) | N/A |
| **MCP server** | Yes (Streamable HTTP) | N/A | Yes (FastMCP) | N/A |
| **Image size** | ~11 GB (full stack) | N/A | 4 GB / 430 MB / 230 MB | N/A |

---

## vs. open-webui/open-terminal

[Open Terminal](https://github.com/open-webui/open-terminal) is a lightweight, self-hosted terminal that gives AI agents a dedicated environment to run commands, manage files, and execute code via a REST API. Both projects solve the same core problem — LLMs need somewhere to run code — but take different architectural approaches.

### Architecture and Isolation

**Open Computer Use** creates a new Docker container for every chat session. If the AI breaks something (installs wrong packages, corrupts files, fills disk), only that chat is affected. Next chat starts fresh. Containers are cleaned up automatically after idle timeout.

**open-terminal** runs a single container (or bare metal process) shared across sessions. Multi-user mode creates OS-level user accounts with isolated home directories (`chmod 2770` + group membership), file ownership enforcement via `sudo chown`, and path validation to prevent cross-user access. For container-per-user isolation, the separate [Terminals](https://github.com/open-webui/terminals) project manages dedicated open-terminal containers per user.

**Trade-off:** Open Computer Use provides stronger isolation at the cost of higher resource usage (~200-500 MB per session). open-terminal is lighter but shares kernel, network, and system resources between users. open-terminal's own documentation [notes](https://github.com/open-webui/open-terminal#built-in-multi-user-isolation) that single-container multi-user mode is not designed for production multi-user deployments.

### MCP Tools: 5 vs 15

The two projects take opposite approaches to tool design.

**Open Computer Use** exposes 5 high-level tools:

| Tool | Description |
|------|-------------|
| `bash_tool` | Run commands with progress streaming and timeout |
| `view` | Read files/directories, resize images for context |
| `create_file` | Create files with content |
| `str_replace` | Edit files via find-and-replace |
| `sub_agent` | Delegate complex tasks to Claude Code |

**open-terminal** exposes 15 core MCP tools via FastMCP (+ 4 notebook tools when enabled):

| Category | Tools |
|----------|-------|
| Files | list, read, write, display, replace, upload, grep, glob |
| Processes | execute, list, status, input, kill |
| Notebooks | create session, execute cell, get session, delete session |

**Trade-off:** Fewer powerful primitives (the AI uses `bash_tool` for search, process management, and anything else) vs. fine-grained operations that don't require shell knowledge.

### Security

| Aspect | Open Computer Use | open-terminal |
|--------|-------------------|---------------|
| **Isolation** | Docker containers (kernel namespaces) | OS user accounts (chmod 2770 + group membership) |
| **Privilege escalation** | `no-new-privileges:true` | Passwordless sudo (full image only; slim/alpine have no sudo) |
| **Resource limits** | Per-container (2 GB RAM, 1 CPU default) | OS-level only |
| **Egress firewall** | Configurable (Docker network policies) | Built-in DNS whitelist (dnsmasq + iptables + ipset), CAP_NET_ADMIN dropped after setup |
| **API key auth** | Bearer token (MCP_API_KEY) | Bearer token, constant-time comparison (hmac.compare_digest) |
| **Skill/upload mounts** | Read-only | N/A |

### What open-terminal offers that we don't

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

### When to choose what

**Choose Open Computer Use** for: production multi-user deployments, live browser automation, document creation skills (PPTX, DOCX, XLSX, PDF), Claude Code sub-agent, workflows that need multiple MCP clients, and cloud agent pipelines.

**Choose open-terminal** for: lightweight code execution, bare metal usage, Jupyter notebooks, port proxying for web development, minimal resource footprint, and simple single-container personal setups.

**Use both together:** Open WebUI supports connecting to both simultaneously. Use open-terminal for quick code execution and Open Computer Use for complex workflows that need browser, skills, or sub-agents.

---

## vs. Claude.ai (Claude Code web)

Claude.ai offers [Computer Use](https://docs.anthropic.com/en/docs/agents-and-tools/computer-use) and Claude Code web — a cloud-based IDE with terminal, browser, and file management. The key architectural differences:

**Browser:** Claude.ai Computer Use is screenshot-based — the AI takes a screenshot, analyzes it with vision, decides where to click, then takes another screenshot. Open Computer Use uses live CDP streaming where both the AI and user interact with the same Chromium instance in real-time. The user can type directly into the browser (e.g. login credentials) while the AI automates via Playwright.

**Files:** Claude.ai shows artifacts in a side panel alongside the conversation — files are part of the chat context. Open Computer Use keeps files on the server (Docker volumes) and the chat only contains HTTP links. No size limits, direct URL access, zip download.

**Terminal:** Claude Code web provides a built-in IDE with terminal. Open Computer Use pre-installs Claude Code CLI in every sandbox — users can access it via the sub-agent tool or open a terminal tab and work independently. Users can also leave the chat interface entirely and work directly in the container.

**Key differences:** Open Computer Use is self-hosted, works with any LLM (not just Claude), and is open source. Claude.ai is a managed cloud service with tighter integration but no self-hosting option.

---

## vs. OpenAI Operator

[OpenAI Operator](https://operator.chatgpt.com/) is a cloud-based browser automation agent. It navigates websites via screenshots (similar to Claude.ai Computer Use) and can hand control to the user for sensitive actions like login.

Open Computer Use is a fundamentally different product: a self-hosted MCP server with full Linux sandboxes, code execution, document creation, and terminal access. The overlap is limited to browser automation, where Open Computer Use uses live CDP streaming instead of screenshots.
