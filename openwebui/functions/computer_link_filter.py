# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
title: Computer Use Filter
author: Open Computer Use Contributors
version: 3.2.0
required_open_webui_version: 0.5.17
description: HTTP-fetches Computer Use system prompt from orchestrator, with LRU cache and stale-cache fallback. outlet() appends a preview iframe artifact (default) or a markdown preview button (opt-in) to assistant messages containing Computer Use file links.

This filter works in conjunction with Computer Use Tools (computer_use_tools.py).

FUNCTIONALITY:
- inlet(): When tool "ai_computer_use" is active and chat_id is present, fetches the
  fully-baked system prompt from the orchestrator's /system-prompt endpoint (server
  substitutes {file_base_url}, {archive_url}, {chat_id} and assembles <available_skills>)
  and injects it into the system message. Cache: 5-minute TTL, max 100 entries,
  O(1) LRU eviction. On fetch failure: serve stale cache if present; else skip injection.
- outlet(): Appends a preview iframe artifact (ENABLE_PREVIEW_ARTIFACT=True by default)
  and/or a markdown preview button (ENABLE_PREVIEW_BUTTON=False by default) and/or an
  archive-download button (ENABLE_ARCHIVE_BUTTON=True by default) to assistant messages
  containing file URLs for the current chat_id. All three are idempotent (substring
  guarded) and scoped to the current chat_id.

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
            from this. Trailing slash is tolerated (stripped internally).
        SYSTEM_PROMPT_URL (str, default ""):
            Override URL for the /system-prompt endpoint. Empty means derive from
            FILE_SERVER_URL. Non-http(s) schemes are rejected.
        INJECT_SYSTEM_PROMPT (bool, default True):
            If False, inlet() skips system-prompt injection entirely (useful when
            another filter owns the prompt).
        ENABLE_ARCHIVE_BUTTON (bool, default True):
            If True, outlet() appends `[{ARCHIVE_BUTTON_TEXT}]({base}/files/{chat_id}/archive)`
            to assistant messages containing file URLs for the current chat_id. Idempotent.
        ARCHIVE_BUTTON_TEXT (str, default "📦 Download all files as archive"):
            Label for the archive-download markdown link.
        ENABLE_PREVIEW_ARTIFACT (bool, default True):
            If True, outlet() appends a fenced ```html block containing an
            `<iframe src="{base}/preview/{chat_id}" style="width:100%;height:100%;border:none"
            allow="clipboard-write; keyboard-map"></iframe>` snippet to assistant messages
            containing file URLs for the current chat_id. Intended default UX for
            deployments that render fenced html blocks as artifacts.
        ENABLE_PREVIEW_BUTTON (bool, default False):
            If True, outlet() appends `[{PREVIEW_BUTTON_TEXT}]({base}/preview/{chat_id})`
            to the same qualifying messages. Opt-in escape hatch for stock Open WebUI
            where artifact rendering is unavailable.
        PREVIEW_BUTTON_TEXT (str, default "🖥️ Open preview"):
            Label for the opt-in preview-button markdown link.
"""

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Optional

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
            description="Orchestrator base URL (without trailing slash)",
        )
        SYSTEM_PROMPT_URL: str = Field(
            default="",
            description="Override URL for /system-prompt endpoint (empty = derive from FILE_SERVER_URL)",
        )
        ENABLE_ARCHIVE_BUTTON: bool = Field(
            default=True,
            description="Add 'Download all as archive' button to messages with files",
        )
        ARCHIVE_BUTTON_TEXT: str = Field(
            default="📦 Download all files as archive",
            description="Text for the archive-download button",
        )
        ENABLE_PREVIEW_ARTIFACT: bool = Field(
            default=True,
            description="Append an inline <iframe> artifact rendering /preview/{chat_id} to assistant messages with file links",
        )
        ENABLE_PREVIEW_BUTTON: bool = Field(
            default=False,
            description="Append a markdown [preview](…) link to assistant messages with file links (opt-in fallback when artifact rendering is unavailable)",
        )
        PREVIEW_BUTTON_TEXT: str = Field(
            default="🖥️ Open preview",
            description="Text for the preview-button markdown link",
        )
        INJECT_SYSTEM_PROMPT: bool = Field(
            default=True,
            description="Inject Computer Use system prompt when tools are active",
        )

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

        - ENABLE_PREVIEW_ARTIFACT (default True): inline ```html <iframe src="…/preview/{chat_id}"> artifact.
        - ENABLE_PREVIEW_BUTTON (default False): markdown link to the preview page — opt-in for stock Open WebUI.
        - ENABLE_ARCHIVE_BUTTON (default True): markdown link to the archive endpoint.

        Invariants (preserved from v3.1.0):
        1. Only role=="assistant" messages are touched.
        2. Non-string content is skipped.
        3. file_url_pattern is scoped to the current chat_id (no cross-chat decoration).
        4. FILE_SERVER_URL is rstripped before URL construction (no //preview/ or //files/).
        5. Substring-based idempotency — repeated outlet() calls do not duplicate.
        """
        if not (self.valves.ENABLE_ARCHIVE_BUTTON
                or self.valves.ENABLE_PREVIEW_BUTTON
                or self.valves.ENABLE_PREVIEW_ARTIFACT):
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
            if self.valves.ENABLE_PREVIEW_BUTTON and preview_url not in content:
                links.append(f"[{self.valves.PREVIEW_BUTTON_TEXT}]({preview_url})")
            # Archive download only makes sense when files actually exist for
            # this chat — gate it on has_file_link, not on the browser-tool
            # trigger.
            if self.valves.ENABLE_ARCHIVE_BUTTON and has_file_link and archive_url not in content:
                links.append(f"[{self.valves.ARCHIVE_BUTTON_TEXT}]({archive_url})")
            if links:
                content += "\n\n" + "\n".join(links)

            if self.valves.ENABLE_PREVIEW_ARTIFACT:
                iframe = (
                    f'<iframe src="{preview_url}" '
                    f'style="width:100%;height:100%;border:none" '
                    f'allow="clipboard-write; keyboard-map"></iframe>'
                )
                if iframe not in content:
                    content += "\n\n```html\n" + iframe + "\n```"

            message["content"] = content

        return body
