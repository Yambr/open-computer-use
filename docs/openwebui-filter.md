# Open WebUI Computer Use Filter

## Purpose

The Computer Use Filter (`openwebui/functions/computer_link_filter.py`) is the only integration point between Open WebUI and the Computer Use Server. Its `inlet()` fetches the server-baked system prompt over HTTP and injects it into the conversation when the `ai_computer_use` tool is active. Its `outlet()` decorates assistant messages that contain sandbox file URLs with a preview iframe artifact, an opt-in preview link, and an archive-download link — giving stock Open WebUI deployments full access to the sandbox preview SPA without any frontend patches.

The filter is the single source of truth for the client-side URL shape; the server owns prompt content and preview rendering. Read the file itself for the authoritative Valve defaults and behaviour.

## Installation

- Open WebUI → **Admin Panel** → **Functions** → **New Function**.
- Paste the entire contents of `openwebui/functions/computer_link_filter.py` into the editor.
- Save, then toggle the function on for the target model(s).
- Optionally override any Valve from the function's settings panel. Defaults are chosen so a fresh deployment works end-to-end as soon as the Computer Use Server is reachable at `http://localhost:8081`.
- Upstream reference: [Open WebUI Functions documentation](https://docs.openwebui.com/features/plugin/functions/).

## Preview panel isn't showing — two ways to fix it

![File preview panel when working](screenshots/02-file-preview.png)

When the AI generates a file, the preview panel shown above should open on the right. If nothing opens, here's why — and two ways to fix it.

### How the preview gets rendered

The filter's `outlet()` appends a fenced ```html block containing an `<iframe src="{PUBLIC_BASE_URL}/preview/{chat_id}">` to every assistant message that references a sandbox file. The URL comes from the server's `PUBLIC_BASE_URL` env var — delivered to the filter via the `X-Public-Base-URL` response header on `/system-prompt` and cached alongside the prompt, so the filter never needs its own copy of the public URL. Open WebUI's **artifacts** feature is what turns that block into the side panel. *Stock* Open WebUI renders the artifact only when you click it — it does not auto-open. Our `docker-compose.webui.yml` build ships a patch (`fix_artifacts_auto_show`) that makes it auto-open; stock builds don't have that patch.

So if you run your own Open WebUI image, you have two options.

### Path A — Add a "preview" button (zero-setup, works on stock Open WebUI)

In Open WebUI → Admin Panel → Functions → `computer_link_filter` → Valves, set `PREVIEW_MODE=button` (or `both` to keep the iframe too). Every message with a generated file now gets a `🖥️ Open preview` markdown link that opens the preview SPA in a new tab. One click, no patches, no rebuild. See [Valves reference](#valves-reference).

### Path B — Apply our patches to Open WebUI (auto-opening side panel)

If you want the artifact to pop open automatically like in the screenshot above, use our patched Open WebUI build:

- **Easiest:** use `docker-compose.webui.yml` from the repo root. It builds Open WebUI with `fix_artifacts_auto_show` and `fix_preview_url_detection` pre-applied.
- **Custom image:** if you maintain your own Open WebUI image, copy the two patch scripts (`openwebui/patches/fix_artifacts_auto_show.py` and `openwebui/patches/fix_preview_url_detection.py`) and run them against `/app/build/_app/immutable/chunks/*.js` at build time — see [`openwebui/Dockerfile`](../openwebui/Dockerfile) lines 10–18 for the exact invocation. Both patches are idempotent and tested against Open WebUI v0.8.11–0.8.12.

### Also check: `PUBLIC_BASE_URL` must be reachable from the user's browser

The iframe/button `src` comes from the server's `PUBLIC_BASE_URL` env var. It must be a hostname the user's browser can resolve — not Docker DNS. Set it in `.env` (`PUBLIC_BASE_URL=https://cu.example.com` for prod, `http://localhost:8081` for local dev). Connection-refused symptoms after that? See [Troubleshooting → connection refused](#preview-shows-connection-refused-or-a-blank-frame).

<a id="two-file_server_url-settings--they-must-match"></a>
### Two URL-roles — public (server env) and internal (filter+tool Valve)

**v4.0.0:** the "two `FILE_SERVER_URL`" problem is gone. There is now **one public URL**, owned by the server. The filter doesn't carry it any more — it's delivered in the `X-Public-Base-URL` response header on `/system-prompt` and cached alongside the prompt. Operator only has one knob for the public URL now.

| Role | Where | Default | Notes |
|------|-------|---------|-------|
| **Public URL** — baked into /system-prompt, returned to filter in header, model writes it in links | `computer-use-server` env `PUBLIC_BASE_URL` (set in `.env`) | `http://computer-use-server:8081` (internal; *must* be overridden for anything beyond compose-local dev) | Single source of truth. The filter reads it from the response header; no filter Valve for it. |
| **Internal URL** — server→server fetch from inside the open-webui container | Filter Valve `ORCHESTRATOR_URL` and Tool Valve `ORCHESTRATOR_URL` (both seeded by `init.sh`) | `http://computer-use-server:8081` (Docker service DNS) | Only reachable inside the compose network. Browsers never see it. `init.sh` seeds both Valves from the `ORCHESTRATOR_URL` env on the open-webui container. |
| **Build-arg `COMPUTER_USE_SERVER_URL`** — compiled into a regex inside minified Svelte chunks by `openwebui/patches/fix_preview_url_detection.py`. | `docker-compose.webui.yml` → `services.open-webui.build.args` | `localhost:${MCP_PORT:-8081}` | Public URL, **no scheme** — the regex wraps it. Must match what `PUBLIC_BASE_URL` emits into file links. |

**Custom project/network layouts.** The stock `docker-compose.yml` pins `container_name: computer-use-server`, so `docker compose -p myproject up` by itself does not rename the container — the internal hostname stays `computer-use-server`. If you remove/change that pin, set `ORCHESTRATOR_URL` on the open-webui container to the new hostname and `init.sh` will seed both Valves correctly.

For the full embedding checklist see [README.md → Required setup when embedding Open WebUI](../README.md#required-setup-when-embedding-open-webui-into-your-own-stack).

## Valves reference

| Name | Type | Default | Purpose |
|------|------|---------|---------|
| `ORCHESTRATOR_URL` | str | `"http://computer-use-server:8081"` | **Internal** URL of the Computer Use server. Used for server→server fetch of `/system-prompt` from inside the open-webui container. Never appears in browser-facing URLs — the public URL comes from the server's `PUBLIC_BASE_URL` env var via the `X-Public-Base-URL` response header. Trailing slash tolerated. Non-http(s) schemes are rejected. |
| `INJECT_SYSTEM_PROMPT` | bool | `True` | If `False`, `inlet()` skips system-prompt injection entirely — useful when another filter owns the prompt. |
| `PREVIEW_MODE` | Literal `"artifact" \| "button" \| "both" \| "off"` | `"artifact"` | Where the preview link appears on assistant messages. `artifact` = inline iframe (requires artifact-rendering Open WebUI, see Path B). `button` = markdown link (works on stock Open WebUI, see Path A). `both` = both. `off` = neither. |
| `ARCHIVE_BUTTON` | Literal `"on" \| "off"` | `"on"` | Append `[{ARCHIVE_BUTTON_TEXT}]({base}/files/{chat_id}/archive)` to assistant messages that contain files for the current chat. |
| `PREVIEW_BUTTON_TEXT` | str | `"🖥️ Open preview"` | Label for the preview-button markdown link (used when `PREVIEW_MODE` is `button` or `both`). |
| `ARCHIVE_BUTTON_TEXT` | str | `"📦 Download all files as archive"` | Label for the archive-download link (used when `ARCHIVE_BUTTON` is `on`). |

## Preview UX: which `PREVIEW_MODE` fits you?

- **`PREVIEW_MODE="artifact"`** (default). Every assistant message containing a sandbox file URL is decorated with a fenced ```html block wrapping an `<iframe>` whose `src` points at `/preview/{chat_id}`. Deployments that render fenced html as artifacts show the Computer Use preview SPA inline, no click required. Our `docker-compose.webui.yml` build ships the `fix_artifacts_auto_show` patch — pair with this mode.
- **`PREVIEW_MODE="button"`**. The same trigger appends `[🖥️ Open preview](…)` instead — opens the preview SPA in a new tab, one click, but works on stock Open WebUI without artifact support.
- **`PREVIEW_MODE="both"`**. Both decorations. Useful while comparing rendering behaviour across deployments or during migrations.
- **`PREVIEW_MODE="off"`**. Neither. Combine with `ARCHIVE_BUTTON="off"` to make `outlet()` a no-op.

Rule of thumb:

- UI renders html artifacts → keep the default (`PREVIEW_MODE="artifact"`).
- Stock Open WebUI → `PREVIEW_MODE="button"`.
- During evaluation → `PREVIEW_MODE="both"`.

## Archive button

`ARCHIVE_BUTTON="on"` (default) preserves the v3.0.x behaviour: when an assistant message contains at least one file URL under `{PUBLIC_BASE_URL}/files/{chat_id}/…`, `outlet()` appends a markdown link to the archive endpoint `/files/{chat_id}/archive`. The endpoint streams a zip of every file the sandbox has written for the chat. The append is idempotent (substring check against the fully-rendered URL) — safe to re-run `outlet()` on the same body as many times as the framework chooses.

## System prompt injection

`INJECT_SYSTEM_PROMPT` (default `True`) controls the `inlet()` path. When the `ai_computer_use` tool is active and `chat_id` is present, the filter HTTP-fetches the baked prompt from `{ORCHESTRATOR_URL}/system-prompt` and injects it into the system message, with a 5-minute LRU cache and a stale-cache fallback on transport failure. The response's `X-Public-Base-URL` header is cached alongside the prompt so `outlet()` can build correct browser-facing links without its own Valve. Non-http(s) schemes on `ORCHESTRATOR_URL` are rejected to avoid `file://` / `ftp://` information-disclosure paths. See `docs/system-prompt.md` for the server-side contract, including how `user_email` drives the `<available_skills>` block.

## Troubleshooting

### Preview shows "connection refused" or a blank frame

- Check that `PUBLIC_BASE_URL` (server `.env`) is reachable *from the user's browser* — the filter has no Valve for the public URL any more; everything flows from the server env.
- Confirm the Computer Use Server is running: `docker compose ps` should list the `computer-use-server` container as healthy.
- Copy the `src=` value out of the iframe and `curl` it directly — the SPA HTML should come back with HTTP 200.

### Button/iframe never appears

- The assistant message must contain at least one URL matching `{PUBLIC_BASE_URL}/files/{chat_id}/…`. No file URL, no decoration.
- `chat_id` must reach `outlet()` via `__metadata__`. Restart Open WebUI after toggling Valves if the model didn't re-init.
- `PREVIEW_MODE` must be `"artifact"`, `"button"`, or `"both"`, OR `ARCHIVE_BUTTON` must be `"on"`. When `PREVIEW_MODE="off"` AND `ARCHIVE_BUTTON="off"`, `outlet()` returns the body unchanged.

### "Non-http scheme" error in logs

Caused by setting `ORCHESTRATOR_URL` to a `file://`, `ftp://`, or similarly non-http(s) URL. The filter rejects it and serves the stale cache if available, otherwise skips injection. Fix by pointing the Valve at an `http://` or `https://` endpoint.

## Version history

- **v4.0.0** — Breaking: removed `FILE_SERVER_URL` and `SYSTEM_PROMPT_URL` Valves, replaced with a single `ORCHESTRATOR_URL` Valve (internal URL). The public URL is now owned by the server (`PUBLIC_BASE_URL` env) and delivered to the filter via the `X-Public-Base-URL` response header on `/system-prompt`. `_fetch_system_prompt()` now returns `(public_url, prompt)`; `outlet()` reads `public_url` from the cache instead of its own Valve. Tool's `FILE_SERVER_URL` Valve was renamed to `ORCHESTRATOR_URL` for consistency. `init.sh` re-seeds the new Valve names.
- **v3.4.0** — Removed the three legacy v3.2.0 boolean Valves (`ENABLE_PREVIEW_ARTIFACT`, `ENABLE_PREVIEW_BUTTON`, `ENABLE_ARCHIVE_BUTTON`) and their migration bridge. `PREVIEW_MODE` and `ARCHIVE_BUTTON` are the only knobs. Users upgrading straight from v3.2.0 revert to defaults — upgrade via v3.3.0 first if you need to preserve saved preferences.
- **v3.3.0** — Collapsed three boolean preview/archive Valves (`ENABLE_PREVIEW_ARTIFACT`, `ENABLE_PREVIEW_BUTTON`, `ENABLE_ARCHIVE_BUTTON`) into two Literal Valves (`PREVIEW_MODE`, `ARCHIVE_BUTTON`). Existing v3.2.0 deployments were migrated transparently by a Pydantic `@model_validator(mode="after")`. `outlet()` behaviour and all v3.1.0/v3.2.0 invariants preserved.
- **v3.2.0** — Added `ENABLE_PREVIEW_ARTIFACT` (default `True`), `ENABLE_PREVIEW_BUTTON` (default `False`), and `PREVIEW_BUTTON_TEXT` Valves. `outlet()` now emits an inline iframe artifact and/or a markdown preview link alongside the archive button. All v3.1.0 invariants preserved.
- **v3.1.0** — Removed the hardcoded ~460-line system prompt f-string; server became the single source of truth. HTTP fetch + LRU cache + stale-cache fallback. `SYSTEM_PROMPT_URL` Valve added (removed in v4.0.0); non-http(s) schemes rejected.
- **v3.0.2** — Last hardcoded-prompt revision. See git history for details.

For deeper context, consult the CHANGELOG blocks in the module docstring of `openwebui/functions/computer_link_filter.py` and the per-commit history on `main`.
