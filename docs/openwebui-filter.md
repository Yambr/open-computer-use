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

The filter's `outlet()` appends a fenced ```html block containing an `<iframe src="{FILE_SERVER_URL}/preview/{chat_id}">` to every assistant message that references a sandbox file. Open WebUI's **artifacts** feature is what turns that block into the side panel. *Stock* Open WebUI renders the artifact only when you click it — it does not auto-open. Our `docker-compose.webui.yml` build ships a patch (`fix_artifacts_auto_show`) that makes it auto-open; stock builds don't have that patch.

So if you run your own Open WebUI image, you have two options.

### Path A — Add a "preview" button (zero-setup, works on stock Open WebUI)

In Open WebUI → Admin Panel → Functions → `computer_link_filter` → Valves, set `PREVIEW_MODE=button` (or `both` to keep the iframe too). Every message with a generated file now gets a `🖥️ Open preview` markdown link that opens the preview SPA in a new tab. One click, no patches, no rebuild. See [Valves reference](#valves-reference).

### Path B — Apply our patches to Open WebUI (auto-opening side panel)

If you want the artifact to pop open automatically like in the screenshot above, use our patched Open WebUI build:

- **Easiest:** use `docker-compose.webui.yml` from the repo root. It builds Open WebUI with `fix_artifacts_auto_show` and `fix_preview_url_detection` pre-applied.
- **Custom image:** if you maintain your own Open WebUI image, copy the two patch scripts (`openwebui/patches/fix_artifacts_auto_show.py` and `openwebui/patches/fix_preview_url_detection.py`) and run them against `/app/build/_app/immutable/chunks/*.js` at build time — see [`openwebui/Dockerfile`](../openwebui/Dockerfile) lines 10–18 for the exact invocation. Both patches are idempotent and tested against Open WebUI v0.8.11–0.8.12.

### Also check: `FILE_SERVER_URL` must be reachable from the user's browser

Even with Path A or Path B, the iframe/button still needs a hostname the browser can resolve. Open WebUI-in-Docker can reach the server via `host.docker.internal`, but the browser needs a routable hostname (e.g. `http://your-host.lan:8081` or a reverse-proxied URL). Set this in the filter's `FILE_SERVER_URL` Valve. Connection-refused symptoms after that? See [Troubleshooting → connection refused](#preview-shows-connection-refused-or-a-blank-frame). And make sure the *server-side* `FILE_SERVER_URL` matches — the next subsection explains why.

### Two `FILE_SERVER_URL` settings — they must match

There are two settings named `FILE_SERVER_URL` in this project. Both must be set to the same value. If they disagree, `outlet()` finds no URL matching its pattern, skips decoration silently — no error, no log line — and the preview panel never appears even though everything else "looks fine".

| Setting | Set at | Default | What it does |
|---|---|---|---|
| **`computer-use-server` container env var** | `docker-compose.yml` (now exposed as `${FILE_SERVER_URL}`, see [source](../computer-use-server/docker_manager.py#L44)) | `http://computer-use-server:8081` | The URL *text* that the server embeds into every file link it emits — in assistant messages and in the sub-agent system prompt. |
| **Filter Valve `FILE_SERVER_URL`** | Open WebUI → Admin Panel → Functions → `computer_link_filter` → Valves. Auto-set by `openwebui/init.sh` when you use the patched compose. | `http://localhost:8081` | The base URL from which `outlet()` builds the regex (`re.escape(base) + "/files/" + chat_id + ...`). A match triggers the preview iframe, archive button, and optional preview button; a miss means nothing is appended. |

**How it fails silently.** Suppose the container still uses the built-in default and you only change the filter Valve to `http://myhost:8081`:

1. Server emits `http://computer-use-server:8081/files/<chat_id>/file.txt` into the message.
2. Filter builds pattern `http://myhost:8081/files/<chat_id>/...`.
3. Pattern does not match → `outlet()` returns the body unchanged.
4. User sees the bare link (which their browser cannot reach) and no preview panel. No error.

**How to set it.** Uncomment `FILE_SERVER_URL=` in `.env` and set it to the externally reachable URL. Restart the `computer-use-server` container. Then set the filter Valve to the **same** value in Open WebUI. That's it.

**Custom project/network layouts.** The stock `docker-compose.yml` pins `container_name: computer-use-server`, so `docker compose -p myproject up` **by itself** does not rename the container — the internal hostname stays `computer-use-server`. But if you remove or change that `container_name:` pin (for example to run two stacks side by side) and/or use `-p`, the internal hostname becomes the Compose-generated one (e.g. `myproject-computer-use-server-1`) and the default `http://computer-use-server:8081` no longer resolves anywhere. In that case — and for any deployment where the browser can't reach the internal hostname — set `FILE_SERVER_URL` to the externally reachable URL and keep the server env var and the filter Valve identical. Scenario reproduced in [docs/KNOWN-BUGS.md #6](KNOWN-BUGS.md#6-preview-breaks-after-custom-container_name-or-non-default-compose-layouts).

### Actually there are four — tool Valve and build-arg

The section above covers the **text-matching** pair: server emits a URL, filter matches that text. Two more settings point at the same Computer Use Server from **different network roles**, and the rules are opposite — three want the public URL, one wants the internal Docker DNS name.

| Where | Role | Right value (prod) | Right value (local dev) |
|-------|------|--------------------|-------------------------|
| `computer-use-server` env `FILE_SERVER_URL` (above) | Public URL — baked into system prompt so the model writes clickable links | `https://cu.your-domain.com` | `http://localhost:8081` |
| Filter Valve `FILE_SERVER_URL` (above) | Public URL — regex match in browser-bound messages | `https://cu.your-domain.com` | `http://localhost:8081` |
| Build-arg `COMPUTER_USE_SERVER_URL` (docker-compose `build.args` for `open-webui` service) | Public URL — compiled into a regex inside minified Svelte chunks by `openwebui/patches/fix_preview_url_detection.py`. Must match what the model emits, which comes from the first row. | `cu.your-domain.com` (no scheme — the regex wraps it) | `localhost:8081` |
| Tool Valve `FILE_SERVER_URL` (Workspace → Tools → `ai_computer_use` → Valves) | Internal Docker DNS — HTTP client forwarding MCP `tools/call` to the server; staying inside the Docker network avoids Cloudflare/Traefik/TLS hops that kill MCP streams (symptom: `MCP call failed: Session terminated`). | `http://computer-use-server:8081` | `http://host.docker.internal:8081` |

For the full step-by-step embedding checklist — image build, build-arg, Valves, env vars — see [README.md → Required setup when embedding Open WebUI](../README.md#required-setup-when-embedding-open-webui-into-your-own-stack).

## Valves reference

| Name | Type | Default | Purpose |
|------|------|---------|---------|
| `FILE_SERVER_URL` | str | `"http://localhost:8081"` | Orchestrator base URL. Derives `/system-prompt`, `/files/{chat_id}/…`, `/files/{chat_id}/archive`, and `/preview/{chat_id}`. Trailing slash is tolerated (stripped internally). Must match the server-side `FILE_SERVER_URL` env var — see [Two `FILE_SERVER_URL` settings](#two-file_server_url-settings--they-must-match). |
| `SYSTEM_PROMPT_URL` | str | `""` | Advanced: override URL for the `/system-prompt` endpoint. Empty means derive from `FILE_SERVER_URL`. Non-http(s) schemes are rejected. |
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

`ARCHIVE_BUTTON="on"` (default) preserves the v3.0.x behaviour: when an assistant message contains at least one file URL under `{FILE_SERVER_URL}/files/{chat_id}/…`, `outlet()` appends a markdown link to the archive endpoint `/files/{chat_id}/archive`. The endpoint streams a zip of every file the sandbox has written for the chat. The append is idempotent (substring check against the fully-rendered URL) — safe to re-run `outlet()` on the same body as many times as the framework chooses.

## System prompt injection

`INJECT_SYSTEM_PROMPT` (default `True`) and `SYSTEM_PROMPT_URL` (default empty) control the `inlet()` path. When the `ai_computer_use` tool is active and `chat_id` is present, the filter HTTP-fetches the baked prompt from the server and injects it into the system message, with a 5-minute LRU cache and a stale-cache fallback on transport failure. Non-http(s) schemes are rejected to avoid `file://` / `ftp://` information-disclosure paths. See `docs/system-prompt.md` for the server-side contract, including how `user_email` drives the `<available_skills>` block.

## Troubleshooting

### Preview shows "connection refused" or a blank frame

- Check that `FILE_SERVER_URL` is reachable *from the user's browser* — Open WebUI may reach the server via `host.docker.internal` while the browser needs a routable hostname.
- Confirm the Computer Use Server is running: `docker compose ps` should list the `computer-use-server` container as healthy.
- Copy the `src=` value out of the iframe and `curl` it directly — the SPA HTML should come back with HTTP 200.

### Button/iframe never appears

- The assistant message must contain at least one URL matching `{FILE_SERVER_URL}/files/{chat_id}/…`. No file URL, no decoration.
- `chat_id` must reach `outlet()` via `__metadata__`. Restart Open WebUI after toggling Valves if the model didn't re-init.
- `PREVIEW_MODE` must be `"artifact"`, `"button"`, or `"both"`, OR `ARCHIVE_BUTTON` must be `"on"`. When `PREVIEW_MODE="off"` AND `ARCHIVE_BUTTON="off"`, `outlet()` returns the body unchanged.

### "Non-http scheme" error in logs

Caused by setting `SYSTEM_PROMPT_URL` to a `file://`, `ftp://`, or similarly non-http(s) URL. The filter rejects it and serves the stale cache if available, otherwise skips injection. Fix by pointing the Valve at an `http://` or `https://` endpoint, or leave it empty so it derives from `FILE_SERVER_URL`.

## Version history

- **v3.4.0** — Removed the three legacy v3.2.0 boolean Valves (`ENABLE_PREVIEW_ARTIFACT`, `ENABLE_PREVIEW_BUTTON`, `ENABLE_ARCHIVE_BUTTON`) and their migration bridge. `PREVIEW_MODE` and `ARCHIVE_BUTTON` are the only knobs. Users upgrading straight from v3.2.0 revert to defaults — upgrade via v3.3.0 first if you need to preserve saved preferences.
- **v3.3.0** — Collapsed three boolean preview/archive Valves (`ENABLE_PREVIEW_ARTIFACT`, `ENABLE_PREVIEW_BUTTON`, `ENABLE_ARCHIVE_BUTTON`) into two Literal Valves (`PREVIEW_MODE`, `ARCHIVE_BUTTON`). Existing v3.2.0 deployments were migrated transparently by a Pydantic `@model_validator(mode="after")`. `outlet()` behaviour and all v3.1.0/v3.2.0 invariants preserved.
- **v3.2.0** — Added `ENABLE_PREVIEW_ARTIFACT` (default `True`), `ENABLE_PREVIEW_BUTTON` (default `False`), and `PREVIEW_BUTTON_TEXT` Valves. `outlet()` now emits an inline iframe artifact and/or a markdown preview link alongside the archive button. All v3.1.0 invariants preserved.
- **v3.1.0** — Removed the hardcoded ~460-line system prompt f-string; server became the single source of truth. HTTP fetch + LRU cache + stale-cache fallback. `SYSTEM_PROMPT_URL` Valve added; non-http(s) schemes rejected.
- **v3.0.2** — Last hardcoded-prompt revision. See git history for details.

For deeper context, consult the CHANGELOG blocks in the module docstring of `openwebui/functions/computer_link_filter.py` and the per-commit history on `main`.
