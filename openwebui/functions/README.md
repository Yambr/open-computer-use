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
| `FILE_SERVER_URL` | `http://localhost:8081` | File server URL (browser-accessible for download links) |
| `ENABLE_ARCHIVE_BUTTON` | `true` | Add "Download archive" button to responses |
| `INJECT_SYSTEM_PROMPT` | `true` | Inject skills and file URL into system prompt |

## Installation

1. **Workspace > Functions** → Create → paste `computer_link_filter.py`
2. Enable globally (toggle in Functions list)
3. Tool `ai_computer_use` must be installed (filter reads its valves for internal URL)

Auto-configured by `docker-compose.webui.yml` via `init.sh`.

## How File Links Work

```
inlet() → Injects file_base_url into system prompt
       → AI generates: [file.docx](http://server:8081/files/{chat_id}/file.docx)
outlet() → Appends archive download button
```

The model receives the mapping: `/mnt/user-data/outputs/` → `{FILE_SERVER_URL}/files/{chat_id}/` and generates correct HTTP links directly.

## Related

- [tools/README.md](../tools/README.md) — MCP client tool
- [SKILLS.md](../../docs/SKILLS.md) — all available skills
- [Main README](../../README.md#open-webui-integration) — full setup guide
