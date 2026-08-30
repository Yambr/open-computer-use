# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""
title: Computer Use Filter
author: Open Computer Use Contributors
version: 4.1.0
required_open_webui_version: 0.5.17
description: HTTP-fetches Computer Use system prompt from orchestrator, with LRU cache and stale-cache fallback. outlet() decorates assistant messages with a preview button and/or archive button based on PREVIEW_MODE and ARCHIVE_BUTTON Valves. The inline-iframe artifact is no longer emitted — the frontend fix_preview_url_detection patch promotes the preview URL into an artifact on its own.

This filter works in conjunction with Computer Use Tools (computer_use_tools.py).

FUNCTIONALITY:
- inlet(): When tool "ai_computer_use" is active and chat_id is present, fetches the
  fully-baked system prompt from the orchestrator's /system-prompt endpoint (server
  substitutes {file_base_url}, {archive_url}, {chat_id} and assembles <available_skills>)
  and injects it into the system message. Cache: 5-minute TTL, max 100 entries,
  O(1) LRU eviction. On fetch failure: serve stale cache if present; else skip injection.
  The server returns its public URL in the X-Public-Base-URL response header; inlet()
  caches it alongside the prompt so outlet() can decorate with browser-facing links.
- outlet(): Decorates assistant messages whose content contains either a file URL for
  the current chat_id OR a <details type="tool_calls"> block that references a browser
  tool (playwright, chromium, screenshot, start-browser). Decoration is driven by two
  Valves: PREVIEW_MODE ("button" | "off", default "button") and
  ARCHIVE_BUTTON ("on" | "off", default "on"). All decorations are idempotent (substring
  guarded) and scoped to the current chat_id. Archive button also requires a file URL.

CHANGELOG (v4.1.0) — BREAKING:
- Removed PREVIEW_MODE="artifact" / "both". outlet() no longer emits a fenced
  ```html <iframe src="..."> block. The frontend fix_preview_url_detection patch
  already promotes any /preview/ URL in message text into an inline artifact, so
  the extra html block was redundant and, worse, suppressed the patch (its guard
  `!htmlGroups.some(o=>o.html)` fails when the block is present, leaving the
  iframe rendered as a raw code fence in chat). Only "button" and "off" remain;
  "button" is the new default. Matches the internal prod behaviour (v3.8.0).

CHANGELOG (v4.0.0) — BREAKING:
- Removed FILE_SERVER_URL and SYSTEM_PROMPT_URL Valves. Replaced with a single
  ORCHESTRATOR_URL Valve (internal URL, default "http://computer-use-server:8081").
  The public URL is now owned by the server (PUBLIC_BASE_URL env) and delivered to
  the filter via the X-Public-Base-URL response header on /system-prompt, so the
  filter never needs to know the browser-facing URL.
- _fetch_system_prompt() signature changed: now returns tuple[public_url, prompt]
  instead of just prompt. outlet() reads the cached public_url when decorating.
- Valves seeded via Open WebUI admin UI or init.sh with the new ORCHESTRATOR_URL
  name; saved FILE_SERVER_URL / SYSTEM_PROMPT_URL values from earlier versions are
  ignored and the default is used instead — re-seed after upgrade.

CHANGELOG (v3.4.0):
- Removed legacy v3.2.0 boolean Valves (ENABLE_PREVIEW_ARTIFACT,
  ENABLE_PREVIEW_BUTTON, ENABLE_ARCHIVE_BUTTON) and their @model_validator bridge.

CHANGELOG (v3.3.0):
- Collapsed three boolean preview/archive Valves into two Literal Valves
  (PREVIEW_MODE, ARCHIVE_BUTTON).

CHANGELOG (v3.2.0):
- Added ENABLE_PREVIEW_ARTIFACT Valve — outlet() emits an inline iframe artifact.
- Added ENABLE_PREVIEW_BUTTON Valve — opt-in markdown button fallback.

CHANGELOG (v3.1.0):
- Removed hardcoded system prompt; server is now the single source of truth.
- HTTP fetch + OrderedDict LRU cache + stale-cache fallback.

CHANGELOG (v3.0.2):
- Previous version with hardcoded prompt; see git history for details.

    VALVES:
        ORCHESTRATOR_URL (str, default "http://computer-use-server:8081"):
            Internal URL of the Computer Use orchestrator — must be reachable
            from inside the Open WebUI container (server→server fetch for
            /system-prompt). Never appears in browser-facing URLs. The default
            works out of the box with the reference docker-compose stack (both
            services on the same Docker network, service DNS resolves the name).
            For production deploys, point this at the internal hostname / k8s
            service DNS of the orchestrator.
            The browser-facing URL for preview/archive links is owned by the
            server (PUBLIC_BASE_URL env) and returned via the X-Public-Base-URL
            response header on /system-prompt.
        INJECT_SYSTEM_PROMPT (bool, default True):
            If False, inlet() skips system-prompt injection entirely (useful when
            another filter owns the prompt).
        PREVIEW_MODE (Literal["button","off"], default "button"):
            Where the preview link appears on assistant messages.
            - "button": markdown [{PREVIEW_BUTTON_TEXT}]({public}/preview/{chat_id}).
              The fix_preview_url_detection frontend patch detects this URL in
              message text and auto-opens it as an inline artifact — no fenced
              html block needed. Works on both patched and stock Open WebUI
              (stock renders a clickable link; patched renders inline artifact).
            - "off": no preview link.
        ARCHIVE_BUTTON (Literal["on","off"], default "on"):
            Append a markdown [{ARCHIVE_BUTTON_TEXT}]({public}/files/{chat_id}/archive)
            link to assistant messages that contain files for the current chat_id.
        PREVIEW_BUTTON_TEXT (str, default "🖥️ Open preview"):
            Label for the preview-button markdown link.
        ARCHIVE_BUTTON_TEXT (str, default "📦 Download all files as archive"):
            Label for the archive-download markdown link.
        DOWNLOAD_BASE_URL (str, default ""):
            Browser-facing base for [[ocu-download:NAME]] links. Empty means the
            marker degrades to the bare filename as plain text rather than
            minting a link that cannot resolve. Set by init.sh alongside
            DOWNLOAD_SCOPE; the two are only useful together.
        DOWNLOAD_SCOPE (str, default ""):
            The {scope} path segment of a download link, and load-bearing rather
            than decoration: the route is /download/{scope}/{filename} and a
            one-segment link is a 404 (ADR-0035). Must equal the filesystem_id
            claim the pane's session carries, so it comes from the portal rather
            than from anything the model wrote. Empty degrades like the base.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Literal, Optional

from pydantic import BaseModel, Field


# All known Open WebUI template variables
# https://docs.openwebui.com/features/workspace/prompts/
OPENWEBUI_TEMPLATE_VARS = [
    "CURRENT_DATE", "CURRENT_DATETIME", "CURRENT_TIME",
    "CURRENT_TIMEZONE", "CURRENT_WEEKDAY",
    "USER_NAME", "USER_LANGUAGE", "USER_LOCATION",
    "CLIPBOARD",
]

# Pattern: {{ VAR }} or {{VAR}} (with/without spaces, Jinja2-style)
TEMPLATE_PATTERN = r"^.*\{\{\s*(?:" + "|".join(OPENWEBUI_TEMPLATE_VARS) + r")\s*\}\}.*$"

# File-download marker the model emits per the <sharing_files> prompt block
# (#191, ADR-0034): [[ocu-download:report.docx]]. outlet() rewrites each into a
# markdown download link. The capture excludes "]" (so a markdown label built
# from it cannot be broken) and newlines (a marker is a single-line token), and
# is length-bounded to a filename. The quantifier is {0,255} so an EMPTY marker
# [[ocu-download:]] still matches and is caught by the fail-closed validation
# in _replace_marker (empty name -> plain text) rather than leaking the literal
# sentinel to the user; {1,255} would let the empty marker slip through unmatched.
_DOWNLOAD_MARKER_RE = re.compile(r"\[\[ocu-download:([^\]\n]{0,255})\]\]")

# Cache TTL and size (module-level so tests can patch them)
_PROMPT_TTL_SECONDS = 300
_PROMPT_CACHE_MAX_SIZE = 100
# A chat's storage scope is fixed for the life of its session, so this TTL only
# bounds how long a reaped-and-recreated session keeps serving the old handle.
_SCOPE_TTL_SECONDS = 300
_SCOPE_CACHE_MAX_SIZE = 100


def _find_block_start(content: str, pos: int) -> int:
    """
    Find the start of the text block containing position `pos`.

    A block is delimited by an empty line (double newline) or the start of content.
    Used to inject the Computer Use system prompt BEFORE any Open WebUI template block.
    """
    boundary = content.rfind("\n\n", 0, pos)
    return boundary + 2 if boundary != -1 else 0


# Open WebUI renders tool invocations into assistant content as
# <details type="tool_calls" ... name="X" arguments="Y" result="Z" ...>.
# The /api/chat/completed endpoint strips raw `tool_calls` / role="tool"
# (Chat.svelte sends only {id, role, content, info, timestamp, usage, sources}),
# so content-scan is the only reliable detection path in outlet() for sessions
# that exercised browser tools without producing file URLs.
_TOOL_CALL_DETAILS_RE = re.compile(
    r'<details\s+[^>]*type="tool_calls"[^>]*>',
    re.IGNORECASE,
)
_NAME_ATTR_RE = re.compile(r'\bname="([^"]*)"')
_ARGS_ATTR_RE = re.compile(r'\barguments="([^"]*)"')
_BROWSER_TOOL_KEYWORDS = ("playwright", "start-browser", "chromium", "screenshot")


def _extract_tool_calls_from_content(content: str) -> list[tuple[str, str]]:
    """Return [(name, arguments_raw), ...] from <details type="tool_calls"> tags.

    Attribute values are html-escaped as delivered by Open WebUI; substring
    keyword matching is robust to that — no need to unescape for detection.
    """
    if not content:
        return []
    out: list[tuple[str, str]] = []
    for m in _TOOL_CALL_DETAILS_RE.finditer(content):
        tag = m.group(0)
        n = _NAME_ATTR_RE.search(tag)
        a = _ARGS_ATTR_RE.search(tag)
        out.append((n.group(1) if n else "", a.group(1) if a else ""))
    return out


def _content_has_browser_tool(content: str) -> bool:
    """True when the assistant message embeds a tool_calls details block that
    references a browser tool (playwright, chromium, screenshot, start-browser).

    Scoped to <details type="tool_calls"> tags — free text in user/assistant
    messages is never scanned, so keyword mentions ("how does playwright work?")
    do not trigger a false positive.
    """
    for name, args in _extract_tool_calls_from_content(content):
        blob = (name + " " + args).lower()
        if any(kw in blob for kw in _BROWSER_TOOL_KEYWORDS):
            return True
    return False


class Filter:
    class Valves(BaseModel):
        ORCHESTRATOR_URL: str = Field(
            default="http://computer-use-server:8081",
            description="Internal URL of the Computer Use orchestrator. Must be reachable from inside the Open WebUI container for server→server /system-prompt fetch. NOT browser-facing — the public URL is owned by the server (PUBLIC_BASE_URL env) and returned via the X-Public-Base-URL response header. Trailing slash is tolerated.",
        )
        INJECT_SYSTEM_PROMPT: bool = Field(
            default=True,
            description="Inject Computer Use system prompt when tools are active. Turn off only if another filter owns the prompt.",
        )
        PREVIEW_MODE: Literal["button", "off"] = Field(
            default="button",
            description="Where the preview link appears on assistant messages. button=markdown link (the fix_preview_url_detection frontend patch turns it into an inline artifact on patched builds; stock Open WebUI shows it as a clickable link). off=no preview link.",
        )
        ARCHIVE_BUTTON: Literal["on", "off"] = Field(
            default="on",
            description="Append a 'Download all files as archive' link to assistant messages that contain files.",
        )
        PREVIEW_BUTTON_TEXT: str = Field(
            default="🖥️ Open preview",
            description="Text for the preview-button markdown link (used when PREVIEW_MODE is 'button').",
        )
        ARCHIVE_BUTTON_TEXT: str = Field(
            default="📦 Download all files as archive",
            description="Text for the archive-download button (when ARCHIVE_BUTTON is on).",
        )
        DOWNLOAD_BASE_URL: str = Field(
            default="",
            description=(
                "Browser-facing base of the File Pane origin that serves "
                "/download/{scope}/{filename} (#191, ADR-0034, shape per "
                "ADR-0035). outlet() rewrites the model's [[ocu-download:NAME]] "
                "markers into a markdown link under this base; the model never "
                "authors the base. Trailing slash tolerated. Empty -> markers "
                "degrade to the bare filename as plain text (broken links are "
                "worse than no links)."
            ),
        )
        DOWNLOAD_SCOPE: str = Field(
            default="",
            description=(
                "The storage scope handle that becomes the {scope} path segment "
                "of a download link. It must equal the filesystem_id claim the "
                "pane's own session carries -- the download route rejects a "
                "mismatch with 401, and the value the pane holds is the one the "
                "portal minted into the embed token, not one this filter can "
                "derive. init.sh seeds it from OCU_FILESYSTEM_ID, the same base "
                "the tool sends on X-OCU-Filesystem-Id. Empty -> markers degrade "
                "to the bare filename, because a one-segment path is not a route "
                "the pane serves. Under per-chat storage isolation this is the "
                "FALLBACK only: one static value cannot equal the filesystem_id "
                "of more than one chat's session, so RESOLVE_SCOPE_URL below "
                "supplies the per-chat value and this is used when the "
                "deployment derives no per-chat scope."
            ),
        )
        RESOLVE_SCOPE_URL: str = Field(
            default="",
            description=(
                "MCP gateway ingress used to learn which storage scope a chat is "
                "bound to, via its resolve_scope tool. Needed whenever the "
                "deployment derives a per-chat scope: the pane's session then "
                "carries filesystem_id <base>-<hex> per chat, so a link built "
                "from the static DOWNLOAD_SCOPE points at the base tree -- it "
                "renders a download page and returns no bytes. Empty -> no "
                "resolution is attempted and DOWNLOAD_SCOPE is used as before."
            ),
        )
        RESOLVE_SCOPE_BEARER: str = Field(
            default="",
            description=(
                "Credential for RESOLVE_SCOPE_URL. Give this filter a key of its "
                "own, confined gateway-side to resolve_scope: learning a scope is "
                "all it needs, and an unconfined key would let a chat-rendering "
                "filter execute tools. It must sit in the same tenant as the "
                "caller key the tool uses -- the gateway derives its session hint "
                "from the resolved principal's tenant, so a foreign-tenant key "
                "resolves a different session and returns a scope matching no "
                "guest."
            ),
        )

    def __init__(self):
        self.valves = self.Valves()
        # Per-(chat, user) LRU cache: (chat_id, user_email) -> (fetched_at, (public_url, prompt))
        # - Keyed by user identity because the server bakes a user-specific <available_skills>
        #   block — sharing across users would leak skills and break correctness.
        # - Value is a tuple so outlet() can read the public URL (from the server's
        #   X-Public-Base-URL response header) without its own URL Valve.
        self._prompt_cache: OrderedDict[
            tuple[str, str], tuple[float, tuple[str, str]]
        ] = OrderedDict()
        # Per-chat scope cache: chat_id -> (fetched_at, scope). A chat's scope is
        # fixed for the life of its session, so this is a hot-path saver, not a
        # correctness device. Only SUCCESSFUL resolutions are stored: caching a
        # failure would freeze a chat's links into the degraded state for the
        # whole TTL after one transient gateway blip.
        self._scope_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def _fetch_system_prompt(
        self, chat_id: str, user_email: str = ""
    ) -> Optional[tuple[str, str]]:
        """
        Fetch system prompt from the orchestrator with per-(chat, user) caching.

        Returns (public_url, prompt) on success, or the cached value on stale-cache
        fallback if the fetch failed but a previous entry exists. Returns None when
        the cache is cold AND the server is unreachable — caller must skip injection.

        The public_url comes from the server's X-Public-Base-URL response header
        (PUBLIC_BASE_URL env on the server). outlet() uses it to build browser-facing
        preview/archive links. Fallback: if the header is absent (older server), the
        ORCHESTRATOR_URL Valve is reused — only correct for bare-metal/co-located
        deploys where internal == public.
        """
        now = time.time()
        cache_key = (chat_id, user_email)
        cached = self._prompt_cache.get(cache_key)

        # Cache hit within TTL
        if cached and (now - cached[0]) < _PROMPT_TTL_SECONDS:
            self._prompt_cache.move_to_end(cache_key)
            return cached[1]

        # Build URL (resolved at request time so Valves updates are honoured)
        orchestrator = self.valves.ORCHESTRATOR_URL.rstrip("/")
        base_url = orchestrator + "/system-prompt"

        # Only http(s) is a valid orchestrator transport. Reject file://, ftp://,
        # data://, etc. — otherwise a misconfigured Valve could read arbitrary
        # local files through urlopen (ruff S310).
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            print(
                f"[ComputerUseFilter] Unsupported orchestrator URL scheme: "
                f"{parsed.scheme!r} (expected http/https)"
            )
            return cached[1] if cached else None

        params = {}
        if chat_id:
            params["chat_id"] = chat_id
        if user_email:
            params["user_email"] = user_email
        url = base_url + ("?" + urllib.parse.urlencode(params) if params else "")

        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "text/plain")
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — scheme validated above
                prompt = resp.read().decode("utf-8")
                # X-Public-Base-URL header tells outlet() which URL to put in
                # browser-facing iframe/archive links. When the header is
                # missing (older server), fall back to the internal Valve —
                # this is only correct when ORCHESTRATOR_URL == public URL
                # (bare-metal co-located deploy).
                public_url = (
                    resp.headers.get("X-Public-Base-URL") or orchestrator
                )
                public_url = public_url.rstrip("/")

            entry = (public_url, prompt)
            # Cache the ready-to-use (public_url, prompt) pair
            self._prompt_cache[cache_key] = (now, entry)
            self._prompt_cache.move_to_end(cache_key)

            # Evict oldest entry when over capacity (O(1) with OrderedDict)
            while len(self._prompt_cache) > _PROMPT_CACHE_MAX_SIZE:
                self._prompt_cache.popitem(last=False)

            return entry

        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as e:
            # Narrow to real transport/decoding failures. Broader Exception
            # would swallow configuration bugs (e.g. attribute errors on the
            # Valves model) behind the stale-cache fallback and make them
            # invisible (ruff BLE001).
            print(f"[ComputerUseFilter] Failed to fetch system prompt: {e}")
            # Stale-cache fallback (any age) when available
            if cached:
                return cached[1]
            # Cold cache + server down -> caller skips injection
            return None

    def _resolve_chat_scope(self, chat_id: str) -> tuple[Optional[str], bool]:
        """
        Learn the storage scope bound to chat_id from the session's owner.

        Returns (scope, ok). `ok` is False ONLY when resolution was attempted and
        failed; the caller degrades the marker to plain text in that case, because
        a link built from a scope we could not confirm is a link that renders a
        download page and returns no bytes -- the worst of the three outcomes,
        since it looks like it worked.

        (None, True) means "no per-chat scope in this deployment": the gateway
        answers with an empty effective_scope when the deployment derives none, and
        then the static DOWNLOAD_SCOPE valve is the correct answer. Distinguishing
        that from a failure is the whole point of the second return value.

        The scope is never derived locally. A filter-local derivation would use a
        different pre-image than the one the guest's session was minted with and
        bind a third value matching neither the pane nor the guest.
        """
        endpoint = self.valves.RESOLVE_SCOPE_URL.strip()
        if not endpoint or not chat_id:
            return None, True  # not configured / nothing to resolve -> use the valve

        now = time.time()
        cached = self._scope_cache.get(chat_id)
        if cached and now - cached[0] < _SCOPE_TTL_SECONDS:
            self._scope_cache.move_to_end(chat_id)
            return cached[1], True

        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in ("http", "https"):
            print(
                f"[ComputerUseFilter] Unsupported resolve-scope URL scheme: "
                f"{parsed.scheme!r} (expected http/https)"
            )
            return None, False

        bearer = self.valves.RESOLVE_SCOPE_BEARER.strip()
        if not bearer:
            print(
                "[ComputerUseFilter] RESOLVE_SCOPE_URL is set but "
                "RESOLVE_SCOPE_BEARER is empty; cannot resolve a chat's scope"
            )
            return None, False

        payload = (
            b'{"jsonrpc":"2.0","id":1,"method":"tools/call",'
            b'"params":{"name":"resolve_scope","arguments":{}}}'
        )
        try:
            req = urllib.request.Request(endpoint, data=payload, method="POST")
            req.add_header("Authorization", f"Bearer {bearer}")
            req.add_header("Content-Type", "application/json")
            req.add_header("MCP-Protocol-Version", "2025-06-18")
            # The chat travels on the header the gateway reads as a session HINT,
            # never as identity: it is mixed with the resolved principal's tenant.
            req.add_header("X-Chat-Id", chat_id)
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — scheme validated above
                envelope = json.loads(resp.read().decode("utf-8"))
        except (
            urllib.error.URLError,
            TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as e:
            # Narrow, like _fetch_system_prompt: a broader Exception would hide
            # configuration bugs behind the degraded path.
            print(f"[ComputerUseFilter] Failed to resolve scope for chat: {e}")
            return None, False

        if envelope.get("error"):
            print(
                f"[ComputerUseFilter] Gateway refused resolve_scope: "
                f"{envelope['error'].get('message')!r}"
            )
            return None, False

        result = envelope.get("result") or {}
        if result.get("isError"):
            print("[ComputerUseFilter] resolve_scope returned an error result")
            return None, False
        blocks = result.get("content") or []
        if not blocks:
            print("[ComputerUseFilter] resolve_scope result carried no content")
            return None, False
        try:
            scope = (json.loads(blocks[0].get("text") or "{}") or {}).get(
                "effective_scope"
            )
        except json.JSONDecodeError as e:
            print(f"[ComputerUseFilter] resolve_scope content did not parse: {e}")
            return None, False

        scope = (scope or "").strip().strip("/")
        if not scope:
            # The deployment derives no per-chat scope. The base valve is correct.
            return None, True

        self._scope_cache[chat_id] = (now, scope)
        self._scope_cache.move_to_end(chat_id)
        while len(self._scope_cache) > _SCOPE_CACHE_MAX_SIZE:
            self._scope_cache.popitem(last=False)
        return scope, True

    def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
    ) -> dict:
        """Inject Computer Use system prompt BEFORE LLM processing."""
        if not self.valves.INJECT_SYSTEM_PROMPT:
            return body

        tool_ids = body.get("tool_ids", [])
        if "ai_computer_use" not in tool_ids:
            return body

        chat_id = __metadata__.get("chat_id") if __metadata__ else None
        if not chat_id:
            return body

        user_email = __user__.get("email", "") if __user__ else ""

        fetched = self._fetch_system_prompt(chat_id, user_email)
        if not fetched:
            # Cold cache + server down -> skip injection (same no-op path as missing chat_id)
            return body
        _public_url, system_prompt = fetched

        messages = body.get("messages", [])
        if not messages:
            return body

        # Locate existing system message
        system_msg_idx = None
        for idx, msg in enumerate(messages):
            if msg.get("role") == "system":
                system_msg_idx = idx
                break

        if system_msg_idx is not None:
            existing_content = messages[system_msg_idx].get("content", "")
            # Some Open WebUI flows deliver structured content (e.g. a list of
            # multimodal parts) instead of a plain string. re.search would
            # crash in that case — skip template detection and fall through to
            # the append branch, which handles arbitrary existing_content via
            # string concatenation (str() coercion there is safe for the
            # downstream LLM which only reads strings anyway).
            if isinstance(existing_content, str):
                match = re.search(TEMPLATE_PATTERN, existing_content, re.MULTILINE)
            else:
                match = None
            if match:
                # Inject BEFORE the block containing the template variable
                block_start = _find_block_start(existing_content, match.start())
                messages[system_msg_idx]["content"] = (
                    existing_content[:block_start].rstrip()
                    + "\n\n"
                    + system_prompt
                    + "\n\n"
                    + existing_content[block_start:]
                )
            else:
                # No template vars (or non-string content) -> append as plain string.
                # When existing_content is a list of multimodal parts, coerce to
                # str() first so the LLM still sees the Computer Use prompt; the
                # original structured content is preserved via the repr.
                if isinstance(existing_content, str):
                    messages[system_msg_idx]["content"] = existing_content + "\n\n" + system_prompt
                else:
                    messages[system_msg_idx]["content"] = str(existing_content) + "\n\n" + system_prompt
        else:
            messages.insert(0, {"role": "system", "content": system_prompt})

        body["messages"] = messages
        return body

    def outlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
    ) -> dict:
        """Rewrite [[ocu-download:NAME]] markers into download links (#191, ADR-0034).

        The model, per the <sharing_files> system-prompt block, emits a marker
        [[ocu-download:report.docx]] naming a file it saved. This turns each valid
        marker into a markdown link to
        DOWNLOAD_BASE_URL/download/{scope}/{urlencoded-name} — a top-level
        first-party link that opens under the user's existing pane session (the
        /download route authorizes on the same attested cookie the File Pane
        established). The URL carries a SELECTOR (filename) and zero authority;
        the model contributes only the name, this filter contributes the base and
        the scope (a model-authored base would be a prompt-injection vector).

        The {scope} segment is load-bearing, not decoration: the route is
        /download/{scope}/{filename} and its parser returns null for anything
        else, the retired one-segment form included (ADR-0035). A link without it
        is a 404, which is how this filter shipped -- a marker the model emitted
        correctly, rewritten into a link that could never resolve. The value must
        equal the filesystem_id claim on the pane's session, so it comes from the
        DOWNLOAD_SCOPE valve (seeded from the same OCU_FILESYSTEM_ID the portal
        mints into the embed token) and never from anything the model wrote.

        Security (Fable-ruled): the marker is the same decision as
        _content_has_browser_tool — a defined sentinel, never a scan of free prose,
        so a filename mentioned in passing does NOT mint a link. Per-capture
        validation is fail-closed (a traversal/separator/empty name drops the
        marker to plain text, no link). urllib.parse.quote(safe="") encodes spaces
        AND parens so the URL cannot break out of the markdown link syntax.

        Invariants:
        1. Only role=="assistant" messages are touched (a user-authored marker is
           left intact — the mint is scoped to assistant output).
        2. Non-string content is skipped.
        3. The base is outlet-owned; the model never authors it.
        4. Idempotent: the marker is consumed on the first pass, so a re-render is
           the identity transform.
        5. Base-unavailable OR scope-unavailable (empty valve) -> the marker
           degrades to the bare filename as plain text. Both are the same
           judgement: a link missing either part cannot resolve, and a broken
           link is worse than no link.
        """
        base = self.valves.DOWNLOAD_BASE_URL.rstrip("/")
        # The scope must equal the filesystem_id of THIS chat's pane session.
        # Under per-chat isolation that value differs per chat, so ask the
        # session's owner; the static valve is the answer only where the
        # deployment derives no per-chat scope. A resolution that was attempted
        # and FAILED yields no link at all: a link carrying an unconfirmed scope
        # renders a download page and returns no bytes, which reads as success.
        chat_id = __metadata__.get("chat_id") if __metadata__ else None
        resolved, resolve_ok = self._resolve_chat_scope(chat_id or "")
        if not resolve_ok:
            scope = ""
        else:
            scope = resolved or self.valves.DOWNLOAD_SCOPE.strip().strip("/")

        def _replace_marker(match: "re.Match[str]") -> str:
            name = match.group(1).strip()
            # Fail-closed basename validation: no separators, traversal, or empty.
            if (
                not name
                or "/" in name
                or "\\" in name
                or "\x00" in name
                or name in (".", "..")
            ):
                return name  # drop the marker to plain text, no link
            if not base or not scope:
                return name  # incomplete link -> bare filename, never a 404
            href = (
                base
                + "/download/"
                + urllib.parse.quote(scope, safe="")
                + "/"
                + urllib.parse.quote(name, safe="")
            )
            return f"[{name}]({href})"

        for message in body.get("messages", []):
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not content or not isinstance(content, str):
                continue
            if "[[ocu-download:" not in content:
                continue
            message["content"] = _DOWNLOAD_MARKER_RE.sub(_replace_marker, content)

        return body
