# Computer Link Filter

**File**: `computer_link_filter.py` — required companion to `computer_use_tools.py`.

## What It Does

| Phase | Action |
|-------|--------|
| **Inlet** (before LLM) | Injects system prompt: file server URL, `<available_skills>` XML (13 skills), output path mapping |
| **Outlet** (after LLM) | Adds "View file" link + "Download all as archive" button when response contains file URLs |

Without this filter, the model won't know about skills or how to generate file download links.

## Valves

| Valve | Default | Description |
|-------|---------|-------------|
| `ORCHESTRATOR_URL` | `http://computer-use-server:8081` | Internal URL of Computer Use server (server→server fetch of `/system-prompt`). Not browser-facing — the public URL is owned by the server. |
| `PREVIEW_MODE` | `"button"` | Where the preview link appears: `button` (markdown link — the frontend patch promotes it to an inline artifact) \| `off` |
| `ARCHIVE_BUTTON` | `"on"` | Add "Download archive" button to responses: `on` \| `off` |
| `INJECT_SYSTEM_PROMPT` | `true` | Inject skills and file URL into system prompt |

See [`docs/openwebui-filter.md`](../../docs/openwebui-filter.md#valves-reference) for the full Valves reference.

## Installation

1. **Workspace > Functions** → Create → paste `computer_link_filter.py`
2. Enable globally (toggle in Functions list)
3. Tool `ai_computer_use` must be installed (filter reads its valves for internal URL)

Auto-configured by `docker-compose.webui.yml` via `init.sh`.

## How File Links Work

```
inlet() → Injects the server-baked /system-prompt text (the server substitutes its
          own PUBLIC_BASE_URL into the {file_base_url} placeholder before returning it).
       → AI generates: [file.docx]({PUBLIC_BASE_URL}/files/{chat_id}/file.docx)
outlet() → Appends preview-button + archive-download markdown links.
```

The model receives the mapping `/mnt/user-data/outputs/` → `{PUBLIC_BASE_URL}/files/{chat_id}/` and generates correct HTTP links directly. The filter never sees the public URL as a Valve — the server is the single source of truth and delivers it to `outlet()` via the `X-Public-Base-URL` response header on `/system-prompt` (cached alongside the prompt).

## Related

- [tools/README.md](../tools/README.md) — MCP client tool
- [SKILLS.md](../../docs/SKILLS.md) — all available skills
- [Main README](../../README.md#open-webui-integration) — full setup guide
