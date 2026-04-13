# Known Bugs

## 1. MCP Server: TypeError 'NoneType' on SSE notifications

**Severity:** Low (doesn't break functionality — tool calls return 200 OK)

**Error:**
```
starlette/routing.py, line 74, in app
    await response(scope, receive, send)
TypeError: 'NoneType' object is not callable
```

**When:** Every `POST /mcp` that returns 202 Accepted (SSE notification acknowledgment).

**Root cause:** MCP Python SDK's Streamable HTTP handler returns `None` for fire-and-forget notification responses. Starlette expects an ASGI callable Response object.

**Impact:** Error logged but tool calls work. The 202 response is already sent before the error.

**Likely fix:** Check if `mcp` SDK version has a fix, or patch the route handler to return an empty Response for 202.

---

## 2. File preview auto-show depends on model behavior

**Severity:** Medium (functional but not always automatic)

**How it works:** The `fix_preview_url_detection` patch detects Computer Use Server file URLs in assistant messages and auto-opens an iframe preview in the artifacts panel. The `computer_link_filter` injects the file server URL into the system prompt so the model knows to include file links.

**Issue:** Some models (especially smaller ones) don't consistently include file URLs in their responses even when instructed by the system prompt. When the model just says "file created" without the URL, the preview patch has nothing to detect.

**Workaround:** The filter's outlet always adds "View your file" link and "Download all as archive" button — these work regardless. For auto-preview, use models that reliably follow system prompt instructions (Claude, GPT-4o, larger Qwen models).

---

## 3. PPTX generation may timeout with complex prompts

**Severity:** Low (model-dependent)

**When:** Model makes many sequential tool calls (19+ bash, create_file, view, str_replace) for complex tasks like presentation creation.

**Impact:** Response may appear incomplete if model hits max tool call retries.

**Workaround:** Use simpler prompts or increase `COMMAND_TIMEOUT` in `.env`.

---

## 4. File/preview endpoints have no per-user auth

**Severity:** Medium (known limitation, planned fix)

**Issue:** Endpoints like `/files/{chat_id}/`, `/api/outputs/{chat_id}`, `/browser/{chat_id}/`, `/terminal/{chat_id}/` are accessible to anyone who knows the chat ID UUID. There is no per-user authentication — only `MCP_API_KEY` protects the MCP endpoint itself.

**Impact:** In a multi-user deployment without network isolation, one user could access another user's files if they know the chat ID.

**Current mitigation:** Chat IDs are UUIDs (hard to guess). Tested in production with 1000+ users on Open WebUI — acceptable risk for self-hosted deployments behind a firewall.

**Planned fix:** Per-session signed tokens for all file/preview/terminal endpoints. See Security Roadmap in README.

---

## 5. MCP tools cannot return images to the model (Open WebUI limitation)

**Severity:** Medium (functional limitation)

**Issue:** Open WebUI does not support `image` content type in MCP tool results — only `text` is handled. This means tools cannot return screenshots or images back to the model for analysis.

**Impact:** Tools like Playwright (page screenshots) or bash (generated charts) cannot pass visual output directly to the model. The model never sees the image, so it can't reason about what's on screen.

**Workaround:** The `describe-image` skill works around this by calling a separate vision model (e.g., GPT-4o, Qwen-VL) to describe the image as text, which is then returned to the main model. Playwright and other skills save images to `/mnt/user-data/outputs/` as HTTP links for the user to view in the file preview panel.

**Root cause:** Open WebUI's MCP integration only passes `text` content blocks from tool responses to the model. This is an upstream limitation — see [open-webui/open-webui](https://github.com/open-webui/open-webui) for progress on image tool result support.

---

## 6. Preview breaks after `docker compose -p <project>` or custom `container_name`

**Severity:** Medium (configuration-only, no data loss)

**How it works:** The Computer Use Server embeds file links into every assistant message using its `FILE_SERVER_URL` env var (default `http://computer-use-server:8081`). The Open WebUI filter has an *identically named* `FILE_SERVER_URL` Valve that it uses to build a regex for detecting those same URLs and appending the preview iframe + archive button. For preview to render, the two values must match.

**Issue:** When you run with `docker compose -p myproject up` or set a custom `container_name:` on the `computer-use-server` service, the default `http://computer-use-server:8081` host stops resolving — inside the Docker network the container is now `myproject-computer-use-server:8081` or similar. The server keeps emitting the old default into link text (its env var is unchanged), but:

1. The browser can't open those links regardless of what the filter Valve says.
2. The filter's regex pattern is built from its Valve, so if you set the Valve to the new external URL, it no longer matches the stale text the server emits — and `outlet()` silently skips decoration, meaning no preview at all. No error is logged.

Same failure mode is possible in any deployment where the operator changes only one of the two settings.

**Workaround:** Set the `FILE_SERVER_URL` env var for the `computer-use-server` service to your externally reachable URL, and set the Open WebUI filter Valve to the same value. `.env.example` now documents this; uncomment the `FILE_SERVER_URL=` line and point it at a URL the user's browser can reach. See [docs/openwebui-filter.md §Two FILE_SERVER_URL settings](openwebui-filter.md#two-file_server_url-settings--they-must-match) for the full explanation.

**Planned fix:** Rename the filter Valve to remove the name collision (e.g., `PUBLIC_FILE_URL`) and emit a warning when the two settings disagree. Tracked as a follow-up; not scheduled.
