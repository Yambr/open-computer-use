# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for computer_link_filter (Open WebUI Function).

Run: python -m pytest tests/test_filter.py -v
"""

import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "openwebui" / "functions"))

import computer_link_filter  # noqa: E402


def _urlopen_mock(
    text: str = "PROMPT",
    public_base_url: str = "http://localhost:8081",
) -> MagicMock:
    """Create a mock satisfying: with urlopen(req, timeout=N) as resp: resp.read() + resp.headers.

    `public_base_url` is the value returned by the server in the X-Public-Base-URL
    header — outlet() builds browser-facing links from it.
    """
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    cm.read.return_value = text.encode("utf-8")
    cm.headers = {"X-Public-Base-URL": public_base_url}
    return cm


def _make_filter(
    orchestrator_url: str = "http://localhost:8081",
) -> "computer_link_filter.Filter":
    f = computer_link_filter.Filter()
    f.valves.ORCHESTRATOR_URL = orchestrator_url
    return f


def _prime_cache(
    f: "computer_link_filter.Filter",
    chat_id: str,
    user_email: str = "",
    public_url: str = "http://localhost:8081",
    prompt: str = "PROMPT",
) -> None:
    """Seed the filter's prompt cache so outlet() has a public_url to decorate with.

    outlet() never invents a public URL — it pulls from cache populated by inlet().
    Tests that exercise outlet() in isolation must prime the cache first.
    """
    f._prompt_cache[(chat_id, user_email)] = (time.time(), (public_url, prompt))


def _active_body() -> dict:
    return {
        "tool_ids": ["ai_computer_use"],
        "messages": [{"role": "user", "content": "hi"}],
    }


def _system_content(body: dict) -> str:
    for m in body["messages"]:
        if m.get("role") == "system":
            return m.get("content", "")
    return ""


def _assistant_body_with_file(chat_id: str = "abc") -> dict:
    link = f"http://localhost:8081/files/{chat_id}/report.pdf"
    return {"messages": [{"role": "assistant", "content": f"see {link}"}]}


class TrailingSlashNormalisation(unittest.TestCase):
    """Any URL Valve may arrive with a trailing slash; URLs must never end up with `//files/`."""

    def setUp(self):
        # inlet() fetches the prompt over HTTP — mock the response so it contains
        # the expected URL verbatim + the X-Public-Base-URL header outlet() reads.
        self._urlopen_patcher = patch(
            "urllib.request.urlopen",
            return_value=_urlopen_mock(
                "System prompt with http://localhost:8081/files/abc baked",
                public_base_url="http://localhost:8081",
            ),
        )
        self._urlopen_patcher.start()
        self.addCleanup(self._urlopen_patcher.stop)

    def test_inlet_does_not_emit_double_slash(self):
        f = _make_filter("http://localhost:8081/")
        body = f.inlet(_active_body(), __metadata__={"chat_id": "abc"})
        self.assertNotIn("//files/", _system_content(body))

    def test_outlet_archive_button_has_no_double_slash(self):
        f = _make_filter("http://localhost:8081/")
        # Simulate server that returned public URL with trailing slash.
        _prime_cache(f, "abc", public_url="http://localhost:8081/")
        link = "http://localhost:8081/files/abc/report.pdf"
        body = {"messages": [{"role": "assistant", "content": f"see {link}"}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        content = out["messages"][0]["content"]
        self.assertNotIn("//files/", content)
        self.assertIn("http://localhost:8081/files/abc/archive", content)


class EmptyChatIdHandling(unittest.TestCase):
    """When chat_id is missing, the injected prompt must not reference broken /files/ URLs."""

    def test_inlet_skips_injection_when_chat_id_is_none(self):
        f = _make_filter()
        body = f.inlet(_active_body(), __metadata__={})
        self.assertEqual("", _system_content(body),
                         "System prompt should not be injected when chat_id is missing")

    def test_inlet_skips_injection_when_metadata_missing(self):
        f = _make_filter()
        body = f.inlet(_active_body(), __metadata__=None)
        self.assertEqual("", _system_content(body))


class BaselineBehaviour(unittest.TestCase):
    """Regression guards: normal happy path must keep working."""

    def setUp(self):
        self._urlopen_patcher = patch(
            "urllib.request.urlopen",
            return_value=_urlopen_mock("System prompt with http://localhost:8081/files/abc baked"),
        )
        self._urlopen_patcher.start()
        self.addCleanup(self._urlopen_patcher.stop)

    def test_inlet_injects_when_tool_active_and_chat_id_present(self):
        f = _make_filter()
        body = f.inlet(_active_body(), __metadata__={"chat_id": "abc"})
        self.assertIn("http://localhost:8081/files/abc", _system_content(body))

    def test_inlet_no_injection_when_tool_inactive(self):
        f = _make_filter()
        body = f.inlet(
            {"tool_ids": [], "messages": [{"role": "user", "content": "hi"}]},
            __metadata__={"chat_id": "abc"},
        )
        self.assertEqual("", _system_content(body))

    def test_inlet_handles_non_string_system_content(self):
        """Open WebUI multimodal flows can deliver system `content` as a list of
        parts instead of a string. inlet() must not crash on re.search and must
        still inject the Computer Use prompt. Regression for CodeRabbit finding
        on 2026-04-12 (filter.py:220)."""
        f = _make_filter()
        structured_content = [{"type": "text", "text": "hello"}]
        body = {
            "tool_ids": ["ai_computer_use"],
            "messages": [
                {"role": "system", "content": structured_content},
                {"role": "user", "content": "hi"},
            ],
        }
        result = f.inlet(body, __metadata__={"chat_id": "abc"})
        # Did not raise; injection still happened somewhere in the system slot
        system_content = result["messages"][0]["content"]
        self.assertIsInstance(system_content, str)
        self.assertIn("http://localhost:8081/files/abc", system_content)

    def test_outlet_appends_archive_button_once(self):
        f = _make_filter()
        _prime_cache(f, "abc")
        link = "http://localhost:8081/files/abc/report.pdf"
        body = {"messages": [{"role": "assistant", "content": f"see {link}"}]}
        out1 = f.outlet(body, __metadata__={"chat_id": "abc"})
        out2 = f.outlet(out1, __metadata__={"chat_id": "abc"})
        self.assertEqual(
            out1["messages"][0]["content"],
            out2["messages"][0]["content"],
            "Archive button must be idempotent (not duplicated on repeat outlet calls)",
        )

    def test_outlet_does_not_modify_non_assistant_messages(self):
        """User/system/tool messages must be left untouched even if they contain a file URL."""
        f = _make_filter()
        _prime_cache(f, "abc")
        link = "http://localhost:8081/files/abc/report.pdf"
        original_user = f"check {link}"
        original_system = f"context with {link}"
        body = {
            "messages": [
                {"role": "user", "content": original_user},
                {"role": "system", "content": original_system},
                {"role": "tool", "content": f"tool output {link}"},
            ]
        }
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertEqual(out["messages"][0]["content"], original_user)
        self.assertEqual(out["messages"][1]["content"], original_system)
        self.assertNotIn("archive", out["messages"][2]["content"].lower())

    def test_outlet_ignores_file_urls_for_other_chat_ids(self):
        """Archive button must NOT be appended when the only file URL belongs to a
        different chat_id (e.g. a multi-user workspace or a quoted prior transcript).
        Regression guard for W-01: outlet previously matched any chat_id via `[^/]+`.
        """
        f = _make_filter()
        _prime_cache(f, "abc")
        other_link = "http://localhost:8081/files/other-chat/report.pdf"
        original_content = f"see artefact from the other chat: {other_link}"
        body = {"messages": [{"role": "assistant", "content": original_content}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertEqual(
            out["messages"][0]["content"],
            original_content,
            "Message referencing a file URL for a different chat_id must be left untouched",
        )
        self.assertNotIn("archive", out["messages"][0]["content"].lower())


class SystemPromptFetchCache(unittest.TestCase):
    """HTTP-fetch + LRU cache + stale-cache fallback.

    v4.0.0: _fetch_system_prompt() returns (public_url, prompt) tuple instead of
    just the prompt — public_url comes from the X-Public-Base-URL response header
    so outlet() doesn't need its own URL Valve.
    """

    def test_fresh_fetch_populates_cache(self):
        f = _make_filter()
        with patch(
            "urllib.request.urlopen",
            return_value=_urlopen_mock("PROMPT_V1", public_base_url="http://pub:8081"),
        ):
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result, ("http://pub:8081", "PROMPT_V1"))
        self.assertIn(("chat-a", ""), f._prompt_cache)
        self.assertEqual(f._prompt_cache[("chat-a", "")][1], ("http://pub:8081", "PROMPT_V1"))

    def test_fetch_falls_back_to_orchestrator_url_when_header_missing(self):
        """Older servers may not send X-Public-Base-URL. Filter falls back to
        reusing ORCHESTRATOR_URL as public_url (only correct for bare-metal)."""
        f = _make_filter("http://int:8081")
        cm = _urlopen_mock("PROMPT")
        cm.headers = {}  # server did not set the header
        with patch("urllib.request.urlopen", return_value=cm):
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result, ("http://int:8081", "PROMPT"))

    def test_cache_hit_within_ttl_skips_http(self):
        f = _make_filter()
        f._prompt_cache[("chat-a", "")] = (time.time(), ("http://pub:8081", "CACHED"))
        with patch("urllib.request.urlopen", side_effect=AssertionError("urlopen must not be called")) as m:
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result, ("http://pub:8081", "CACHED"))
        m.assert_not_called()

    def test_ttl_expiry_triggers_refetch(self):
        f = _make_filter()
        f._prompt_cache[("chat-a", "")] = (time.time() - 301, ("http://pub:8081", "OLD"))
        with patch("urllib.request.urlopen", return_value=_urlopen_mock("FRESH")):
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result[1], "FRESH")
        self.assertGreater(f._prompt_cache[("chat-a", "")][0], time.time() - 5)

    def test_lru_eviction_at_max_size(self):
        f = _make_filter()
        with patch("urllib.request.urlopen", side_effect=lambda *a, **kw: _urlopen_mock("P")):
            for i in range(1, 102):  # 101 distinct chat ids
                f._fetch_system_prompt(f"chat-{i}", "")
        self.assertEqual(len(f._prompt_cache), 100)
        self.assertNotIn(("chat-1", ""), f._prompt_cache)
        self.assertIn(("chat-101", ""), f._prompt_cache)

    def test_stale_cache_fallback_on_server_down(self):
        f = _make_filter()
        f._prompt_cache[("chat-a", "")] = (
            time.time() - 9999,
            ("http://pub:8081", "STALE"),
        )
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("conn refused")):
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result, ("http://pub:8081", "STALE"))

    def test_cold_cache_returns_none_when_server_down(self):
        f = _make_filter()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("conn refused")):
            result = f._fetch_system_prompt("chat-x", "")
        self.assertIsNone(result, f"Expected None on cold-cache failure, got {result!r}")

    def test_user_email_propagated_to_query_string(self):
        f = _make_filter()
        captured = {}

        def _capture(req, timeout=0):
            captured["url"] = req.full_url
            return _urlopen_mock("P")

        with patch("urllib.request.urlopen", side_effect=_capture):
            f._fetch_system_prompt("chat-a", "user@example.com")
        self.assertIn("chat_id=chat-a", captured["url"])
        self.assertIn("user_email=user%40example.com", captured["url"])

    def test_rejects_non_http_scheme_without_urlopen(self):
        """Valves misconfiguration (file://, ftp://, etc.) must not reach urlopen.
        Regression guard for ruff S310: ORCHESTRATOR_URL=file:///etc/passwd would
        otherwise read the file as the injected system prompt.
        """
        f = _make_filter("file:///etc/passwd")
        with patch("urllib.request.urlopen", side_effect=AssertionError("must not be called")) as m:
            result = f._fetch_system_prompt("chat-a", "")
        self.assertIsNone(result)
        m.assert_not_called()

    def test_rejects_non_http_scheme_serves_stale_cache_when_available(self):
        """If the scheme is invalid but a cached value exists, serve it (same
        policy as transport failure)."""
        f = _make_filter("ftp://example.com")
        f._prompt_cache[("chat-a", "")] = (
            time.time() - 9999,
            ("http://pub:8081", "STALE"),
        )
        with patch("urllib.request.urlopen", side_effect=AssertionError("must not be called")):
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result, ("http://pub:8081", "STALE"))

    def test_narrow_exception_propagates_programming_errors(self):
        """A broad `except Exception` used to swallow programming bugs (e.g.
        AttributeError from internal misuse) as silent stale-cache fallbacks.
        The narrowed handler must re-raise non-transport failures."""
        f = _make_filter()
        with patch("urllib.request.urlopen", side_effect=AttributeError("boom")):
            with self.assertRaises(AttributeError):
                f._fetch_system_prompt("chat-a", "")

    def test_cache_isolates_different_users_on_same_chat(self):
        """Two users sharing a chat_id must NOT see each other's baked <available_skills>."""
        f = _make_filter()
        prompts = iter(["PROMPT_FOR_ALICE", "PROMPT_FOR_BOB"])

        def _serve_next(req, timeout=0):
            return _urlopen_mock(next(prompts))

        with patch("urllib.request.urlopen", side_effect=_serve_next):
            a = f._fetch_system_prompt("chat-shared", "alice@example.com")
            b = f._fetch_system_prompt("chat-shared", "bob@example.com")
        self.assertEqual(a[1], "PROMPT_FOR_ALICE")
        self.assertEqual(b[1], "PROMPT_FOR_BOB")
        self.assertIn(("chat-shared", "alice@example.com"), f._prompt_cache)
        self.assertIn(("chat-shared", "bob@example.com"), f._prompt_cache)
        # No cross-contamination: Alice's cached entry still holds Alice's prompt
        self.assertEqual(
            f._prompt_cache[("chat-shared", "alice@example.com")][1][1],
            "PROMPT_FOR_ALICE",
        )


class PreviewArtifact(unittest.TestCase):
    """Covers PREVIEW-01 (default iframe artifact), PREVIEW-03 (invariants for iframe), PREVIEW-04 (iframe idempotency)."""

    def _filter(self, public_url: str = "http://localhost:8081") -> "computer_link_filter.Filter":
        f = _make_filter()
        _prime_cache(f, "abc", public_url=public_url)
        return f

    def test_outlet_appends_iframe_artifact_by_default(self):
        f = self._filter()
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        content = body["messages"][0]["content"]
        self.assertIn('<iframe src="http://localhost:8081/preview/abc"', content)
        self.assertIn("```html", content)
        self.assertIn('allow="clipboard-write; keyboard-map"', content)

    def test_outlet_iframe_artifact_is_idempotent(self):
        f = self._filter()
        body = _assistant_body_with_file()
        out1 = f.outlet(body, __metadata__={"chat_id": "abc"})
        out2 = f.outlet(out1, __metadata__={"chat_id": "abc"})
        self.assertEqual(out1["messages"][0]["content"], out2["messages"][0]["content"])
        self.assertEqual(out2["messages"][0]["content"].count("<iframe src="), 1)

    def test_outlet_iframe_artifact_disabled_when_valve_false(self):
        f = self._filter()
        f.valves.PREVIEW_MODE = "button"  # artifact disabled (only button)
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        content = body["messages"][0]["content"]
        self.assertNotIn("<iframe", content)
        self.assertNotIn("```html", content)

    def test_outlet_iframe_artifact_respects_other_chat_ids(self):
        f = self._filter()
        other_link = "http://localhost:8081/files/other-chat/report.pdf"
        original = f"see artefact from another chat: {other_link}"
        body = {"messages": [{"role": "assistant", "content": original}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertEqual(out["messages"][0]["content"], original)

    def test_outlet_iframe_not_added_to_non_assistant_roles(self):
        f = self._filter()
        link = "http://localhost:8081/files/abc/report.pdf"
        body = {
            "messages": [
                {"role": "user", "content": f"u {link}"},
                {"role": "system", "content": f"s {link}"},
                {"role": "tool", "content": f"t {link}"},
            ]
        }
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        for msg in out["messages"]:
            self.assertNotIn("<iframe", msg["content"])
            self.assertNotIn("```html", msg["content"])

    def test_outlet_iframe_url_has_no_double_slash_when_trailing_slash(self):
        f = self._filter(public_url="http://localhost:8081/")
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        content = body["messages"][0]["content"]
        self.assertNotIn("//preview/", content)
        self.assertIn('<iframe src="http://localhost:8081/preview/abc"', content)


class PreviewButton(unittest.TestCase):
    """Covers PREVIEW-02 (opt-in markdown button), PREVIEW-04 (button idempotency)."""

    def _filter(self) -> "computer_link_filter.Filter":
        f = _make_filter()
        _prime_cache(f, "abc")
        return f

    def test_outlet_preview_button_off_by_default(self):
        f = self._filter()
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        self.assertNotIn("[🖥️ Open preview]", body["messages"][0]["content"])

    def test_outlet_preview_button_appended_when_enabled(self):
        f = self._filter()
        f.valves.PREVIEW_MODE = "both"
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        self.assertIn(
            "[🖥️ Open preview](http://localhost:8081/preview/abc)",
            body["messages"][0]["content"],
        )

    def test_outlet_preview_button_is_idempotent(self):
        f = self._filter()
        f.valves.PREVIEW_MODE = "both"
        body = _assistant_body_with_file()
        out1 = f.outlet(body, __metadata__={"chat_id": "abc"})
        out2 = f.outlet(out1, __metadata__={"chat_id": "abc"})
        self.assertEqual(out1["messages"][0]["content"], out2["messages"][0]["content"])
        self.assertEqual(
            out2["messages"][0]["content"].count("[🖥️ Open preview]"),
            1,
        )

    def test_outlet_preview_button_respects_other_chat_ids(self):
        f = self._filter()
        f.valves.PREVIEW_MODE = "both"
        other_link = "http://localhost:8081/files/other-chat/report.pdf"
        original = f"see {other_link}"
        body = {"messages": [{"role": "assistant", "content": original}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertEqual(out["messages"][0]["content"], original)


class BrowserToolTrigger(unittest.TestCase):
    """Covers the second outlet() trigger: a `<details type="tool_calls">` block
    referencing a browser tool (playwright / chromium / screenshot / start-browser).

    Added to exercise the 2026-04-18 fix — previously untested. Sessions that
    drive a browser without producing a downloadable file must still get a
    preview iframe; archive button must stay gated on file URLs only.
    """

    def _tool_call_details(self, name: str = "playwright", arguments: str = "{}") -> str:
        # Attribute values come html-escaped in production but substring
        # keyword matching is robust to that, per _content_has_browser_tool's
        # docstring. Use raw values here for readability.
        return f'<details type="tool_calls" name="{name}" arguments="{arguments}" result=""></details>'

    def test_helper_detects_each_browser_keyword(self):
        """_content_has_browser_tool() must match every keyword in the allow-list."""
        for kw in computer_link_filter._BROWSER_TOOL_KEYWORDS:
            content = self._tool_call_details(name=kw)
            self.assertTrue(
                computer_link_filter._content_has_browser_tool(content),
                f"Keyword {kw!r} inside <details type=\"tool_calls\"> should trigger detection",
            )

    def test_helper_matches_keyword_in_arguments(self):
        """Keyword may live in the html-escaped `arguments="..."` attribute rather
        than the tool name. Open WebUI escapes quotes inside JSON args as `&#34;`,
        so plaintext keywords remain a valid substring of the escaped blob."""
        escaped_args = "{&#34;action&#34;:&#34;chromium-launch&#34;}"
        content = self._tool_call_details(name="mcp", arguments=escaped_args)
        self.assertTrue(computer_link_filter._content_has_browser_tool(content))

    def test_helper_ignores_freetext_keyword_mentions(self):
        """Keyword in plain assistant text (outside a tool_calls details block) must NOT trigger."""
        content = "How does playwright handle screenshot capture in chromium?"
        self.assertFalse(computer_link_filter._content_has_browser_tool(content))

    def test_helper_ignores_non_toolcall_details_blocks(self):
        """`<details type="reasoning">playwright</details>` must NOT trigger — detection is
        scoped to type=\"tool_calls\" only."""
        content = '<details type="reasoning" name="playwright">thinking...</details>'
        self.assertFalse(computer_link_filter._content_has_browser_tool(content))

    def test_helper_returns_false_on_empty_content(self):
        self.assertFalse(computer_link_filter._content_has_browser_tool(""))
        self.assertFalse(computer_link_filter._content_has_browser_tool(None))  # type: ignore[arg-type]

    def _primed_filter(self) -> "computer_link_filter.Filter":
        f = _make_filter()
        _prime_cache(f, "abc")
        return f

    def test_outlet_appends_iframe_on_browser_tool_without_file_url(self):
        """outlet() must inject preview iframe when a browser tool ran but produced no file."""
        f = self._primed_filter()
        content = "I navigated to the page. " + self._tool_call_details(name="playwright")
        body = {"messages": [{"role": "assistant", "content": content}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertIn('<iframe src="http://localhost:8081/preview/abc"', out["messages"][0]["content"])

    def test_outlet_preview_button_triggered_by_browser_tool(self):
        """When PREVIEW_MODE is "both", browser-tool trigger alone is enough to inject the button."""
        f = self._primed_filter()
        f.valves.PREVIEW_MODE = "both"
        content = self._tool_call_details(name="chromium")
        body = {"messages": [{"role": "assistant", "content": content}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertIn(
            "[🖥️ Open preview](http://localhost:8081/preview/abc)",
            out["messages"][0]["content"],
        )

    def test_outlet_archive_button_NOT_triggered_by_browser_tool_alone(self):
        """Archive button is meaningless without files — must stay gated on file URLs even
        when a browser tool ran."""
        f = self._primed_filter()
        content = self._tool_call_details(name="screenshot")
        body = {"messages": [{"role": "assistant", "content": content}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertNotIn("archive", out["messages"][0]["content"].lower())

    def test_outlet_does_not_trigger_on_freetext_keyword(self):
        """Regression guard for false-positive scoping: assistant free text mentioning
        a browser tool must NOT receive preview decoration."""
        f = self._primed_filter()
        body = {"messages": [{"role": "assistant", "content": "Use playwright to click the button."}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertNotIn("<iframe", out["messages"][0]["content"])
        self.assertNotIn("preview", out["messages"][0]["content"].lower())

    def test_outlet_browser_tool_trigger_is_idempotent(self):
        """Repeated outlet() calls on browser-tool-triggered content must not duplicate iframe."""
        f = self._primed_filter()
        content = self._tool_call_details(name="playwright")
        body = {"messages": [{"role": "assistant", "content": content}]}
        out1 = f.outlet(body, __metadata__={"chat_id": "abc"})
        out2 = f.outlet(out1, __metadata__={"chat_id": "abc"})
        self.assertEqual(out1["messages"][0]["content"], out2["messages"][0]["content"])
        self.assertEqual(out2["messages"][0]["content"].count("<iframe src="), 1)


class OutletWithoutCache(unittest.TestCase):
    """outlet() must not invent a public URL. When the cache is empty (outlet
    invoked on a re-rendered old message after a server restart, or before
    inlet() ran), decoration is skipped — broken links are worse than no links.
    """

    def test_outlet_skips_all_decoration_when_cache_empty(self):
        f = _make_filter()
        link = "http://localhost:8081/files/abc/report.pdf"
        original = f"assistant said: {link}"
        body = {"messages": [{"role": "assistant", "content": original}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertEqual(
            out["messages"][0]["content"],
            original,
            "Empty cache must leave the message untouched — no iframe, button, or archive",
        )

    def test_outlet_skips_when_cache_has_different_chat_id(self):
        """Cache for chat-X must not decorate a message sent in chat-Y."""
        f = _make_filter()
        _prime_cache(f, "other-chat")
        link = "http://localhost:8081/files/abc/report.pdf"
        original = f"assistant said: {link}"
        body = {"messages": [{"role": "assistant", "content": original}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertEqual(out["messages"][0]["content"], original)


class ValveSchema(unittest.TestCase):
    """Filter owns exactly one URL Valve (ORCHESTRATOR_URL). FILE_SERVER_URL and
    SYSTEM_PROMPT_URL are gone — the public URL is owned by the server and returned
    via the X-Public-Base-URL response header on /system-prompt."""

    def test_only_orchestrator_url_valve_exists(self):
        valve_fields = set(computer_link_filter.Filter.Valves.model_fields.keys())
        self.assertIn("ORCHESTRATOR_URL", valve_fields)
        self.assertNotIn("FILE_SERVER_URL", valve_fields)
        self.assertNotIn("SYSTEM_PROMPT_URL", valve_fields)


class DocstringDriftGuard(unittest.TestCase):
    """Covers DOCS-03 — every Field on Filter.Valves is listed in the module VALVES: docstring."""

    def test_every_valve_is_documented_in_docstring(self):
        doc = computer_link_filter.__doc__ or ""
        self.assertIn("VALVES:", doc, "Module docstring must contain a VALVES: block")
        # Extract everything under VALVES: to the next blank-line-separated section
        # (or end of docstring). Simple split is sufficient — drift guard only.
        after_marker = doc.split("VALVES:", 1)[1]
        for field_name in computer_link_filter.Filter.Valves.model_fields:
            self.assertIn(
                field_name,
                after_marker,
                f"Valve {field_name!r} is defined on Filter.Valves but missing "
                f"from the VALVES: docstring block — update the docstring "
                f"in computer_link_filter.py to list it.",
            )


if __name__ == "__main__":
    unittest.main()
