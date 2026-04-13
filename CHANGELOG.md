# Changelog

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
- MCP Registry: added project logo, fixed `server.json` schema, simplified manifest for publication as `io.github.yambr/open-computer-use`.

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
- **MCP Registry manifest** (`server.json`): published as `io.github.yambr/open-computer-use`
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
