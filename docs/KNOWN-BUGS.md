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

**Severity:** Medium (by design for single-user, needs fix for multi-user)

**Issue:** Endpoints like `/files/{chat_id}/`, `/api/outputs/{chat_id}`, `/browser/{chat_id}/`, `/terminal/{chat_id}/` are accessible to anyone who knows the chat ID UUID. There is no per-user authentication — only `MCP_API_KEY` protects the MCP endpoint itself.

**Impact:** In a multi-user deployment without network isolation, one user could access another user's files if they know the chat ID.

**Current mitigation:** Chat IDs are UUIDs (hard to guess). For single-user or trusted-network deployments this is acceptable.

**Planned fix:** Per-session signed tokens for all file/preview/terminal endpoints. See Security Roadmap in README.
