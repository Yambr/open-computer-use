# Sub-Agent Tab -- Terminal + Claude Code Monitoring

## Overview

The "Sub-Agent" tab in the preview SPA adds two key capabilities:

1. **Headless sub-agent monitoring** -- see running Claude Code processes, kill stuck ones
2. **Interactive terminal** -- launch Claude Code manually, resume interrupted sessions

## Architecture

```
Browser (xterm.js) <-- WS --> computer-use-orchestrator <-- WS --> Container ttyd:7681
                              (proxy)              (tmux + bash)
```

The terminal uses the same pattern as the browser (CDP proxy):
- **ttyd** -- WebSocket terminal server inside the container (port 7681)
- **tmux** -- persistent session (reconnectable, scroll history)
- **computer-use-orchestrator** -- transparent WebSocket proxy (same as for Chromium CDP)
- **xterm.js** -- terminal in the browser

### Security

| Endpoint | Auth | Access |
|----------|------|--------|
| `/terminal/{chat_id}/status` | chat_id | Check ttyd |
| `/terminal/{chat_id}/ws` | chat_id | WebSocket to ttyd |
| `/terminal/{chat_id}/start-ttyd` | chat_id | Start ttyd (docker exec) |
| `/terminal/{chat_id}/sessions` | chat_id | List JSONL sessions |
| `/terminal/{chat_id}/processes` | chat_id | ps claude |
| `/terminal/{chat_id}/processes/{pid}/kill` | chat_id | kill claude |

- Terminal data does NOT go through docker.sock -- only TCP proxy to the container
- docker.sock is only used for: IP lookup, start-ttyd, sessions/processes listing, keep-alive timer
- Container escape is not possible (no-new-privileges, sandboxed)

## Components

### Container (Dockerfile)
- `ttyd` -- binary at `/usr/local/bin/ttyd` (downloaded from GitHub releases)
- `tmux` -- from apt
- `ENABLE_TOOL_SEARCH=true` -- reduces MCP tool context by 85%
- `~/.claude/CLAUDE.md` -- written by entrypoint (workspace paths, output rules)

### File-server (app.py)
- 6 endpoints in the "Terminal Proxy" section
- WebSocket proxy -- copy of `browser_ws_proxy()` with port 7681
- Keep-alive task -- resets shutdown timer every 5 min while WS is alive

### Preview SPA (frontend)
- Two modes: **Dashboard** (default) and **Workspace** (xterm.js)
- Dashboard: description, "New session" button, training link, sessions table, processes
- Workspace: xterm.js + ttyd protocol, toolbar (Back, Clear, Terminate)

### Nginx
- Location `/terminal/` -- WebSocket upgrade, 1 hour timeout

### OpenWebUI (computer_link_filter.py)
- Detect `sub_agent` in tool_calls -> inject preview link -> auto-open Artifacts

## Lifecycle

1. AI launches sub_agent -> container is created
2. computer_link_filter injects preview link -> Artifacts open
3. User sees dashboard with processes and sessions
4. Can stop a stuck process or continue a session in the terminal
5. ttyd starts lazily on first click of "New session" / "Continue"
6. tmux session is persistent -- reconnectable on disconnect
7. Container lives while WS is connected (keep-alive), dies 10 min after disconnect

## Sub-agent Timeout

If sub_agent() times out (3600s) but Claude Code is still running:
- The main AI receives a message with a bash wait command
- The user can observe in the Sub-Agent tab
- Can stop or continue in the terminal

## Files

| File | What changed |
|------|-------------|
| `Dockerfile` | +ttyd, +tmux, +ENABLE_TOOL_SEARCH, CLAUDE.md in entrypoint |
| `computer-use-orchestrator/app.py` | +6 terminal endpoints, +SPA (CSS+JS+HTML) |
| `computer-use-orchestrator/mcp_tools.py` | +sub-agent timeout handling |
| `computer-use-orchestrator/static/xterm*` | +xterm.js, +addon-fit, +addon-web-links |
| `nginx/nginx.conf` | +location /terminal/ |
| `openwebui-functions/computer_link_filter.py` | +sub_agent detection |
