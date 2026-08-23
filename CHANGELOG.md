# Changelog

## Unreleased — `next/v1` branch

### Changed

- **TypeScript 7 removes the JavaScript compiler API from the sandbox image.** The
  image now ships `typescript@7.0.2`, the native compiler. `require('typescript')`
  returns `{version, versionMajorMinor}` only — `createProgram`, `ts.sys` and the
  rest of the API are gone. The `tsc` CLI is unaffected (type-checking and emit
  both verified under 7.0.2, including downlevel to es2019 and `.mts` ESM output),
  and `tsx` is unaffected (it transpiles through esbuild, not the API). What breaks
  is assistant-written code inside the sandbox that consumes the API
  programmatically; it fails at the first property access rather than at import,
  so the symptom is an undefined-function error rather than a missing module.
  `ts-node` was removed for exactly this reason — it consumed the API and had no
  consumer here.

- **License migration: BUSL-1.1 → FSL-1.1-Apache-2.0.** All future releases ship under the Functional Source License, Version 1.1, Apache 2.0 Future License. Use, modification, forking, internal self-hosting, and redistribution remain permitted; offering a hosted or embedded service that competes with our paid version(s) requires a separate commercial agreement. Each release automatically converts to Apache-2.0 two years after publication under the Grant of Future License clause. Past releases retain their original BUSL-1.1 terms per the LICENSE file published at that tag. Affected: `LICENSE`, `NOTICE`, `README.md` badge + License section, `CLAUDE.md` License Headers section, `CONTRIBUTING.md`, `package.json`, SPDX headers across 176 source files, `helm/computer-use-server/`, `THIRD-PARTY-LICENSES.md`, `computer-use-server/cli-defaults/*.json`.

## v0.11.0.0-rc.1 — release candidate for the 0.11.0 base bump (2026-08-02)

Pre-release. Contents are the `v0.11.0.0` entry below, cut so the 0.11.0 base can be exercised on real deployments while upstream settles. The final release waits for Open WebUI `0.11.1`/`0.11.2`, at which point the patch dry-run is re-run against that tag and the anchors adjusted if they moved.

Images carry the `0.11.0.0-rc.1` tag: `ghcr.io/wide-moat/open-computer-use`, `-server`, `-cleanup`, `-webui`. `main` stays on `v0.10.2.0`; nothing about this pre-release changes the stable line.

## v0.11.0.0 — rootless Podman sandboxes, Open WebUI base 0.11.0 (2026-08-23)

Minor release, and the first to carry the sandbox runtime change: the inner container
engine is now **rootless Podman** instead of Docker-in-Docker. Open WebUI base is bumped
from `0.10.2` → `0.11.0`, 616 upstream commits. `middleware.py` changed by 1074 lines, but the output-based tool loop survived intact — `convert_output_to_messages` only moved its definition out of the module and is still imported there. Four of the five `fix_tool_loop_errors` anchors needed rebasing. The other four patches
applied without anchor changes — which turned out to say less than it sounds: three of them
carried defects that applying cleanly does not reveal, and those are fixed here too.

On the Open WebUI side the headline change is that upstream now handles tool-loop and
code-interpreter errors itself.

### Changed

- **Sandboxes run on rootless Podman instead of Docker-in-Docker.** The chart renders one
  engine — a `quay.io/podman/stable:v5.3` sidecar (Podman Engine 5.3.2) serving the
  Docker-compatible API — and there is nothing to select between: the `dind` container, the
  `sandboxRuntime` switch and the `varLibDocker` PVC are gone. An older values file setting
  `sandboxRuntime: docker` names a key no template reads.

  What this removes from the cluster's side of the bargain:

  - **No privileged container.** Docker-in-Docker required one; rootless Podman does not.
  - **No RuntimeClass.** The default was `kata-qemu-heavy`, which most clusters do not have.
    The chart now installs on a stock Kubernetes node.
  - **No Block-mode PVC.** This one was not obvious and is the reason the other two could go:
    the Block volume existed only because virtio-fs inside the Kata guest drops the
    `security.capability` xattrs the sandbox image carries, so the image would not unpack on
    ordinary storage. No guest, no virtio-fs, no requirement — verified, not assumed: the
    9.47 GB image unpacks on plain filesystem storage with file capabilities intact.

  **Isolation changes shape, and it is a reduction rather than a wash.** The Kata VM boundary
  is replaced by user namespaces plus an AppArmor profile, set through
  `podAnnotations` (`container.apparmor.security.beta.kubernetes.io/podman`). The profile has
  to already exist on the node; a chart cannot install one, and without it the sandboxes are
  confined only by the cluster's default profile. Clusters that have Kata and want the VM
  boundary back can set `orchestrator.runtimeClassName` — but the Block-mode PVC has to come
  back with it, because virtio-fs returns with the guest.

  The orchestrator itself is unchanged. `podman system service` speaks the Docker API on the
  same socket path, so `DOCKER_SOCKET` still reads `unix:///var/run/docker.sock` and the
  Python Docker SDK talks to Podman without a code change.

- **`openwebui/Dockerfile`** — `ARG OPENWEBUI_VERSION=0.10.2` → `0.11.0`.
- **`fix_tool_loop_errors` no longer emits its own error banner.** 0.11.0 added `get_message_error_content()` and `emit_message_error()`, and calls both from the tool-loop and code-interpreter `except` blocks — the exact problem this patch was written for ("errors silently swallowed via `log.debug` + `break`"). Emitting our own `chat:message:error` on top would show the user two banners for one failure, so both modifications now call upstream's helper instead. That also gains something the patch never did: `emit_message_error()` persists the error to the chat, not just to the event stream. What stays ours is what upstream still does not do — restoring the text the user already saw before the failure, classifying transport faults into a "resend your message" hint, and rewriting the opaque "Model not found" into a budget-exhaustion message.
- **`fix_tool_loop_errors` Mod 1 (tool_loop)** — `convert_output_to_messages()` gained a `flatten_tool_images=True` kwarg and reflowed to one argument per line; the `except` body is upstream's new three-line form.
- **`fix_tool_loop_errors` Mod 2 (code_interp)** — same `except` rework, and the chat-title lookup collapsed from a multi-line ternary guarded by a `channel:`-prefix check to a one-liner guarded by the new `save_to_chat` flag.
- **`fix_tool_loop_errors` Mod 4 (done_bg)** — `ctx['assistant_message']` carries a `'content'` key again. It was dropped in 0.10.0 with `serialize_output()`; 0.11.0 rebuilds it from the streamed text (`''.join(content_parts) or get_output_text(output)`). Upstream also emits `publish_chat_finished_event` just above this block, so the wrap starts at the done-emit to avoid swallowing it.
- **`fix_tool_loop_errors` Mod 5 (iter)** — the loop bound moved off the module constant onto a local `max_tool_call_iterations`, resolved per request as `getattr(request.state, 'max_tool_call_iterations', CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS)`.
- **Mod 3 (SSE) unchanged**, and `fix_attached_files_position` needed no anchor edits. `fix_large_tool_results`, `fix_skip_embedding_chat_files` and `fix_skip_rag_files_native_fc` applied cleanly against 0.11.0 but were each wrong in a way applying cleanly does not reveal — see **Fixed** below.
- **Test fixtures** replaced with byte-identical `v0.11.0` extracts (`middleware_v0.11.0.py`, `retrieval_v0.11.0.py`); `conftest.py`, `fixtures/__init__.py` and the `V0102` identifiers across the five suites renamed to match.
- **Version pins refreshed**: `docker-compose.webui.yml`, `.env.example`, `README.md`, `openwebui/README.md`, `openwebui/patches/README.md`, `docs/openwebui-filter.md`, `helm/computer-use-server/Chart.yaml` `appVersion`, `examples/helm/with-open-webui/values-open-webui.yaml` `tag`, and the `Target:` line in every patch docstring.

### Fixed

- **`fix_large_tool_results` truncated tool results after the frontend had already been sent
  them.** Mod 2 anchored on `_saved_output`/`new_form_data`, code inserted by
  `fix_tool_loop_errors`. In `middleware_v0.11.0.py` the `chat:completion` emit that sends the
  results to the UI and persists them is at line 5217; that anchor is at 5223. Worse, being
  attached to the `new_form_data` block, the truncation did not run **at all** when the model
  answered immediately after a tool call and the loop exited — the common case for a single
  large `fetch_url`. The anchor now sits on upstream's own "Append a new empty message item"
  line, ahead of the emit.

  Two things follow. The patch no longer depends on `fix_tool_loop_errors` running first,
  because it anchors on upstream code rather than another patch's marker; the Dockerfile
  comment saying otherwise is gone. And a regression test asserts the injection point precedes
  the emit — the failure was silent in both directions (the patch reported success either way),
  so the position is asserted rather than the exit code.

- **`fix_skip_embedding_chat_files` injected code that cannot run on 0.10.x or later.** The
  knowledge-base fallback built its extractor as `Loader(engine=request.app.state.config…)`
  across some thirty keyword arguments. `app.state.config` was removed upstream — the 0.11.0
  retrieval source contains zero occurrences — so the fallback would raise on first use.
  `compile()` cannot see this, which is why it survived a base bump that re-audited every
  anchor. It now uses upstream's own `get_loader_config()` + `build_loader_from_config()`, both
  already imported in the target module.

- **`fix_skip_rag_files_native_fc` hid attached notes, chats and URLs from the model.** When
  the Computer Use tool is enabled the patch skips the RAG pipeline for ordinary files, keeping
  only items with `context == 'full'`. But upstream's `get_sources_from_items()` dispatches on
  six types — `text`, `note`, `chat`, `url`, `file`, `collection` — and only `file` has a
  sandbox equivalent the model can read off disk. Everything else the user attached was dropped
  silently, with no error and nothing in the log. The filter now keeps any item whose type is
  not `file`.

- **`server.json` was three base bumps stale** — the MCP registry manifest still declared `0.8.12.6`. Nothing in the repo reads it, which is how it drifted unnoticed since the 0.9.2 bump.
- **`CLAUDE.md` still described the version scheme as `v0.9.X.Y`** and used `v0.9.5.0` as its worked example, two bases after that stopped being true.

### Verified

- Cumulative dry-run in `openwebui/Dockerfile` order against a fresh `v0.11.0` source tree: all five backend patches apply, re-run clean (`ALREADY PATCHED`), both resulting files pass `ast.parse`, and the patched middleware carries exactly one error-banner emit in the tool-loop `except` — the duplicate-banner regression the `emit_message_error` rework exists to avoid.
- `pytest tests/patches/` — 31 passed against the new fixtures, including the new anchor-position regression test. That test was itself checked by restoring the old anchor and confirming it fails.
- Image build of `open-webui-ocu:0.11.0.0-rc.1` succeeds with all seven hard-fail guards green; every marker present in the built layers and both patched Python files parse inside the image.
- Runtime: container boots, `/api/version` returns `0.11.0`, `/health` returns `{"status":true}`, `init.sh` completes its whole sequence with zero tracebacks. Every endpoint it calls is still present in the 0.11.0 routers, so it needs no change.
- Browser end-to-end for both frontend chunk patches, with the chat seeded through the REST API rather than generated by a model — no LLM, so the check is reproducible without a provider key. Opening a chat whose assistant message contains an `html` code block opens the Artifacts panel unprompted and the iframe renders the page (`<h1>` reads `PATCH OK`); a chat containing a bare `/files/` URL produces the preview iframe. Zero console errors originate from the patched chunks. This matters more than usual here: `Chat.svelte` changed by 1106 lines and both patches rewrite minified bundles by regex, so "the patch applied" and "the behaviour survived" were genuinely separate questions.

### Upstream behavior changes worth knowing

- The tool-call iteration cap is now overridable per request via `request.state.max_tool_call_iterations`. The environment variable is unchanged: `env.py` still reads `CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS`, still accepts the pre-0.10 `..._RETRIES` name as a fallback, still defaults to 256. Existing `.env` files and the shipped compose file keep working.
- Errors raised while continuing a tool call are now persisted to the chat, so a failed turn leaves a record instead of only a transient banner.

## v0.10.2.0 — bump Open WebUI base to 0.10.2 (2026-07-26)

Minor release: Open WebUI base bumped from `0.9.5` → `0.10.2` (upstream shipped 0.9.6, 0.10.0, 0.10.1, 0.10.2). Upstream's v0.10.0 moved tool-output rendering out of the backend into a client-side renderer, deleting `serialize_output()` from `middleware.py`. That made one patch obsolete and moved anchors in three others. Both frontend chunk patches applied to the bumped base without changes.

### Removed

- **`fix_large_tool_args` patch.** Its target, `serialize_output()` in `utils/middleware.py`, no longer exists: upstream commit `0443ab3` (first released in 0.10.0) replaced server-side HTML serialisation with `StructuredOutputRenderer.svelte` + `structuredOutput.ts`, which build tool-call attributes as objects on the client. The problem the patch solved — a >10 KB `arguments="…"` attribute inside the persisted message body, re-parsed by the markdown/HTML tokenizer on every stream chunk — has no code path left. Removed `openwebui/patches/fix_large_tool_args.py`, its `RUN` line in `openwebui/Dockerfile`, `tests/patches/test_fix_large_tool_args.py`, and its rows in `openwebui/README.md` and `openwebui/patches/README.md`.

### Changed

- **`openwebui/Dockerfile`** — `ARG OPENWEBUI_VERSION=0.9.5` → `0.10.2`.
- **`fix_tool_loop_errors` Mod 1 (tool_loop)** — anchor no longer includes the trailing `if DETECT_CODE_INTERPRETER:`; upstream inserted a tool-call iteration-limit block ahead of it. The loop body itself is byte-identical to 0.9.5.
- **`fix_tool_loop_errors` Mod 2 (code_interp)** — track `metadata.get('chat_id', '')` in place of `metadata['chat_id']` in the post-loop title guard.
- **`fix_tool_loop_errors` Mod 4 (done_bg)** — `ctx['assistant_message']` no longer carries `'content': serialize_output(output)`; the frontend renders from `output` alone. Dropped from both SEARCH and REPLACE.
- **`fix_tool_loop_errors` Mod 5 (iter)** — track the renamed counter (`tool_call_retries` → `tool_call_iterations`) and the multi-line `while` guarded by `CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS`.
- **`fix_large_tool_results` Mod 3 (history)** — upstream inserted `form_data['messages'] = sanitize_tool_pairs(form_data['messages'])` between `process_messages_with_output(...)` and `get_system_message(...)`. The anchor now spans it, and history truncation runs after the sanitiser rather than before it.
- **`docker-compose.webui.yml`** — default `OPENWEBUI_VERSION:-0.9.2` → `0.10.2`. This default had been left behind by the v0.9.5.0 release, so `docker compose -f docker-compose.webui.yml up --build` on a fresh clone was building against 0.9.2 while the Dockerfile said 0.9.5.
- **Version pins refreshed** to match the new base: `README.md` compatibility section and embed snippet, `docs/openwebui-filter.md`, `.env.example` (was `0.8.12`), `helm/computer-use-server/Chart.yaml` `appVersion` and `examples/helm/with-open-webui/values-open-webui.yaml` `tag` (both were `0.9.2.4`).
- **`openwebui/patches/README.md` rewritten.** It claimed only `fix_artifacts_auto_show` was active and the rest were "commented out in `openwebui/Dockerfile`", and that patches "exit with code 0 even on failure". Both statements had been false since the fail-loud rewrite — every patch runs unconditionally and `sys.exit(1)` on an anchor miss. It also omitted `fix_tool_loop_errors` and `fix_preview_url_detection` entirely.

### Fixed

- **`pytest tests/patches/` was red on `main`** — 18 failures. The v0.9.5.0 release rewrote SEARCH/REPLACE anchors but kept only v0.9.1 / v0.9.2 fixtures, so every suite for a version-sensitive patch asserted against source shapes its own patch could no longer match. No CI workflow runs this directory, which is why it stayed unnoticed. Fixtures are now a single pair (`middleware_v0.10.2.py`, `retrieval_v0.10.2.py`) tracking the pinned base, and the duplicated per-version test classes collapse into one class per patch. The stale `v0.9.1` / `v0.9.2` fixtures are deleted (15,561 lines of vendored upstream source). `pytest tests/patches/` — 29 passed.
- **`fix_tool_loop_errors` injected three dead `serialize_output()` calls into its own error handlers.** The `chat:completion` emissions in the tool-loop, transport and code-interpreter error paths still called the helper 0.10.0 deleted. All three sit inside a broad `except`, so the `NameError` was swallowed and the user-facing error banner was lost — the exact failure the patch exists to prevent. They now emit the structured `output` payload alone, matching upstream. A build cannot catch this class of bug (patches only do string surgery; the injected code never runs at build time), so `tests/patches/` gained a guard asserting the patched middleware references no removed helper.
- **`CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS` was hardcoded to `200` in `docker-compose.webui.yml`** while `README.md` and `docs/INSTALL.md` documented it as an `.env` setting, so a configured value — including `-1` to disable the cap — was ignored. Now interpolated with `200` as the fallback, and added to `.env.example`.

### Verified

- Cumulative dry-run in `openwebui/Dockerfile` order against a fresh `v0.10.2` source tree: all five backend patches apply, re-run clean (`ALREADY PATCHED`), both resulting files pass `ast.parse`, and the patched middleware contains zero `serialize_output` references.
- Both frontend patches locate and rewrite their chunks inside `ghcr.io/open-webui/open-webui:0.10.2` (`D4rfk4Lu.js`, `_UcCb4Vt.js`), including the cache-bust rename.
- Image build of `open-webui-ocu:0.10.2.0-rc.2` from the production `openwebui/Dockerfile` succeeds with all seven hard-fail guards green; every patch marker is present in the built layers and both patched Python files parse inside the image.
- Runtime smoke test of that image: container boots, `/api/version` returns `0.10.2`, `/health` returns `{"status":true}`, and `init.sh` completes its whole sequence — admin created, `ai_computer_use` tool created and marked public-read, `computer_use_filter` created, activated and made global, valves seeded, `DEFAULT_MODEL_PARAMS` set.
- Browser end-to-end against a live model, driving the patched image through Chromium: asking for an HTML code block opens the Artifacts panel with no user click and the iframe renders the requested page (`<h1>` reads `PATCH OK`); a bare `/files/` URL in a reply produces the preview iframe. Zero console errors originate from the patched chunks. This is the check the previous two base bumps skipped — both frontend patches inject into minified SvelteKit chunks, and 0.10.0 rewrote `Chat.svelte` heavily, so anchor-found is not the same as behaviour-intact.
- `init.sh` needs no change: every endpoint it calls (`/api/version`, `/api/models`, `auths/{signin,signup}`, `tools/{create,id/…,access/update,valves/update}`, `functions/{create,id/…,toggle,toggle/global,valves/update}`, `models/create`, `configs/models`) is present in 0.10.2. `tests/test_init_sh_unchanged.sh` still matches its pinned hash.

### Upstream behavior changes worth knowing

- Tool results and reasoning render from the structured `output` array via `StructuredOutputRenderer.svelte`; assistant messages no longer persist a serialised HTML `content` string for tool calls. Anything reading `content` off a stored assistant message for tool history gets nothing.
- `CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS` replaces `CHAT_RESPONSE_MAX_TOOL_CALL_RETRIES`, and the upstream default rose from 30 to 256. `env.py` reads the old name as an explicit fallback, so existing deployments keep working; `docker-compose.webui.yml` and the README recipes now set the new name. `-1` disables the cap.
- `sanitize_tool_pairs()` now drops orphaned tool calls and tool results from the outgoing message list.
- `backend/start.sh` runs under `set -euo pipefail`. Our entrypoint wrapper is a separate script and is unaffected.

## v0.9.5.0 — bump Open WebUI base to 0.9.5 (2026-05-20)

Minor release: Open WebUI base bumped from `0.9.2` → `0.9.5` (upstream shipped 0.9.3, 0.9.4, 0.9.5 on 2026-05-09). All eight patches re-audited against the new source tree — none became obsolete (upstream did not natively address any of the eight problem domains in 0.9.3–0.9.5). Frontend patches (`fix_artifacts_auto_show`, `fix_preview_url_detection`) applied to the bumped base without changes; four backend patches needed updated SEARCH/REPLACE anchors to track upstream refactors.

### Changed

- **`openwebui/Dockerfile`** — `ARG OPENWEBUI_VERSION=0.9.2` → `0.9.5`.
- **`fix_tool_loop_errors` Mod 1 (tool_loop)** — upstream wrapped `convert_output_to_messages(output, raw=True)` into a multi-line call with the new `reasoning_format=get_reasoning_format(model)` kwarg (introduced for OR-aligned reasoning emission). SEARCH/REPLACE updated to match the multi-line shape at both call sites (stateful Responses API branch and Chat Completions branch).
- **`fix_tool_loop_errors` Mod 2 (code_interp)** — upstream guarded the post-loop `title = await Chats.get_chat_title_by_id(metadata['chat_id'])` with a `channel:`-prefix check, turning the assignment into a multi-line parenthesized ternary. SEARCH/REPLACE updated to match.
- **`fix_large_tool_results` Mod 3 (history)** — same `reasoning_format` refactor: upstream `process_messages_with_output(form_data.get('messages', []))` is now a multi-line call with `reasoning_format=get_reasoning_format(model)`. SEARCH/REPLACE updated to match.
- **`fix_skip_embedding_chat_files` Patch 1 (early return for regular uploads)** — upstream inserted an `else: await _validate_collection_access([collection_name], user, access_type='write')` branch between `if collection_name is None:` and `if form_data.content:` (part of the v0.9.5 file-access enforcement, upstream PR #24524). SEARCH/REPLACE updated to preserve the new guard.

### Verified

- Backend dry-run: all six middleware/retrieval patches applied cleanly against a fresh `v0.9.5` source tree; resulting files parse with `ast.parse` (Python syntax intact).
- Docker build: `docker build --platform linux/amd64 -t open-webui-ocu:0.9.5.0-rc.2 -f openwebui/Dockerfile openwebui/` succeeds end-to-end; all eight patches' hard-fail guards (`sys.exit(1)`) green.

### Upstream behavior changes worth knowing

- New default `AIOHTTP_CLIENT_ALLOW_REDIRECTS=False` blocks 3xx redirects in web fetch / tool servers / OAuth (we don't rely on redirects through `host.docker.internal`, no action).
- `POST /api/v1/auth/signout` (was GET); `init.sh` does not call signout, no action.
- New `IFRAME_CSP` env var controls iframe Content-Security-Policy (Artifacts panel uses iframes); leave default unless smoke test shows blank Artifacts.
- Per-model `params` dict now stripped from non-write-access users in `models.py` GET responses; `init.sh` runs as admin, no action.

## v0.9.2.4 — fix xlsx upload hang on Open WebUI 0.9.x (2026-05-11)

Patch release on top of v0.9.2.3 (Open WebUI base unchanged). Fixes a regression from the OWUI v0.8 → v0.9 base bump: the `fix_skip_embedding_chat_files` patch was written against the v0.8 sync database/storage signatures and quietly broke when OWUI made `Files.update_file_data_by_id`, `Storage.get_file`, and `Loader.load` async.

### Fixed

- **Open WebUI frontend spinner stuck forever after uploading an xlsx > 1 MB into a chat** (issue #96). `Files.update_file_data_by_id` went from `def` to `async def` between OWUI v0.8.x and v0.9.x; the skip-embedding patch was still calling it without `await`, so the coroutine was dropped without ever writing the `completed` status to the database. The HTTP response returned 200 immediately but the file row stayed in `pending`, and the OWUI frontend polled forever. Zip and other archive uploads were unaffected because they take a different code path that already used `await`. Fix is a one-line `await` on the patched call, plus a regression-guard test that asserts every patched `Files.update_file_data_by_id` call site is awaited.
- **KB-fallback path could freeze the OWUI backend for minutes during knowledge-base ingestion.** Patch 2 of `fix_skip_embedding_chat_files` called `Storage.get_file()` and `Loader.load()` directly inside the async `process_file` handler. Both are sync and CPU/IO-bound (PyMuPDF, Unstructured, Tika, etc.) and would block the OWUI event loop for the entire read/parse — no other request could be served until extraction finished. Upstream OWUI explicitly switched to `await asyncio.to_thread(Storage.get_file, ...)` and `await loader.aload(...)` at v0.9.1 for exactly this reason. The patch now does the same. New regression-guard test rejects any non-offloaded `Storage.get_file(` / `_fb_loader.load(` call site.

### Internal

- Audited every patch in `openwebui/patches/` against the OWUI v0.8 → v0.9 sync→async migration. Only `fix_skip_embedding_chat_files` regressed; the others either do not touch async-ified APIs (`fix_artifacts_auto_show`, `fix_attached_files_position`, `fix_large_tool_args`, `fix_large_tool_results`, `fix_preview_url_detection`, `fix_skip_rag_files_native_fc`) or were already updated for the migration in earlier releases (`fix_tool_loop_errors`, which has an inline `v0.9.1: async-ified` note).


## v0.9.2.3 — extract-text + bundled GSD/Superpowers skills (2026-05-03)

Patch release on top of v0.9.2.2 (Open WebUI base unchanged). Adds Anthropic's `extract-text` CLI for unified plain-text extraction across document formats, the `file-reading` and `pdf-reading` skills built on top of it, and bundled GSD + Superpowers skill packs auto-wired for Claude Code subagents. PyMuPDF and xlrd added to support the new skills (third-party licensing tracked in `THIRD-PARTY-LICENSES.md`). Hardened `settings.json` permissions — agent can no longer overwrite its own hook scripts.

### Added

- **`extract-text` CLI** — Anthropic's Rust-based unified plain-text extractor at `/usr/local/bin/extract-text`. Handles docx/odt/epub/xlsx/pptx/rtf/html/htm/ipynb in a single call. Vendored at `vendor/extract-text/` (see README there for licensing). Used by the new `file-reading` and `pdf-reading` skills.
- **`file-reading` skill** (`/mnt/skills/public/file-reading/`) — dispatch table telling the model which tool to use for each upload type, so it doesn't `cat` a PDF or slurp a 100MB CSV.
- **`pdf-reading` skill** (`/mnt/skills/public/pdf-reading/`) — content inventory, text extraction, page rasterization, embedded image / attachment / form-field extraction, and document-type-aware reading strategies.
- **`PyMuPDF==1.24.10`** and **`xlrd==2.0.1`** added to `requirements.txt` for PDF positional image extraction (`pdf-reading`) and legacy `.xls` parsing (`file-reading`).
- **GSD + Superpowers bundled for Claude Code** — pinned to `v1.9.9` (`gsd-build/get-shit-done`) and `v5.0.7` (`obra/superpowers`). Override at build time with `--build-arg GSD_REF=… --build-arg SUPERPOWERS_REF=…`. Cloned to `/opt/skills-external/`, then symlinked into `~/.claude/{skills,agents,commands,hooks}` from the entrypoint. Inside the container Claude Code gains `/gsd:*` slash-commands, `gsd-*` agents, superpowers skills, and SessionStart/Pre/PostToolUse hooks. Main AI is unaffected (still reads `/mnt/skills/`). `settings.json` hook commands are guarded with `[ -f … ] && … || true` so missing upstream files do not error every session.
- **`skills/README.md`** — licensing matrix and disclaimer for Anthropic-authored skills (`docx`, `pdf`, `pptx`, `xlsx`, `file-reading`, `pdf-reading`). Spells out that those directories are bundled for operators with a valid Anthropic agreement and points to the open-source fallbacks already documented in each `SKILL.md`.
- **`THIRD-PARTY-LICENSES.md`** — explicit licensing notice for bundled third-party deps. Calls out PyMuPDF AGPL-3.0 conveyance obligations, Anthropic Skill License materials, Apache-2.0 GSD/Superpowers, and the BSD-3-Clause Open WebUI base. Linked from the README License section.

### Security

- **Narrowed agent Write permissions inside the sandbox.** Previously `settings.json` granted `Write(/home/assistant/.claude/**)`, which let the agent overwrite the same `gsd-*.js` / `gsd-*.sh` hook scripts that run automatically on `SessionStart`, `PreToolUse`, and `PostToolUse` — a self-mutation / persistence path. Allowed writes are now narrowed to `Write(.claude/CLAUDE.md)` and `Write(.claude/settings.json)` only; `hooks/`, `agents/`, `commands/`, and `skills/` stay read-only. `tests/test-pr88-skills.sh` asserts the regression. (CodeRabbit PR #88.)

### Known followups

- The `extract-text` binary is vendored under `vendor/extract-text/` (~2MB blob). A future patch should fetch it at build time with sha256 verification and remove the blob from git. Source release URL TBD — Anthropic does not currently publish a public release for this CLI.
- GSD and Superpowers are pinned via upstream tags (`v1.9.9`, `v5.0.7`). Tags are mutable. `git clone --branch` does not accept raw commit SHAs; for strict reproducibility a future patch should switch to `git clone --no-checkout && git fetch <sha> && git checkout <sha>`.

## v0.9.2.2 — Multi-CLI Sub-Agent runtime followups (2026-04-26)

Patch release on top of v0.9.2.1 covering the v0.9.2.1 audit followups (Phases 9.1–9.6): real-CLI smoke harness, two production Dockerfile bug fixes (`opencode` schema, `codex` `model_provider` selector), Preview SPA active-CLI badge, CLI config templates with `OPENCODE_CONFIG_EXTRA` / `CODEX_CONFIG_EXTRA` env hooks, plus CodeRabbit review followups (resume-session CLI gate, opencode docs schema, dead helper, MD040 fences). Security: `pillow` 12.1.1 → 12.2.0 (CVE-2026-40192), `python-multipart` 0.0.22 → 0.0.26.

### Fixed

- **`opencode` runtime was non-functional in v0.9.2.1.** The Dockerfile entrypoint rendered `/tmp/opencode.json` with top-level key `"providers"` (plural) and a flat `"apiKey"` per provider. Current opencode (1.14.25) schema requires `"provider"` (singular) with credentials nested under `"options": { "apiKey": ... }`. Pre-fix containers exited with `Error: Configuration is invalid at /tmp/opencode.json ↳ Unrecognized key: "providers"` before reaching the model. Caught by Phase 9.1 real-CLI smoke (`tests/orchestrator/test_cli_adapters_live.py`).
- **`codex` `OPENAI_BASE_URL` was silently ignored in v0.9.2.1.** The Dockerfile heredoc declared `[model_providers.custom]` when `OPENAI_BASE_URL` is set but never set the top-level `model_provider = "custom"` selector, so codex always fell through to the default `openai` provider (api.openai.com) regardless. Fixed by prepending the selector line. Operators pointing codex at a corporate gateway are unblocked.

### Added

- **Real-CLI smoke suite** — `tests/orchestrator/test_cli_adapters_live.py` (gated by `RUN_LIVE_CLI=1`) plus `tests/orchestrator/mock_llm_server.py`. Runs each adapter end-to-end against a hermetic stdlib HTTP server speaking three wire protocols (Anthropic Messages SSE, OpenAI Responses SSE, OpenAI Chat Completions SSE) inside a docker-network sidecar. Closes audit concern #1 from `.planning/milestones/v0.9.2.1-AUDIT.md`. Also includes two regression guards that load the entrypoint-rendered configs (not test-side configs) so future heredoc regressions trip immediately.
- **Preview SPA active-CLI surface** — new `GET /api/runtime/cli` orchestrator endpoint returning `{cli, default_model, supports_cost}`. The preview UI (`computer-use-server/static/preview.js`) now renders an `ActiveCliBadge` pill in the toolbar showing the resolved sub-agent CLI; for codex/opencode it adds a "cost n/a" indicator so operators understand `cost_usd: null` is not a `$0.00` rendering bug. Pure progressive enhancement — silently disappears against older orchestrators without the endpoint. Endpoint contract pinned by `tests/orchestrator/test_runtime_cli_endpoint.py`. Closes audit concern #3.
- **CLI config templates companion** — `docs/cli-config-templates.md` with copy-paste recipes for codex+Azure, codex+approval/sandbox modes, codex+custom OpenAI-compat gateways, opencode+instructions, opencode+MCP federation, opencode+custom openai-compat providers, opencode+agent personas, plus a verification recipe. Backed by two new env hooks in the Dockerfile entrypoint: **`OPENCODE_CONFIG_EXTRA`** (replaces `/tmp/opencode.json` verbatim) and **`CODEX_CONFIG_EXTRA`** (appended to `~/.codex/config.toml` after the canonical block). Both backwards-compatible — unset = today's behaviour. Cross-linked from `docs/multi-cli.md` under `## Advanced configs`. Closes audit concern #2.

### Docs

- `docs/multi-cli.md` cross-links the new templates companion under the `## Advanced configs` section.
- `.planning/REQUIREMENTS.md` `DOCS-MULTICLI-01..04` checkboxes flipped from `[ ]` → `[x]` (cosmetic-only sync; the docs themselves shipped in commit `245d1b6`).

## v0.9.2.1 — Multi-CLI Sub-Agent Runtime (2026-04-26)

Adds OpenAI Codex CLI (`@openai/codex@0.125.0`) and OpenCode (`opencode-ai@1.14.25`, sst fork) as drop-in alternatives to Claude Code across the entire sub-agent surface. A single `SUBAGENT_CLI=claude|codex|opencode` env switch routes every sub-agent invocation through the chosen CLI with identical operator UX. Default unset = `claude` (byte-identical backwards-compat with v0.9.2.0).

### Added

- **`SUBAGENT_CLI` env switch** with hard-fail allowlist validation (typo → orchestrator refuses to start) (CLI-01, CLI-02, CLI-03)
- **`cli_runtime.py` resolver + `cli_adapters/` package** (Protocol, `SubAgentResult` dataclass, three adapters) (ADAPT-01)
- **CodexAdapter** — `codex exec --ephemeral --json --output-last-message` with `--cd /tmp/codex-agents-<uuid>/` workdir (ADAPT-03)
- **OpenCodeAdapter** — `opencode run --model <provider/model> --format json --dangerously-skip-permissions` (ADAPT-04)
- **Per-CLI model resolution** with hard-fail on cross-CLI alias misuse (e.g. `sonnet` on codex → actionable ValueError) (ADAPT-06)
- **`cli_runtime.dispatch(...)` single entry point**; `mcp_tools.sub_agent` rewritten as thin orchestration over it; production claude path is byte-identical to v0.9.2.0 (golden-snapshot tested) (ADAPT-02, ADAPT-05)
- **Per-CLI auth allowlists** in `_create_container` prevent cross-CLI key leak (Pitfall 1) (AUTH-01)
- **OpenCode config rendered to `/tmp/opencode.json`** (NOT volume) with `{env:VAR}` substitution syntax — zero plaintext secrets on disk (Pitfall 7) (AUTH-02)
- **Codex `~/.codex/config.toml`** rendered conditionally with `[model_providers.custom]` block when `OPENAI_BASE_URL` is set (AUTH-03)
- **Marker-gated entrypoint heredoc** (`/tmp/.cli-runtime-initialised`) — config rendering fires once per container lifetime (AUTH-04)
- **`.bashrc` autostart honours `${SUBAGENT_CLI:-claude}`** with `NO_AUTOSTART=1` env + `/tmp/.no_autostart` sentinel escape hatches; marker renamed `CLAUDE_AUTOSTARTED → SUBAGENT_AUTOSTARTED` (TERM-01, TERM-02, TERM-03)
- **Cost-guardrail caveat** — `cost_usd=None` rendered as `cost: unavailable` (never `$0.00`) for non-claude CLIs; `SUB_AGENT_TIMEOUT` documented as backstop
- **`docs/multi-cli.md`** — operator guide with worked OpenCode + qwen3-coder + OpenRouter recipe (DOCS-MULTICLI-01, DOCS-MULTICLI-02)

### Tests (mandatory, ship with the code)

- **TEST-01** — Docker image installs all three CLIs; `claude --version`, `codex --version`, `opencode --version` smoke (image build + `tests/test-docker-image.sh`)
- **TEST-02** — `cli_runtime.resolve_cli` resolver suite (`tests/orchestrator/test_cli_runtime.py`, ~23 cases inc. invalid SystemExit + per-CLI passthrough)
- **TEST-03** — `cli_adapters` adapter argv + parse_result coverage with per-CLI fixtures under `tests/fixtures/cli/` (`tests/orchestrator/test_cli_adapters.py`)
- **TEST-04** — end-to-end `sub_agent(...)` dispatch suite parametrized over all 3 CLIs, signature regression guard, cost-rendering "unavailable" gate (`tests/orchestrator/test_sub_agent_dispatch.py`)
- **TEST-05** — `openwebui/init.sh` byte-equals v0.9.2.0 baseline regression (`tests/test_init_sh_unchanged.sh`, hardcoded sha256 `31ce03b6...c27a7`)
- **TEST-06** — per-CLI dispatch + marker-gating (`GATED-SENTINEL`) + `NO_AUTOSTART` escape-hatch smoke in `tests/test-docker-image.sh`

### Backwards compatibility

- `SUBAGENT_CLI` unset / empty / `claude` → byte-identical to v0.9.2.0 (verified by golden-snapshot test of `claude_command` argv + end-to-end dispatch shell-command equality)
- `mcp_tools.sub_agent(task, max_turns=25, model="sonnet")` MCP signature unchanged — every existing skill caller works without modification
- Existing volumes with old `CLAUDE_AUTOSTARTED=1` markers continue to work — autostart fires once on next session via the new independent `SUBAGENT_AUTOSTARTED` check; no double-firing, no regression
- `dangerous_mode` terminal flow (`app.py:847`) migrated from injecting `CLAUDE_AUTOSTARTED=1` to the new documented `NO_AUTOSTART=1` escape hatch
- `openwebui/init.sh` unchanged (CI-enforced)

### Documentation

- `docs/multi-cli.md` (DOCS-MULTICLI-01, DOCS-MULTICLI-02) — full operator guide with switch matrix, worked recipes, troubleshooting, prior-art credits
- `README.md` cross-link in the Sub-agent / Pro tip area (DOCS-MULTICLI-03)
- `docs/INSTALL.md` cross-link in the env configuration section (DOCS-MULTICLI-03)
- `.env.example` — `# === Optional: Multi-CLI sub-agent runtime ===` block with `SUBAGENT_CLI=` (commented) + per-CLI auth env templates (DOCS-MULTICLI-03)
- `CHANGELOG.md` v0.9.2.1 entry (this entry) (DOCS-MULTICLI-04)

### Prior art

- [OpenAI Codex CLI documentation](https://developers.openai.com/codex/cli/reference) — `codex exec` flag spec + JSONL event schema
- [sst/opencode documentation](https://opencode.ai/docs/) — `opencode run`, `{env:VAR}` config substitution, providers list
- [OpenRouter qwen3-coder model page](https://openrouter.ai/qwen/qwen3-coder)
- Issue #40 / PR #41 (community contribution by `rahxam`) — informed Phase 3 (Claude Code gateway compatibility), the foundation this milestone builds on

---

## v0.9.2.0 (2026-04-25)

### Breaking Changes — Open WebUI base bump 0.8.12 → 0.9.2

- **Base image bumped**: `openwebui/Dockerfile` default `ARG OPENWEBUI_VERSION=0.8.12` → `0.9.2`; `docker-compose.webui.yml` default `OPENWEBUI_VERSION:-0.8.12` → `OPENWEBUI_VERSION:-0.9.2`. A plain `docker compose -f docker-compose.webui.yml up --build` on a fresh clone now builds against `ghcr.io/open-webui/open-webui:0.9.2`. No v0.9.1 release was cut — the 0.9.1-era patches were rewritten as the v0.9.2 baseline (Phases 4–6), and only the v0.9.2 re-verification (Phases 7–9) was carried into this release.
- **Strict version pinning**: this build (`v0.9.2.X`) is strictly built and verified against Open WebUI 0.9.2. The first 3 segments of our build version always equal the Open WebUI base version. Operators on Open WebUI 0.8.12 or 0.9.1 must use the corresponding `v0.8.12.Y` / `v0.9.1.Y` build (the latter was never publicly cut — 0.9.1-era fixtures remain green in `tests/patches/` only as regression coverage for the in-memory `V091_SHIM` inside `fix_tool_loop_errors`, not as a supported runtime target).

### Features — Open WebUI 0.9.2 compatibility (Phases 4–9)

Eight patches re-verified against Open WebUI v0.9.2, zero dropped. Each patch carries a `sys.exit(1)` fail-loud on anchor miss and an idempotency marker so re-running the patch on an already-patched layer is a no-op.

- **fix_artifacts_auto_show** (FE) — matches at v0.9.2. Auto-opens the Artifacts panel when an assistant message contains an HTML code block. Marker: `FIX_ARTIFACTS_AUTO_SHOW` baked into the compiled SvelteKit chunks.
- **fix_preview_url_detection** (FE) — matches at v0.9.2. Auto-inserts the preview iframe for `{server}/preview/{chat_id}` and `{server}/files/{chat_id}/...` URLs. Host-agnostic: iframe src reconstructed at runtime from the matched URL's own origin. Marker: `FIX_PREVIEW_URL_DETECTION`.
- **fix_tool_loop_errors** (BE) — rewritten for v0.9.2. SEARCH/REPLACE extended with the new `'metadata': metadata,` key that v0.9.2 upstream added to `new_form_data = {…}` inside the tool-call retry loop. A 10-line in-memory `V091_SHIM → V092_SHIM` keeps v0.9.1 fixtures green as regression coverage only. Marker: `FIX_TOOL_LOOP_ERRORS`.
- **fix_large_tool_results** (BE, cascade on patch 3) — rewritten for v0.9.2. SEARCH_TOOL_LOOP extended through the full `new_form_data = {…}` closing brace with `'metadata': metadata,` to keep the 3+4 cascade atomic. `tests/patches/test_fix_large_tool_results.py::test_cascade_with_patch_3_on_v092` pins the invariant. Marker: `FIX_LARGE_TOOL_RESULTS`.
- **fix_large_tool_args** (BE) — matches at v0.9.2. Count-assertion `content.count(OLD_ARGS) == 2` still holds. Truncates oversized tool-call arguments in HTML attributes to prevent browser freeze on large tool outputs. Marker: `FIX_LARGE_TOOL_ARGS`.
- **fix_attached_files_position** (BE) — matches at v0.9.2. Moves file context to the end of messages to improve prompt-cache hit rates with large file attachments. Marker: `FIX_ATTACHED_FILES_POSITION`.
- **fix_skip_embedding_chat_files** (BE) — matches at v0.9.2. Both retrieval.py anchors byte-identical; skips expensive text extraction + embedding for >1MB chat uploads, using the knowledge-base fallback instead. Marker: `FIX_SKIP_EMBEDDING_CHAT_FILES`.
- **fix_skip_rag_files_native_fc** (BE) — matches at v0.9.2. Skips the RAG pipeline for chat files when the Computer Use tool is enabled, avoiding unnecessary processing for native-function-calling models. Marker: `FIX_SKIP_RAG_FILES_NATIVE_FC` (filename / marker-name mismatch is deliberate — documented in Phase 6 verdict).

Build proof: `open-computer-use:0.9.2-test` built from the full production `openwebui/Dockerfile` with `--build-arg OPENWEBUI_VERSION=0.9.2` emits 8 `PATCHED: fix_* applied successfully.` lines and 0 `ERROR:` lines. Test proof: `python -m pytest tests/` green in `python:3.13-slim` — 248 passed, 0 failed.

### Features — Claude Code gateway compatibility rollup (Phase 3, GATEWAY-01..12)

Phase 3 code shipped on `main` on 2026-04-12 (commit `38347fd`) but never had its own release — it is cut here. Fixes issue [#40](https://github.com/Wide-Moat/open-computer-use/issues/40); inspired by PR [#41](https://github.com/Wide-Moat/open-computer-use/pull/41), rewritten with tests and without deploy-specific churn. Full operator guide in [docs/claude-code-gateway.md](docs/claude-code-gateway.md).

- **GATEWAY-01** — Root-cause bug fix. `computer-use-server/context_vars.py:14` `current_anthropic_base_url` default changed from `"https://api.anthropic.com/"` to `None`, restoring the `or ANTHROPIC_BASE_URL` env fallback at `docker_manager.py:359`. Previously the truthy default blocked every env override silently.
- **GATEWAY-02** — Ten module-level env constants added to `docker_manager.py` (captured at import time via `os.getenv(NAME, "")`): `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`, `DISABLE_PROMPT_CACHING{,_SONNET,_OPUS,_HAIKU}`. Organised into model-IDs and compat-flags sub-groups.
- **GATEWAY-03** — `CLAUDE_CODE_PASSTHROUGH_ENVS` tuple + deterministic passthrough loop in `_create_container`: each of the ten (NAME, VALUE) pairs injects into `extra_env` only when truthy. Empty / unset vars never reach the sandbox.
- **GATEWAY-04** — `mcp_tools.sub_agent` widened: aliases (`sonnet` / `opus` / `haiku`) honour `ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL` when set; direct IDs (`claude-sonnet-4-6`, LiteLLM-style `anthropic/claude-sonnet-4-6`) pass through unchanged; empty/None falls back to Sonnet default. Case-insensitive after `strip()`.
- **GATEWAY-05..07** — Test coverage: new `tests/orchestrator/test_docker_manager.py` (three operator paths — no vars / auth-only / full gateway), `tests/orchestrator/test_sub_agent_model_resolution.py` (seven alias + direct-ID cases), and a regression test proving `ANTHROPIC_CUSTOM_HEADERS` injection at `docker_manager.py:378` is unchanged.
- **GATEWAY-08..09** — `docker-compose.yml` declares `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, and the 10 gateway vars under the `${VAR:-}` pattern; `.env.example` grows a `# === Optional: Claude Code sub-agent gateway overrides ===` block. Adding `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL` is itself a bug fix — they were missing from compose, so Path B (auth-only) never worked end-to-end on a vanilla `docker compose up`.
- **GATEWAY-10** — New `docs/claude-code-gateway.md`: three-path operator table (zero-config Claude Code `/login` → auth-only → full gateway), worked LiteLLM recipe with `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` + `DISABLE_PROMPT_CACHING=1`, Azure/Bedrock-via-LiteLLM cross-reference, verification checklist, troubleshooting pointer to issue #40.
- **GATEWAY-11** — README.md "Open WebUI Integration" section + `docs/INSTALL.md` configuration table cross-link the new doc.
- **GATEWAY-12** — `python -m pytest tests/ -v` green in `python:3.13-slim` with zero new warnings; the three project shell tests remain green.

### Known Limitations

- **Live UI UAT for v0.9.2 deferred to the user**: Phase 5's Artifacts-panel + preview-iframe screenshots were captured against a v0.9.1-era image. For v0.9.2 the automation proves (a) patch markers are baked into `/app/build/_app/immutable/chunks/*.js` of the built `open-computer-use:0.9.2-test` image, (b) the patched middleware and retrieval modules parse as valid Python AST, (c) cascade 3+4 on v0.9.2 fixtures is atomic — but end-to-end localhost UX verification (open a chat, request an HTML artifact, request a file preview) is the user's post-release UAT step. It does not block the release; the mechanical proof that the v0.9.2 patched chunks carry their fail-loud markers and parse cleanly is in place.

## v0.8.12.8 (2026-04-19)

### Breaking Changes — filter v4.1.0, preview-mode surface narrowed
- **`PREVIEW_MODE="artifact"` and `PREVIEW_MODE="both"` removed** (closes #43). `outlet()` no longer emits a fenced ```html `<iframe>` block — it only appends a markdown preview link. The extra html block was redundant *and* actively harmful: the `fix_preview_url_detection` frontend patch is guarded by `!htmlGroups.some(o=>o.html)`, so pre-emitting an html block from the filter caused the patch to skip detection, leaving the iframe rendered as a raw code fence in chat (the #43 symptom that had been reappearing since v3.2.0). Only `"button"` and `"off"` remain; `"button"` is the new default. Matches the internal prod v3.8.0 behaviour — the long-standing production reference was never using artifact mode to begin with.
- **Migration**: saved `"artifact"` / `"both"` values now fail Pydantic validation on load. Re-seed Valves with `rm /app/backend/data/.computer-use-initialized` + container restart. `init.sh` will write the new `"button"` default.

### Breaking Changes — single public URL on the server
- **Server env renamed**: `FILE_SERVER_URL` → `PUBLIC_BASE_URL`. It's now the *single source of truth* for the browser-facing URL — baked into `/system-prompt` text and returned to the Open WebUI filter via the new `X-Public-Base-URL` response header. Rename in your `.env`.
- **Tool Valve renamed**: `FILE_SERVER_URL` → `ORCHESTRATOR_URL` (same semantics — internal URL for MCP forwarding).
- **Filter Valves changed**: `FILE_SERVER_URL` and `SYSTEM_PROMPT_URL` Valves *removed*. Replaced with a single `ORCHESTRATOR_URL` Valve (internal URL for server→server fetch). The filter reads the public URL from the server's response header — no more "two `FILE_SERVER_URL` settings that must match" footgun.
- **Filter `_fetch_system_prompt()` signature**: now returns `tuple[public_url, prompt] | None` instead of `str | None`. `outlet()` reads `public_url` from the cache.
- **`DOCKER_AI_UPLOAD_URL` env var renamed**: → `ORCHESTRATOR_URL` (consistent with the Valves).
- **`docker-compose.webui.yml`**: dropped `MCP_SERVER_EXTERNAL_URL` and `extra_hosts: host.docker.internal:host-gateway`. The open-webui and computer-use-server containers now talk over the shared Compose default network using Docker service DNS (`http://computer-use-server:8081`).

**Migration:**
1. Rename `FILE_SERVER_URL=...` → `PUBLIC_BASE_URL=...` in your `.env`.
2. If you run `docker-compose.webui.yml` / `init.sh`: the init script re-seeds Valves with the new names automatically — delete `/app/backend/data/.computer-use-initialized` and restart `open-webui` so it re-runs.
3. If you configured Valves manually in the Open WebUI admin UI, re-enter them: tool `ORCHESTRATOR_URL`, filter `ORCHESTRATOR_URL`. The old `FILE_SERVER_URL` / `SYSTEM_PROMPT_URL` entries in the DB are ignored by the new Pydantic model and can be left in place.

### Features
- **Filter v3.2.0 → v3.4.0 — simpler Valves**: the three boolean preview/archive Valves (`ENABLE_PREVIEW_ARTIFACT`, `ENABLE_PREVIEW_BUTTON`, `ENABLE_ARCHIVE_BUTTON`) were first collapsed in v3.3.0 into two Literal Valves (`PREVIEW_MODE` ∈ `artifact | button | both | off`, `ARCHIVE_BUTTON` ∈ `on | off`), then removed entirely in v3.4.0 along with their `@model_validator` bridge. Users upgrading straight from v3.2.0 revert to defaults — upgrade via v3.3.0 first if you need to preserve saved preferences.
- **Filter v4.0.0 — public URL owned by server**: the filter no longer carries a public-URL Valve. The server's new `/system-prompt` response header `X-Public-Base-URL` delivers it to the filter per request; `_fetch_system_prompt()` caches the (public_url, prompt) pair so `outlet()` can decorate with browser-facing preview/archive links without its own Valve.
- **Startup warning for default `PUBLIC_BASE_URL`** (closes #59): the orchestrator logs a one-time warning when the env var is still the hardcoded internal-DNS default (`http://computer-use-server:8081`), catching the #43-class "preview panel never appears" misconfiguration at boot rather than silently in production.

### Fixes
- **Filter — browser-only sessions got no preview**: `outlet()` previously required a `/files/{chat_id}/…` URL in the assistant message to inject preview decorations, so pure browser sessions (playwright / chromium with no downloadable file) saw nothing. Detection now also fires on a `<details type="tool_calls">` block that references a browser tool. Scoped to the tag — free-text keyword mentions never false-trigger. Archive button stays gated on file URLs (unchanged).
- **sub-agent `max_turns` default inconsistency**: the Open WebUI tool's `sub_agent(max_turns=...)` signature defaulted to 50, silently overriding the server's 25 default on every call. Unified to 25 alongside a sweep of stale doc references (docs/SKILLS.md, skills/public/sub-agent/references/usage.md).

### Tests
- **Filter — `BrowserToolTrigger` class** (10 tests): exercises the new browser-tool trigger — every keyword, html-escaped `arguments="…"` (production delivery form), free-text scoping, non-tool_calls `<details>` blocks, empty content, preview-button injection, archive button still gated on files, invariant that no fenced-html or raw iframe is ever emitted, idempotency across repeated `outlet()` calls.
- **Filter — legacy-value guard**: `test_legacy_preview_mode_values_rejected_on_construction` asserts that saved `"artifact"` / `"both"` Valve values from v3.x / v4.0.0 DBs fail Pydantic validation loudly instead of silently falling through.
- **Server — `test_startup_warnings.py`** (3 tests): env unset → warn; custom URL → silent; explicit default literal → warn.

### Documentation
- `docs/openwebui-filter.md`: Valves reference updated for v3.4.0 (legacy rows removed), "Preview UX: which PREVIEW_MODE fits you?" retained.
- `openwebui/functions/README.md` Valve table refreshed.
- `openwebui/init.sh` bootstrap payload updated to new schema field names so fresh deployments start with new names in the DB.

### Features — maximum MCP-native system-prompt surface (six tiers)

The same per-session system prompt is now delivered through six channels backed by a single cached renderer (`computer-use-server/system_prompt.py::render_system_prompt`, 60s TTL per `(chat_id, user_email)`). Redundancy is by design — a client may skip any one channel and still get the prompt somewhere. Complete map at `docs/system-prompt.md`.

1. **Tool descriptions** — `bash_tool` + `view` docstrings point at `/home/assistant/README.md` as a recovery hint (`tools/list` surface).
2. **`/home/assistant/README.md` in sandbox** — rendered on container creation via `container.put_archive`, survives container removals via the `chat-{chat_id}-workspace` volume.
3. **Static `InitializeResult.instructions=` hint** — one-liner pointing at README + `resources/list` for clients that render the initialize-result field directly.
4. **Dynamic `InitializeResult.instructions`** — per-request content via `current_instructions` ContextVar + `_DynamicInstructionsServer` subclass swapped onto `mcp._mcp_server`. Works thanks to `stateless_http=True` + per-request `create_initialization_options()`.
5. **`resources/list` + `resources/read`** — uploaded files surfaced as `FunctionResource` per chat, URI shape `file://uploads/{chat_id}/{url-encoded rel_path}`. Registered on container creation AND on `POST /api/uploads` so new uploads appear without client reconnect. Upload itself stays on HTTP (MCP has no upload primitive).
6. **`GET /system-prompt` HTTP endpoint** — backward compat for the Open WebUI filter. Now reads `X-Chat-Id` / `X-User-Email` (plus `X-OpenWebUI-*` aliases) with header priority over query params; delegates to the shared renderer; `X-Public-Base-URL` response header preserved.

All four "dynamic" tiers (2, 4, 5, 6) hit the same `render_system_prompt` cache — one render per `(chat_id, user_email)` per minute regardless of fan-out.

**Deliberately NOT using `@mcp.prompt("system")`.** We considered exposing the prompt via the MCP `prompts/*` primitive (OpenAI Agents SDK's documented fallback `server.get_prompt(...)`), but the 2025-11-25 spec restricts `PromptMessage.role` to `{user, assistant}` and positions prompts as user-controlled slash commands. Naming a prompt `"system"` clashes with both, and `InitializeResult.instructions` is the canonical field for server-supplied instructions. Tier 4 covers that canonically — a `prompts/get("system")` entry would have been off-spec duplication.

Duplication analysis (per-scenario): Open WebUI through LiteLLM sees the prompt **once** via the filter's `inlet()` inject — `InitializeResult.instructions` is not forwarded by LiteLLM. MCP-native clients (Agents SDK, Inspector, Claude Desktop) see it **once** via `InitializeResult.instructions`. In both paths a second copy appears only if the model follows the Tier 1 recovery-nudge and calls `view /home/assistant/README.md`. Worst case: 2 copies; typical case: 1. The nudge stays to help pathological clients that strip system prompts — see `docs/system-prompt.md` for tightening options.

Private-API touchpoints are pinned by tests (`tests/orchestrator/test_dynamic_instructions.py`, `test_mcp_resources.py`) and documented at their call sites with SDK line references; when bumping `mcp` minor, re-run these tests first.

### Reliability — post-review hardening (PR #65 follow-ups)

After independent review of the six-tier surface a series of regression and
silent-failure fixes landed. Each one closed a real path that was broken in
production *or* in the upgrade story:

- **`/mcp` returned HTTP 500 in production builds**. Dockerfile didn't `COPY` `mcp_resources.py` and `uploads.py`, the lifespan caught the resulting `ImportError` and yielded WITHOUT calling `session_manager.run()`, and from then on every MCP call hit `Task group is not initialized`. uvicorn's default error path returned a body-less 500 with no traceback — the failure was 100% silent server-side and surfaced only as empty tool output in the chat. Three changes prevent recurrence:
  - `Dockerfile` now copies the missing modules.
  - Lifespan no longer swallows `ImportError` — boot crashes loud if anything required is missing, with the matching dead `try/except` in `_init_mcp()` and the module-level `get_mcp_app` import removed for a single failure mode.
  - New CI job `Smoke — POST /mcp returns 200` builds the server image, boots it, and POSTs an `initialize` request. Catches this exact regression in one run.
- **Open WebUI tool now classifies every failure mode loudly**. `openwebui/tools/computer_use_tools.py` previously returned `"[No output]"` on empty results and a single `"[Error] MCP call failed"` for any exception, often without firing the `status="error"` SSE event — the chat tool-call collapsible looked green and empty, and the AI concluded the tool was broken. New behaviour:
  - Pre-flight probes both `GET /health` AND `POST /mcp initialize` (the second is what catches the silent 500 above). 30s cache, 3s timeout.
  - Tiered exception classes: `[CONFIG ERROR]`, `[NETWORK ERROR]`, `[MCP TRANSPORT ERROR]`, `[UNEXPECTED ERROR]`, `[TOOL ERROR]`.
  - Empty-result disambiguation: `"[Command produced no output. Exit was successful — this is not an error.]"` instead of `"[No output]"`. Phrasing is deliberate — AI models read the string literally.
  - `Tools._run_tool` consolidates the five per-tool wrappers; `_looks_like_error()` replaces five drifted heuristics so `view`/`str_replace`/`create_file` now report errors with the same fidelity as `bash_tool`.
- **Filter `outlet()` no longer drops preview/archive buttons silently** when the inlet cache is cold (Open WebUI restart between inlet and outlet). It re-fetches `/system-prompt` to recover the public URL — same `_fetch_system_prompt` stale-cache fallback path, so a truly down server still skips decoration ("broken links worse than no links" invariant preserved).
- **`/system-prompt` legacy n8n contract restored**. PR #65 had auto-substituted `chat_id="default"` when no chat_id was supplied; now it returns the template with `{file_base_url}` / `{archive_url}` / `{chat_id}` placeholders intact when nothing is supplied, matching pre-v4.0.0 behaviour for external integrators that do their own substitution.
- **Per-`(chat_id, user_email)` render lock**. Slow `skill_manager` providers no longer serialize all MCP requests across all chats — only the matching key blocks.
- **Atomic resource sync window**. `mcp_resources.sync_chat_resources` builds the new resource set outside the lock and swaps in one synchronous critical section; `asyncio.Lock` swapped to `threading.Lock` so the worker-thread `asyncio.run()` path actually serializes against the request-loop path.
- **Defensive shape assertions** on `mcp._mcp_server` and the lowlevel `Server` before the Tier 4 class swap. SDK rename now fails at import with a pointer to re-pin, instead of silently dropping Tier 4 to static instructions.
- **`mcp` SDK pinned** to `1.27.0` with a comment listing the three private-API touchpoints the pin guards.
- **`docker_manager.put_archive` checked** for `False` return — README write failures surface as exceptions instead of false-success log lines.
- **Sanitization at boundaries**: `sync_chat_resources(chat_id)` calls `sanitize_chat_id` so case variants (`"Chat"` vs `"chat"`) share the same stale-uri set; `/system-prompt` does the same on header/query chat_id.

### CI

- New job `Pytest — orchestrator` runs `pytest tests/orchestrator/` (97 tests) on every push. Existed in repo, never wired to CI.
- New job `Smoke — POST /mcp returns 200` boots the server image and runs `tests/test-mcp-endpoint-live.sh` — the smoke that would have caught the silent 500 bug in one CI run.

### Dependencies
- `claude-code` pinned to `2.1.114` in the sandbox `Dockerfile` for reproducible builds. `latest` still available as an override.
- `mcp` Python SDK pinned to `1.27.0` in `computer-use-server/requirements.txt` (was `>=1.0.0`). Required because the orchestrator uses three private attributes (`mcp._mcp_server`, `mcp._resource_manager._resources`, `mcp._mcp_server.request_context.session`) that have no public equivalent. Tests `test_dynamic_instructions.py` and `test_mcp_resources.py` pin the contract — re-run them on every minor bump.

## v0.8.12.7 (2026-04-13)

### Features
- **System prompt extraction**: the ~460-line hardcoded Computer Use system prompt has been moved from `computer_link_filter` into the orchestrator's `GET /system-prompt` endpoint (ported from the internal fork's v3.7/v3.8 architecture). The server now performs full substitution: `{file_base_url}`, `{archive_url}`, `{chat_id}` placeholders from an optional `chat_id` query param, and the `<available_skills>` XML block from an optional `user_email` query param. Per-user skill lookup falls back gracefully to `DEFAULT_PUBLIC_SKILLS` when no external skill provider is configured (community default).
- **Filter rewrite (v3.0.2 → v3.1.0)**: `openwebui/functions/computer_link_filter.py` is now a thin HTTP client — it fetches the fully-baked prompt from the server and injects it as-is. No more client-side URL substitution. File size dropped from 636 lines to under 250.
- **LRU cache with stale-cache fallback**: the filter keeps an `OrderedDict` LRU keyed by `chat_id`, 5-minute TTL, max 100 entries, O(1) eviction. On fetch failure (server down, timeout, non-200), it serves the stale entry for the same chat if present; otherwise it skips injection (same safe no-op path as the missing-`chat_id` case). No broken URLs ever reach the model.
- **New Valve `SYSTEM_PROMPT_URL`**: optional override for the endpoint URL (empty = derive from `FILE_SERVER_URL`).
- **Filter v3.1.0 → v3.2.0 — preview panel**: new Valves expose `/preview/{chat_id}` so the archive button can open the preview iframe on stock Open WebUI installs without the project's artifact patch.
- **Claude Code gateway compatibility** (fixes #40, PR #46): the orchestrator now passes `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, and related gateway env vars through to the sandbox container; `sub_agent` model resolution widened to accept direct model IDs in addition to aliases. Docker Compose gets a gateway-overrides block and `.env.example` documents the full set.

### Fixes
- **Filter — cross-user prompt cache leak**: cache key now scoped so one user's baked prompt can't be served to another user; archive-button detection restricted to assistant messages and the current `chat_id` only.
- **Filter — URL scheme validation**: `/system-prompt` fetch now validates the URL scheme (http/https only) and narrows the exception surface so a misconfigured Valve can't SSRF or hang.
- **Filter — non-string system content**: `inlet()` no longer crashes when Open WebUI hands it a non-string system message.
- **sub-agent — delegation scope**: restricted to code-only tasks; stops wasting API calls on non-code delegations.

### Tests
- 5 new pinning tests in `tests/orchestrator/test_system_prompt_endpoint.py` cover the `/system-prompt` contract: `chat_id` substitution, `user_email` default-skills fallback, legacy `file_base_url` / `archive_url` params, no-param degraded path, `text/plain` content-type.
- 7 new cache tests in `tests/test_filter.py::SystemPromptFetchCache`: fresh fetch populates cache, cache hit within TTL skips HTTP, TTL expiry triggers refetch, LRU eviction at 100 entries, stale-cache fallback on server down, cold-cache skip when server down, `user_email` propagation to query string.
- The 7 pre-existing filter tests continue to pass. Two of them (which reach the injection path) now use a `setUp` fixture that mocks `urllib.request.urlopen`.
- `/system-prompt` endpoint test made hermetic (no reliance on ambient env).
- New `docker_manager` env-injection matrix tests and `sub_agent` model-resolution tests covering the Claude Code gateway path.

### CI
- **Sandbox smoke tests in build pipeline** (PR #48): the build workflow now boots the sandbox image and verifies Chromium launches end-to-end before accepting the image.

### Documentation
- `.env.example` now documents `MCP_TOKENS_URL` (optional external skill-provider URL; empty default → graceful fallback to `DEFAULT_PUBLIC_SKILLS`).
- New `docs/claude-code-gateway.md` guide cross-linked from README and INSTALL covering gateway configuration.
- FILE_SERVER_URL: two-setting behaviour documented (PR #58) so operators understand the server-side vs. filter-side URLs.
- sub-agent docs: explicit-override precedence clarified; cutoff wording unified; presentation examples pruned; non-code delegation policy aligned across the system prompt.

### Dependencies
- `playwright` repinned to `1.57.0` (briefly bumped to `1.59.1` then reverted in PR #47 to stay aligned with the base image).
- `psutil` 7.1.0 → 7.2.2.
- `beautifulsoup4` 4.14.2 → 4.14.3.
- `reportlab` 4.4.4 → 4.4.10.

### Privacy / packaging
- `.planning/` gitignored on the public GitHub remote; pre-push hook enforces the rule.
- Internal-fork references scrubbed; `tests/test-no-corporate.sh` extended to catch regressions.
- MCP Registry: added project logo, fixed `server.json` schema, simplified manifest for publication as `io.github.Wide-Moat/open-computer-use`.

### Code removed
- Filter's hardcoded ~460-line prompt f-string.
- Filter's client-side URL substitution (`{file_base_url}` / `{archive_url}` / `{chat_id}` replacement).
- Filter's timestamp-based file-injection heuristic (handled natively by Open WebUI middleware).

## v0.8.12.6 (2026-04-04)

### Features
- **SINGLE_USER_MODE**: new env var for easy onboarding without `X-Chat-Id` header
  - Not set (default): lenient — uses shared container + warning in tool response and server logs
  - `true`: single-user — one container, no headers needed (recommended for Claude Desktop)
  - `false`: strict multi-user — `X-Chat-Id` required, error if missing
- **MCP Registry manifest** (`server.json`): published as `io.github.Wide-Moat/open-computer-use`
- **Dynamic config endpoints**: documented `/system-prompt`, `/skill-list`, `/mcp-info` in docs/MCP.md
- **System prompt reference**: new `docs/system-prompt.md` with prompt structure documentation

### Tests
- 13 unit tests for single-user mode (`tests/orchestrator/test_single_user_mode.py`)
- 6 Docker integration tests (`tests/test-single-user-mode.sh`)

## v0.8.12.5 (2026-04-04)

### License
- **License change**: core code migrated from MIT to Business Source License 1.1 (BSL 1.1)
  - Change License: Apache 2.0 (auto-converts after Change Date: 2029-04-04)
  - Additional Use Grant: free for all use except offering as a competing managed/hosted service
  - Attribution required: project name + link to repository
- Skills `describe-image` and `sub-agent` remain MIT; third-party skills unchanged
- Added SPDX license headers to all core source files
- Added NOTICE file documenting multi-license model
- Added LICENSE-MIT and LICENSE-APACHE alongside BSL LICENSE

## v0.8.12.4 (2026-04-02)

### Security
- **Pillow 11 → 12.1.1**: fixes PSD out-of-bounds write CVE; migrated `Image.LANCZOS` → `Image.Resampling.LANCZOS` for Pillow 12 API compatibility
- **urllib3 → 2.6.3**: decompression bomb + redirect bypass fix
- **cryptography → 46.0.6**: SECT curves subgroup attack fix
- **PyJWT → 2.12.1**: critical header extensions bypass fix
- **pdfminer.six → 20251230**: pickle deserialization RCE fix
- **pdfplumber → 0.11.9**: constraint resolution with pdfminer.six
- **python-multipart → 0.0.22** (orchestrator): CVE patch

### Tests
- 15 new unit tests for `view()` image processing path (`tests/orchestrator/test_view_image.py`)
  - Pillow 12 API guard: fails if deprecated `Image.LANCZOS` form is used
  - Structured content return format (`[text, image_url]`)
  - All 5 image extensions + case-insensitive matching
  - Container failure error handling
- 7 new version regression tests (`tests/test_requirements.py`)
  - Prevents accidental downgrade of CVE-patched dependencies

## v0.8.12.3 (2026-04-01)

### Security
- Fix 28 GitHub CodeQL security alerts: path traversal, XSS, URL redirect vulnerabilities
- Centralized input sanitization via `security.py` (sanitize_chat_id, safe_path)
- XSS prevention in file preview with same-origin checks
- SRI integrity for CDN resources
- 40+ security tests

### MCP Tools Best Practices
- **Output truncation**: bash_tool output capped at 30K chars (head+tail) to protect context window
- **Command semantics**: grep/find/diff exit code 1 is no longer treated as error (matches Claude Code behavior)
- **str_replace uniqueness**: errors when old_str matches multiple times, preventing accidental edits
- **view threshold**: increased from 16K to 30K for consistency with bash_tool
- **System prompt**: added tool usage tips (prefer view over cat, grep exit codes explained)
- 15 new unit tests for MCP tools

### Open WebUI Patches
- **fix_large_tool_results**: truncates large MCP tool results (>50K chars) to prevent context window exhaustion
  - Handles both Chat Completions and Responses API formats
  - Truncates current results in tool loop AND historical results from DB
  - Optional upload of full results via DOCKER_AI_UPLOAD_URL
  - Config: `TOOL_RESULT_MAX_CHARS` (default 50000), `TOOL_RESULT_PREVIEW_CHARS` (default 2000)
  - 10 new unit tests

## v1.0.0 - Initial Open Source Release (2026-03-30)

### Features
- **MCP Server**: Computer Use orchestrator with full MCP (Model Context Protocol) support
- **Docker Sandbox**: Isolated Ubuntu 24.04 containers with Python 3.12, Node.js 22, Java 21
- **CDP Browser**: Live browser viewer via Chrome DevTools Protocol proxy
- **Terminal**: Interactive terminal via ttyd + tmux + xterm.js
- **Claude Code**: Pre-installed Claude Code CLI with TTY support
- **Skills System**: 13 built-in public skills + 14 examples (pptx, docx, xlsx, pdf, sub-agent, playwright-cli, and more)
- **Open WebUI Integration**: Docker-compose stack with patched Open WebUI + PostgreSQL
- **Tools**: bash, str_replace, create_file, view, sub_agent
- **File Server**: Upload/download with archive support

### Included Tools
- Playwright (Chromium), LibreOffice, Tesseract OCR, FFmpeg, Pandoc
- ImageMagick, Graphviz, Mermaid CLI
- Python: docx, pptx, openpyxl, pypdf, Pillow, OpenCV, pandas, numpy
- Node.js: React, TypeScript, pdf-lib, pptxgenjs, sharp
