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
Open Terminal uses the **IDE's native file explorer** — files appear in the file tree and open in editor tabs. Our approach uses a **server-side preview renderer** that works in any browser, without an IDE.

### vs. Claude.ai
Claude.ai renders **artifacts** (HTML, React, SVG) inline in the chat. Our side panel is separate from the chat and supports a wider range of file types (office documents, PDFs, archives, etc.) via server-side rendering.

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
| **File preview** | Server-side rendering (side panel) | Inline artifacts | IDE editor tabs |
| **Terminal** | ttyd + tmux (persistent, side panel) | N/A | Integrated terminal |
| **Claude Code** | Pre-installed CLI, interactive TTY | N/A | N/A |
| **Escape hatch** | Open server URLs, work independently | N/A | N/A |
| **File storage** | Docker volumes (server-side) | Chat context | Local/cloud mount |
| **Self-hosted** | Yes | No | No |
| **Any LLM** | Yes (OpenAI-compatible) | Claude only | Claude only |
