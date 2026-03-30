# Open WebUI Integration

Everything needed to connect [Open WebUI](https://github.com/open-webui/open-webui) to [Open Computer Use](https://github.com/Yambr/open-computer-use). Works with stock Open WebUI — no fork required.

## Components

| # | Component | Type | Required | What it does |
|---|-----------|------|----------|-------------|
| 1 | [**tools/computer_use_tools.py**](tools/) | Tool | Yes | MCP client proxy — forwards `bash`, `create_file`, `str_replace`, `view`, `sub_agent` calls to the Computer Use Server |
| 2 | [**functions/computer_link_filter.py**](functions/) | Filter | Yes | Injects skills list + file server URL into system prompt; adds "Download archive" button to responses |
| 3 | [**patches/**](patches/) | Build-time | Recommended | Quality-of-life fixes: auto-open file preview, truncate large tool args, skip unnecessary RAG processing |

**Tool + Filter = minimum working setup.** Patches improve UX but everything works without them.

## Quick Start

**Automatic** (recommended): `docker-compose.webui.yml` builds a patched Open WebUI image and auto-installs tool + filter on first startup via `init.sh`.

**Manual**: Install tool and filter through Workspace UI, set Tool ID to `ai_computer_use`, enable filter globally. See [setup guide](../README.md#open-webui-integration).

## Patches

Applied at Docker build time. All are idempotent and non-breaking:

| Patch | Default | What it does |
|-------|---------|-------------|
| `fix_artifacts_auto_show` | Active | Auto-opens preview panel for generated files |
| `fix_preview_url_detection` | Active | Detects file URLs and opens iframe preview |
| `fix_tool_loop_errors` | Active | Better error messages for tool call budget/transport errors |
| `fix_large_tool_args` | Optional | Truncates huge tool args to prevent browser freeze |
| `fix_attached_files_position` | Optional | Moves file context to end of message (better prompt caching) |
| `fix_skip_embedding_chat_files` | Optional | Skips embedding for large uploads (>1MB) |
| `fix_skip_rag_files_native_fc` | Optional | Skips RAG when Computer Use tool handles files directly |

Tested with Open WebUI v0.8.11–0.8.12.
