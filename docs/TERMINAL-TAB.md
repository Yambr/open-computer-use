# Sub-Agent Tab — Terminal + Claude Code

## Overview

The "Sub-Agent" tab in the preview panel provides:

1. **Claude Code monitoring** — see running processes, kill stuck ones
2. **Interactive terminal** — launch Claude Code manually, resume interrupted sessions

## How it works

```
Browser (xterm.js)  ←WebSocket→  Computer Use Server  ←WebSocket→  Container (ttyd:7681)
                                 (proxy on :8081)                   (tmux + bash)
```

- **ttyd** — WebSocket terminal server inside the container (port 7681)
- **tmux** — persistent session (reconnectable, scroll history preserved)
- **Computer Use Server** — transparent WebSocket proxy
- **xterm.js** — terminal rendering in the browser

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /terminal/{chat_id}/status` | Check if ttyd is running |
| `WebSocket /terminal/{chat_id}/ws` | Terminal WebSocket connection |
| `POST /terminal/{chat_id}/start-ttyd` | Start ttyd (lazy — first click) |
| `GET /terminal/{chat_id}/sessions` | List Claude Code JSONL sessions |
| `GET /terminal/{chat_id}/processes` | List running Claude Code processes |
| `POST /terminal/{chat_id}/processes/{pid}/kill` | Kill a stuck process |

## Lifecycle

1. AI calls `sub_agent` → sandbox container is created
2. Filter injects preview link → Artifacts panel opens
3. User sees dashboard with processes and sessions
4. Click **"Open terminal"** → ttyd starts, Claude Code launches
5. tmux session is persistent — reconnectable on disconnect
6. Container stays alive while WebSocket is connected (keep-alive heartbeat)
7. Container auto-stops after idle timeout (default: 10 min)

## Dangerous Mode

Toggle **"Skip permission prompts"** to run Claude Code without confirmation dialogs. Sets `NO_AUTOSTART=1` environment variable so .bashrc skips its autostart and the frontend can inject `claude --dangerously-skip-permissions` instead. Use only for trusted tasks.

## Sub-agent Timeout

If `sub_agent()` times out (default: 3600s) but Claude Code is still running:
- The model receives a timeout message
- User can observe progress in the Sub-Agent tab
- Can stop or continue interactively in the terminal

## MCP Servers in Claude Code

When MCP server names are passed via `X-MCP-Servers` header, the server auto-generates `~/.mcp.json` inside the container. Claude Code picks it up and can use those MCP servers autonomously. See [MCP.md](MCP.md#mcp-servers-for-claude-code-sub-agent) for details.
