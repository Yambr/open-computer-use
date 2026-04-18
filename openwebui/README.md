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

**Automatic** (recommended): `docker-compose.webui.yml` builds a patched Open WebUI image and runs `init.sh` on first startup to install the tool + filter, configure valves, mark the **tool public-read** (`group:*` + `user:*` grants) and the **filter both active AND global** (two separate Open WebUI toggles), plus set `DEFAULT_MODEL_PARAMS = {function_calling: "native", stream_response: true}`.

**Manual**: Install tool and filter through Workspace UI, set Tool ID to `ai_computer_use`, toggle **Active** and **Global** on the filter (both switches), set tool access to **Public** (Share → Public). See [setup guide](../README.md#required-setup-when-embedding-open-webui-into-your-own-stack) for the full checklist and common silent-fail traps.

## Patches

Applied at Docker build time. All are idempotent and non-breaking. The 4 patches marked **Active** below are critical for user-visible UX — embedding Open WebUI with an upstream `ghcr.io/open-webui/open-webui` image (no build from this Dockerfile) silently disables them. See [../README.md#required-setup-when-embedding-open-webui-into-your-own-stack](../README.md#required-setup-when-embedding-open-webui-into-your-own-stack) for the full embedding checklist.

| Patch | Default | What it does | Without it |
|-------|---------|--------------|------------|
| `fix_artifacts_auto_show` | Active | Auto-opens preview panel for generated files | HTML/iframe renders as raw text in the chat body instead of the artifacts panel |
| `fix_preview_url_detection` | Active | Detects file URLs in messages and opens iframe preview | Preview iframe is never auto-inserted after file links |
| `fix_tool_loop_errors` | Active | Better error messages for tool call budget/transport errors | Raw exceptions instead of banners; `MCP call failed: Session terminated` appears unwrapped |
| `fix_large_tool_results` | Active | Truncates large MCP tool results (>50K chars) and optionally uploads them to the Computer Use server | `TOOL_RESULT_MAX_CHARS` / `DOCKER_AI_UPLOAD_URL` become no-ops; large outputs wreck the model context |
| `fix_large_tool_args` | Optional | Truncates huge tool call args (>10KB) to prevent browser freeze | Browser UI can freeze on "Executing [tool]..." with large str_replace payloads |
| `fix_attached_files_position` | Optional | Moves file context to end of message (better prompt caching) | Attaching a file invalidates the cached prefix of the message |
| `fix_skip_embedding_chat_files` | Optional | Skips embedding for large uploads (>1MB) | Large uploads block the chat for minutes on extraction/embedding |
| `fix_skip_rag_files_native_fc` | Optional | Skips RAG when `ai_computer_use` handles files directly | Extra RAG pipeline runs on every message even when unnecessary |

Tested with Open WebUI v0.8.11–0.8.12.
