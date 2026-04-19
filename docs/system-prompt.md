# System Prompt Delivery — Six MCP-Native Tiers

The Computer Use Server delivers the same per-session system prompt through **six different channels**, so clients with varying MCP support all get it. Every tier renders from the same source (`computer-use-server/system_prompt.py::render_system_prompt`) with a shared 60-second in-process cache, so fan-out cost is one render per `(chat_id, user_email)` per minute.

**Redundancy is by design.** A client might strip `InitializeResult.instructions` and never call `resources/list` — but it will always call `tools/list`, and the tool descriptions nudge the model toward `/home/assistant/README.md` inside the sandbox. That file is always present.

**Why not `@mcp.prompt("system")`?** MCP `prompts/*` is user-controlled (slash-commands the user explicitly picks) and `PromptMessage.role` is restricted to `{user, assistant}` — naming a prompt `"system"` both clashes with the spec's role model and duplicates `InitializeResult.instructions`, which is the canonical field for "how the server wants itself used." We chose the canonical path.

## The Tiers

| # | Surface | Where it lives | Who uses it |
|---|---|---|---|
| 1 | Tool descriptions | `tools/list` — `bash_tool` + `view` docstrings mention README.md | Every MCP client (tools are mandatory) |
| 2 | `/home/assistant/README.md` | Rendered into the sandbox on container creation via `put_archive` | Any model that runs the `view` tool |
| 3 | Static `instructions=` hint | FastMCP constructor, one-line pointer to README + `resources/list` | Claude Desktop, MCP Inspector; Agents SDK exposes via `server.server_initialize_result` |
| 4 | Dynamic `InitializeResult.instructions` | Per-request ContextVar, swapped onto `mcp._mcp_server` as a `@property` | Same clients as #3, with chat-specific content |
| 5 | `resources/list` + `resources/read` | Uploaded files surfaced as `FunctionResource` per chat, URI `file://uploads/{chat_id}/{rel_path}` | Agents SDK, Inspector, Claude Desktop |
| 6 | `GET /system-prompt` HTTP | Backward-compat endpoint with header > query priority | Open WebUI filter; external integrations (n8n) |

## Tier 1 — Tool description nudges

Docstrings of `bash_tool` and `view` tools (in `computer-use-server/mcp_tools.py`) end with:

> If you've lost track of your environment (chat_id, file URLs, available skills), re-read /home/assistant/README.md.

Deliberately **not** "read this first" — the system prompt itself (Tiers 3/4) already identifies as "contents of /home/assistant/README.md", so if the client surfaced it the model already has the content. This line is a **recovery hint**, not a forcing function.

## Tier 2 — README.md in the sandbox

When `docker_manager._create_container` spins up a chat's workspace container, it calls `render_system_prompt_sync(chat_id, user_email)` and writes the result to `/home/assistant/README.md` (or `/root/README.md` for the test image) via `container.put_archive`. The file survives across container removals because it lives in the chat's persistent workspace volume (`chat-{chat_id}-workspace`).

Does **not** enumerate uploaded files — those are Tier 5's responsibility and are refreshed on every upload. README is static-per-container and changes only when `user_email` changes (which doesn't happen mid-chat).

## Tier 3 — Static `instructions=`

FastMCP's constructor kwarg. A one-liner pointing at Tiers 2 and 5 (README + uploaded-file resources) so a client that renders only `InitializeResult.instructions` still learns where the per-session content lives.

## Tier 4 — Dynamic `InitializeResult.instructions`

The same `instructions` field, but **per-request**. Relies on three facts pinned in the SDK source (`.venv/lib/python3.13/site-packages/mcp/server/...`):

1. `streamable_http_manager._handle_stateless_request:196` calls `self.app.create_initialization_options()` inside a per-request task spun up for each HTTP hit — and we run `stateless_http=True` (`mcp_tools.py:276`).
2. `lowlevel/server.py:188` reads `self.instructions` at that moment to populate `InitializationOptions`.
3. `session.py:183` echoes it into `InitializeResult.instructions`.

Mechanism:
- `MCPContextMiddleware` (runs before every MCP request) pre-renders the prompt via `render_system_prompt(...)` and stores it in `current_instructions: ContextVar[str]`.
- `_DynamicInstructionsServer` subclasses `mcp.server.lowlevel.Server` with `@property def instructions` returning the ContextVar value (falling back to the static `_STATIC_INSTRUCTIONS` string when unset).
- After `FastMCP(...)` constructs the lowlevel server, we **swap the class** on the existing instance: `mcp._mcp_server.__class__ = _DynamicInstructionsServer`. No reconstruction needed.

**Stateful mode would break this** (a long-lived session caches `init_options` at construction). Do NOT flip `stateless_http=False` without re-reading the SDK source above.

**Private-API caveat.** We touch `mcp._mcp_server` and `_resource_manager._resources`. Pin `mcp` narrowly in `computer-use-server/requirements.txt` — an SDK minor bump requires re-verifying these attribute shapes.

## Tier 5 — Uploaded files as MCP resources

`resources/list` returns a `FunctionResource` per uploaded file with URI `file://uploads/{chat_id}/{url-encoded rel_path}`. `resources/read` fetches the content — text for `text/*` and a short MIME allowlist, base64 blob otherwise.

Why `chat_id` embedded in the URI: Agents SDK and Inspector don't re-send `X-Chat-Id` on per-resource calls, so URIs must be self-contained.

Why URL-encoding: FastMCP's `ResourceTemplate.matches` (verified at `.venv/.../templates.py:88`) uses `[^/]+` per template param — it blocks nested paths. Flattening via `urllib.parse.quote` sidesteps the limitation cleanly without forking the SDK.

Dynamic registration: `sync_chat_resources(chat_id)` clears previously-registered entries for that chat, re-adds from the current filesystem state, under an `asyncio.Lock` to avoid "dict changed size during iteration" when a concurrent `resources/list` runs during an upload. Called from:
- `docker_manager._create_container` — initial sync when the container spins up.
- `app.py:upload_file` — after `POST /api/uploads/{chat_id}/{filename}` saves a new file.

Upload itself stays on HTTP — **MCP has no upload primitive.** Community consensus is out-of-band HTTP alongside the MCP server.

## Tier 6 — HTTP `/system-prompt`

Kept for the Open WebUI filter (`openwebui/functions/computer_link_filter.py:224–363`) which fetches the prompt server-side and injects it into the LLM's system message. The endpoint reads:

```
X-Chat-Id | X-OpenWebUI-Chat-Id   > ?chat_id=           > "default"
X-User-Email | X-OpenWebUI-User-Email > ?user_email=   > None
```

Header-priority rule consistent with the rest of the server (MCP middleware reads the same headers and aliases). Response header `X-Public-Base-URL` is still emitted so the filter's `outlet()` can build browser-facing archive/preview URLs from the server-owned `PUBLIC_BASE_URL`.

## Render cache

`render_system_prompt(chat_id, user_email)` is cache-backed with a 60-second TTL (`_RENDER_TTL_SECONDS` in `system_prompt.py`). Matches `skill_manager`'s own memory-cache TTL. Middleware runs the render on **every** MCP request to pre-fill the ContextVar for Tier 4, so the cache is load-bearing — without it, every `tools/call` would re-hit the skills provider. The second request for the same `(chat_id, user_email)` is a dict lookup.

Invalidation: `invalidate_render_cache()` (no arg → clear all; `chat_id` arg → clear that chat). Used in tests; also callable when skills change upstream.

## Known duplication: Open WebUI filter × README

When Open WebUI is the frontend:
- Tier 6 HTTP endpoint gives the filter the prompt, which it injects into the LLM's system message.
- Tier 2 also writes the same text to `/home/assistant/README.md`.
- Tier 4 puts the same text in `InitializeResult.instructions` (which the filter does not currently strip).

The model may see the prompt up to three times (~3–5K tokens per extra copy). Follow-up PR: teach the filter to skip inject when the tool is attached. Out of scope for the "maximum MCP surface" refactor — backward compat is a hard requirement.

## See also

- `docs/MCP.md` — protocol-level MCP server documentation.
- `docs/openwebui-filter.md` — how the filter consumes Tier 6.
- `computer-use-server/system_prompt.py` — the render function + cache.
- `tests/orchestrator/test_{render_cache,dynamic_instructions,mcp_resources,tool_descriptions,readme_in_container,system_prompt_endpoint}.py` — pinning tests for every tier.
