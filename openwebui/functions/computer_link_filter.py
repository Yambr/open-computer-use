# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
title: Computer Use Filter
author: Open Computer Use Contributors
version: 3.1.0
required_open_webui_version: 0.5.17
description: HTTP-fetches Computer Use system prompt from orchestrator /system-prompt endpoint, with LRU cache and stale-cache fallback.

This filter works in conjunction with Computer Use Tools (computer_use_tools.py).

FUNCTIONALITY:
- inlet(): When tool "ai_computer_use" is active and chat_id is present, fetches the
  fully-baked system prompt from the orchestrator's /system-prompt endpoint (server
  substitutes {file_base_url}, {archive_url}, {chat_id} and assembles <available_skills>)
  and injects it into the system message. Cache: 5-minute TTL, max 100 entries,
  O(1) LRU eviction. On fetch failure: serve stale cache if present; else skip injection.
- outlet(): Appends an archive-download button to assistant messages containing file links.

CHANGELOG (v3.1.0):
- Removed hardcoded ~460-line system prompt f-string; server is now the single source of truth.
- HTTP fetch + OrderedDict LRU cache + stale-cache fallback (ported from internal fork v3.8.0).
- Added SYSTEM_PROMPT_URL Valve (optional override); falls back to FILE_SERVER_URL/system-prompt.
- Removed client-side URL substitution — server does it.
- Dropped unused __files__ parameter from inlet().

CHANGELOG (v3.0.2):
- Previous version with hardcoded prompt; see git history for details.
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
            match = re.search(TEMPLATE_PATTERN, existing_content, re.MULTILINE)
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
                # No template vars -> append
                messages[system_msg_idx]["content"] = existing_content + "\n\n" + system_prompt
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
        """Append an archive-download button to assistant messages with file links."""
        chat_id = __metadata__.get("chat_id") if __metadata__ else None
        if not chat_id:
            return body

        if not self.valves.ENABLE_ARCHIVE_BUTTON:
            return body

        # Match orchestrator file links
        base = self.valves.FILE_SERVER_URL.rstrip("/")
        file_url_pattern = re.escape(base) + r"/files/" + re.escape(chat_id) + r"/[^\s\)]+"
        archive_url = f"{base}/files/{chat_id}/archive"

        for message in body.get("messages", []):
            # Docstring contract: archive button is appended to *assistant* messages only.
            # Rewriting user/system/tool content would corrupt upstream input.
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not content or not isinstance(content, str):
                continue
            if re.search(file_url_pattern, content) and archive_url not in content:
                message["content"] = (
                    content + f"\n\n[{self.valves.ARCHIVE_BUTTON_TEXT}]({archive_url})"
                )

        return body
