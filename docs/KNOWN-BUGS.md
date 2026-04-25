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

## 6. Preview breaks after custom `container_name` or non-default compose layouts

**Severity:** Medium (configuration-only, no data loss)

**Status (v4.0.0):** the class of "two settings must match" bugs was fixed by moving public-URL ownership to the server. The filter now reads the public URL from the server's `X-Public-Base-URL` response header — there is only one place to set it.

**How it works:** The Computer Use Server embeds file links into every assistant message using its `PUBLIC_BASE_URL` env var. The Open WebUI filter's `outlet()` uses whatever URL the server returned in the response header — no separate public-URL Valve. The filter's internal `ORCHESTRATOR_URL` Valve is a Docker-only hostname and doesn't leave the container.

**What can still go wrong:** the `PUBLIC_BASE_URL` on the `computer-use-server` container must still be a URL the user's browser can reach. Custom compose project names, removed `container_name:` pins, or missing DNS mean the browser sees links pointing at an unreachable hostname — the preview iframe then 404s / shows a blank frame even though the filter decorates it correctly.

**Workaround:** Set `PUBLIC_BASE_URL` (server `.env`) to your externally reachable URL (`http://your-host.lan:8081`, `https://cu.example.com`, …). The `fix_preview_url_detection` patch is host-agnostic — no build-arg required. See [docs/openwebui-filter.md](openwebui-filter.md#two-url-roles--public-server-env-and-internal-filtertool-valve).
