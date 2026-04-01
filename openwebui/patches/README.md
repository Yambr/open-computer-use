# Open WebUI Patches

Patches for Open WebUI to improve Computer Use integration.

## Active Patch

### fix_artifacts_auto_show.py
Auto-opens the artifacts panel when HTML code blocks are detected in assistant messages. Without this patch, users must manually click to see generated HTML/file previews.

## Optional Patches

These are included but commented out in `openwebui/Dockerfile`. Uncomment to enable.

### fix_large_tool_results.py
Truncates large MCP tool results (>50K chars by default) to prevent context window exhaustion. When tools like Metabase, OpenSearch, or Playwright return huge outputs, this patch truncates them in-place with a preview, protecting both the LLM context and DB storage. Optionally uploads full results to the Computer Use server for later retrieval.

**Config env vars:**
- `TOOL_RESULT_MAX_CHARS` (default: 50000) — truncation threshold. Set to 0 to disable.
- `TOOL_RESULT_PREVIEW_CHARS` (default: 2000) — preview size shown to model.
- `DOCKER_AI_UPLOAD_URL` (optional) — base URL for uploading full results.

**Requires:** `fix_tool_loop_errors.py` must be applied first.

### fix_large_tool_args.py
Truncates oversized tool call arguments (>10KB) in HTML attributes and base64-encodes the full content. Prevents browser UI freeze when tools return large outputs.

### fix_attached_files_position.py
Moves file context to the end of messages instead of prepending. Improves prompt cache hit rates when working with large file attachments.

### fix_skip_embedding_chat_files.py
Skips expensive text extraction and embedding for large chat file uploads (>1MB). Falls back to knowledge base upload instead of blocking the chat.

### fix_skip_rag_files_native_fc.py
Skips the RAG pipeline for chat files when the `ai_computer_use` tool is enabled. The tool handles files directly via the MCP server, so RAG processing is unnecessary overhead.

## How Patches Work

Each patch:
1. Searches for specific patterns in Open WebUI's compiled frontend/backend code
2. Applies targeted modifications (idempotent — safe to run multiple times)
3. Uses a `PATCH_MARKER` to detect if already applied
4. Exits with code 0 even on failure (non-critical)

Patches are applied during `docker compose build` when building the Open WebUI image.
