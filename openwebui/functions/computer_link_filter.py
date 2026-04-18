# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
title: Computer Use Filter
author: Open Computer Use Contributors
version: 3.3.0
required_open_webui_version: 0.5.17
description: HTTP-fetches Computer Use system prompt from orchestrator, with LRU cache and stale-cache fallback. outlet() decorates assistant messages with a preview iframe / preview button / archive button based on PREVIEW_MODE and ARCHIVE_BUTTON Valves.

This filter works in conjunction with Computer Use Tools (computer_use_tools.py).

FUNCTIONALITY:
- inlet(): When tool "ai_computer_use" is active and chat_id is present, fetches the
  fully-baked system prompt from the orchestrator's /system-prompt endpoint (server
  substitutes {file_base_url}, {archive_url}, {chat_id} and assembles <available_skills>)
  and injects it into the system message. Cache: 5-minute TTL, max 100 entries,
  O(1) LRU eviction. On fetch failure: serve stale cache if present; else skip injection.
- outlet(): Decorates assistant messages whose content contains either a file URL for
  the current chat_id OR a <details type="tool_calls"> block that references a browser
  tool (playwright, chromium, screenshot, start-browser). Decoration is driven by two
  Valves: PREVIEW_MODE ("artifact" | "button" | "both" | "off", default "artifact") and
  ARCHIVE_BUTTON ("on" | "off", default "on"). All decorations are idempotent (substring
  guarded) and scoped to the current chat_id. Archive button also requires a file URL.

CHANGELOG (v3.3.0):
- Collapsed three boolean preview/archive Valves (ENABLE_PREVIEW_ARTIFACT,
  ENABLE_PREVIEW_BUTTON, ENABLE_ARCHIVE_BUTTON) into two Literal Valves
  (PREVIEW_MODE, ARCHIVE_BUTTON). Fewer, clearer knobs.
- Backward compatible: legacy fields are still read from existing deployments and
  migrated transparently by a @model_validator. Users who saved v3.2.0 settings
  keep them on upgrade. Legacy fields remain visible in the Valves UI labeled
  DEPRECATED until filter v4.0 / v0.9.0.
- outlet() rewritten to read PREVIEW_MODE + ARCHIVE_BUTTON only. No behavioural
  regression — the same four user-facing states (artifact / button / both / off)
  remain reachable.

CHANGELOG (v3.2.0):
- Added ENABLE_PREVIEW_ARTIFACT Valve (default True) — outlet() now emits an inline
  <iframe src="{base}/preview/{chat_id}"> wrapped in a fenced ```html block when the
  assistant message contains a file URL for the current chat_id. Intended UX for
  deployments that render HTML artifacts.
- Added ENABLE_PREVIEW_BUTTON Valve (default False) — opt-in markdown link fallback
  for stock Open WebUI installations that do not render artifact blocks.
- Added PREVIEW_BUTTON_TEXT Valve (default "🖥️ Open preview") — button label for
  the opt-in preview link.
- outlet() correctness invariants preserved: role=="assistant" guard,
  isinstance(content, str) guard, chat_id-scoped file_url_pattern,
  FILE_SERVER_URL.rstrip("/") guard against //preview/, substring-based idempotency.
- Archive button behaviour unchanged; preview and archive links share the
  single-blank-line separator style.

CHANGELOG (v3.1.0):
- Removed hardcoded ~460-line system prompt f-string; server is now the single source of truth.
- HTTP fetch + OrderedDict LRU cache + stale-cache fallback (ported from internal fork v3.8.0).
- Added SYSTEM_PROMPT_URL Valve (optional override); falls back to FILE_SERVER_URL/system-prompt.
- Removed client-side URL substitution — server does it.
- Dropped unused __files__ parameter from inlet().

CHANGELOG (v3.0.2):
- Previous version with hardcoded prompt; see git history for details.

    VALVES:
        FILE_SERVER_URL (str, default "http://localhost:8081"):
            Orchestrator base URL. The filter derives /system-prompt,
            /files/{chat_id}/…, /files/{chat_id}/archive, and /preview/{chat_id}
            from this. Trailing slash is tolerated (stripped internally). Must
            match the server-side FILE_SERVER_URL env var — see
            docs/openwebui-filter.md#two-file_server_url-settings--they-must-match.
        SYSTEM_PROMPT_URL (str, default ""):
            Advanced: override URL for the /system-prompt endpoint. Empty means
            derive from FILE_SERVER_URL. Non-http(s) schemes are rejected.
        INJECT_SYSTEM_PROMPT (bool, default True):
            If False, inlet() skips system-prompt injection entirely (useful when
            another filter owns the prompt).
        PREVIEW_MODE (Literal["artifact","button","both","off"], default "artifact"):
            Where the preview link appears on assistant messages.
            - "artifact": inline fenced ```html <iframe src="{base}/preview/{chat_id}">.
              Default. Requires an Open WebUI build that renders HTML artifacts
              (e.g. our docker-compose.webui.yml ships the fix_artifacts_auto_show
              patch pre-applied).
            - "button": markdown [{PREVIEW_BUTTON_TEXT}]({base}/preview/{chat_id}).
              Escape hatch for stock Open WebUI where artifact rendering is off.
            - "both": both of the above.
            - "off":  neither.
        ARCHIVE_BUTTON (Literal["on","off"], default "on"):
            Append a markdown [{ARCHIVE_BUTTON_TEXT}]({base}/files/{chat_id}/archive)
            link to assistant messages that contain files for the current chat_id.
        PREVIEW_BUTTON_TEXT (str, default "🖥️ Open preview"):
            Label for the preview-button markdown link (only used when PREVIEW_MODE
            is "button" or "both").
        ARCHIVE_BUTTON_TEXT (str, default "📦 Download all files as archive"):
            Label for the archive-download markdown link (only used when
            ARCHIVE_BUTTON is "on").

    DEPRECATED VALVES (v3.3.0 — read-only, migrated automatically):
        ENABLE_PREVIEW_ARTIFACT (Optional[bool]):
            Replaced by PREVIEW_MODE. Users on v3.2.0 who had this set keep their
            preference after upgrade (mapped to PREVIEW_MODE). Will be removed in
            filter v4.0 / v0.9.0.
        ENABLE_PREVIEW_BUTTON (Optional[bool]):
            Replaced by PREVIEW_MODE. See above.
        ENABLE_ARCHIVE_BUTTON (Optional[bool]):
            Replaced by ARCHIVE_BUTTON. See above.
"""

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


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

# Cache TTL and size (module-level so tests can patch them)
_PROMPT_TTL_SECONDS = 300
_PROMPT_CACHE_MAX_SIZE = 100


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
        FILE_SERVER_URL: str = Field(
            default="http://localhost:8081",
            description="Orchestrator base URL (without trailing slash). Must be reachable from your browser AND match the server-side FILE_SERVER_URL env var — see docs/openwebui-filter.md#two-file_server_url-settings--they-must-match.",
        )
        SYSTEM_PROMPT_URL: str = Field(
            default="",
            description="Advanced: override URL for /system-prompt endpoint (empty = derive from FILE_SERVER_URL). Leave blank unless you run the system-prompt endpoint on a different host.",
        )
        INJECT_SYSTEM_PROMPT: bool = Field(
            default=True,
            description="Inject Computer Use system prompt when tools are active. Turn off only if another filter owns the prompt.",
        )
        PREVIEW_MODE: Literal["artifact", "button", "both", "off"] = Field(
            default="artifact",
            description="Where the preview link appears on assistant messages. artifact=inline iframe (default, requires artifact-rendering Open WebUI), button=markdown link (works on stock Open WebUI), both=both, off=neither.",
        )
        ARCHIVE_BUTTON: Literal["on", "off"] = Field(
            default="on",
            description="Append a 'Download all files as archive' link to assistant messages that contain files.",
        )
        PREVIEW_BUTTON_TEXT: str = Field(
            default="🖥️ Open preview",
            description="Text for the preview-button markdown link (when PREVIEW_MODE is button or both).",
        )
        ARCHIVE_BUTTON_TEXT: str = Field(
            default="📦 Download all files as archive",
            description="Text for the archive-download button (when ARCHIVE_BUTTON is on).",
        )

        # Legacy v3.2.0 fields — kept for backward compatibility so existing
        # deployments do not lose their settings on upgrade. The _migrate_legacy
        # validator maps them onto the new fields. These will be removed in
        # filter v4.0 / open-computer-use v0.9.0.
        ENABLE_PREVIEW_ARTIFACT: Optional[bool] = Field(
            default=None,
            description="DEPRECATED (v3.3.0) — use PREVIEW_MODE. Value is migrated automatically on first load.",
        )
        ENABLE_PREVIEW_BUTTON: Optional[bool] = Field(
            default=None,
            description="DEPRECATED (v3.3.0) — use PREVIEW_MODE. Value is migrated automatically on first load.",
        )
        ENABLE_ARCHIVE_BUTTON: Optional[bool] = Field(
            default=None,
            description="DEPRECATED (v3.3.0) — use ARCHIVE_BUTTON. Value is migrated automatically on first load.",
        )

        @model_validator(mode="after")
        def _migrate_legacy(self):
            """Map v3.2.0 boolean Valves onto v3.3.0 Literal Valves.

            Only fires when the user has NOT explicitly set the new field —
            prevents a stale legacy value (e.g. a cleared but still-persisted
            ENABLE_PREVIEW_ARTIFACT=True) from overwriting a deliberate
            PREVIEW_MODE choice made after the upgrade.
            """
            touched = self.model_fields_set

            if "PREVIEW_MODE" not in touched and (
                self.ENABLE_PREVIEW_ARTIFACT is not None
                or self.ENABLE_PREVIEW_BUTTON is not None
            ):
                a = self.ENABLE_PREVIEW_ARTIFACT
                b = self.ENABLE_PREVIEW_BUTTON
                if a and b:
                    self.PREVIEW_MODE = "both"
                elif a:
                    self.PREVIEW_MODE = "artifact"
                elif b:
                    self.PREVIEW_MODE = "button"
                else:
                    self.PREVIEW_MODE = "off"

            if "ARCHIVE_BUTTON" not in touched and self.ENABLE_ARCHIVE_BUTTON is not None:
                self.ARCHIVE_BUTTON = "on" if self.ENABLE_ARCHIVE_BUTTON else "off"

            return self

    def __init__(self):
        self.valves = self.Valves()
        # Per-(chat, user) LRU cache: (chat_id, user_email) -> (monotonic_fetched_at, prompt_text)
        # Keyed by user identity too because the server bakes a user-specific <available_skills>
        # block when user_email is supplied — sharing across users would leak skills and
        # break correctness when two users hit the same chat_id.
        self._prompt_cache: OrderedDict[tuple[str, str], tuple[float, str]] = OrderedDict()

    def _fetch_system_prompt(self, chat_id: str, user_email: str = "") -> Optional[str]:
        """
        Fetch system prompt from the orchestrator with per-(chat, user) caching.

        Returns the prompt string on success, or on stale-cache fallback if the fetch
        failed but a previous entry exists. Returns None when the cache is cold AND
        the server is unreachable — caller must skip injection in that case.
        """
        now = time.time()
        cache_key = (chat_id, user_email)
        cached = self._prompt_cache.get(cache_key)

        # Cache hit within TTL
        if cached and (now - cached[0]) < _PROMPT_TTL_SECONDS:
            self._prompt_cache.move_to_end(cache_key)
            return cached[1]

        # Build URL (resolved at request time so Valves updates are honoured)
        base_url = self.valves.SYSTEM_PROMPT_URL or (
            self.valves.FILE_SERVER_URL.rstrip("/") + "/system-prompt"
        )

        # Only http(s) is a valid orchestrator transport. Reject file://, ftp://,
        # data://, etc. — otherwise a misconfigured Valve could read arbitrary
        # local files through urlopen (ruff S310).
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            print(
                f"[ComputerUseFilter] Unsupported system prompt URL scheme: "
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

            # Cache the ready-to-use prompt (server baked everything)
            self._prompt_cache[cache_key] = (now, prompt)
            self._prompt_cache.move_to_end(cache_key)

            # Evict oldest entry when over capacity (O(1) with OrderedDict)
            while len(self._prompt_cache) > _PROMPT_CACHE_MAX_SIZE:
                self._prompt_cache.popitem(last=False)

            return prompt

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

        system_prompt = self._fetch_system_prompt(chat_id, user_email)
        if not system_prompt:
            # Cold cache + server down -> skip injection (same no-op path as missing chat_id)
            return body

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
        """Append preview iframe artifact, preview button, and/or archive button to assistant messages with file links.

        - PREVIEW_MODE="artifact" (default): inline ```html <iframe src="…/preview/{chat_id}"> artifact.
        - PREVIEW_MODE="button":   markdown link to the preview page — escape hatch for stock Open WebUI.
        - PREVIEW_MODE="both":     both of the above.
        - PREVIEW_MODE="off":      neither.
        - ARCHIVE_BUTTON="on" (default): markdown link to the archive endpoint (only when files exist).

        Invariants (preserved from v3.1.0):
        1. Only role=="assistant" messages are touched.
        2. Non-string content is skipped.
        3. file_url_pattern is scoped to the current chat_id (no cross-chat decoration).
        4. FILE_SERVER_URL is rstripped before URL construction (no //preview/ or //files/).
        5. Substring-based idempotency — repeated outlet() calls do not duplicate.
        """
        mode = self.valves.PREVIEW_MODE
        wants_artifact = mode in ("artifact", "both")
        wants_button = mode in ("button", "both")
        wants_archive = self.valves.ARCHIVE_BUTTON == "on"

        if not (wants_artifact or wants_button or wants_archive):
            return body

        chat_id = __metadata__.get("chat_id") if __metadata__ else None
        if not chat_id:
            return body

        base = self.valves.FILE_SERVER_URL.rstrip("/")
        file_url_pattern = re.escape(base) + r"/files/" + re.escape(chat_id) + r"/[^\s\)]+"
        preview_url = f"{base}/preview/{chat_id}"
        archive_url = f"{base}/files/{chat_id}/archive"

        for message in body.get("messages", []):
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not content or not isinstance(content, str):
                continue

            # Two independent triggers:
            # 1. A file URL scoped to the current chat_id — legacy v3.2.0 path.
            # 2. A <details type="tool_calls"> block that references a browser
            #    tool — covers sessions that exercised playwright/chromium
            #    without producing a downloadable file (e.g. pure navigation).
            has_file_link = bool(re.search(file_url_pattern, content))
            has_browser_tool = _content_has_browser_tool(content)
            if not (has_file_link or has_browser_tool):
                continue

            links: list[str] = []
            if wants_button and preview_url not in content:
                links.append(f"[{self.valves.PREVIEW_BUTTON_TEXT}]({preview_url})")
            # Archive download only makes sense when files actually exist for
            # this chat — gate it on has_file_link, not on the browser-tool
            # trigger.
            if wants_archive and has_file_link and archive_url not in content:
                links.append(f"[{self.valves.ARCHIVE_BUTTON_TEXT}]({archive_url})")
            if links:
                content += "\n\n" + "\n".join(links)

            if wants_artifact:
                iframe = (
                    f'<iframe src="{preview_url}" '
                    f'style="width:100%;height:100%;border:none" '
                    f'allow="clipboard-write; keyboard-map"></iframe>'
                )
                if iframe not in content:
                    content += "\n\n```html\n" + iframe + "\n```"

            message["content"] = content

        return body
