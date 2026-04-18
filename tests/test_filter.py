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


def _urlopen_mock(text: str = "PROMPT") -> MagicMock:
    """Create a mock satisfying: with urlopen(req, timeout=N) as resp: resp.read()."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    cm.read.return_value = text.encode("utf-8")
    return cm


def _make_filter(file_server_url: str = "http://localhost:8081") -> "computer_link_filter.Filter":
    f = computer_link_filter.Filter()
    f.valves.FILE_SERVER_URL = file_server_url
    return f


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
    """FILE_SERVER_URL may arrive with a trailing slash; URLs must never end up with `//files/`."""

    def setUp(self):
        # After filter rewrite (Task 3), inlet() fetches the prompt over HTTP —
        # mock the response so it contains the expected URL verbatim.
        self._urlopen_patcher = patch(
            "urllib.request.urlopen",
            return_value=_urlopen_mock("System prompt with http://localhost:8081/files/abc baked"),
        )
        self._urlopen_patcher.start()
        self.addCleanup(self._urlopen_patcher.stop)

    def test_inlet_does_not_emit_double_slash(self):
        f = _make_filter("http://localhost:8081/")
        body = f.inlet(_active_body(), __metadata__={"chat_id": "abc"})
        self.assertNotIn("//files/", _system_content(body))

    def test_outlet_archive_button_has_no_double_slash(self):
        f = _make_filter("http://localhost:8081/")
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
    """New in v3.1.0: HTTP-fetch + LRU cache + stale-cache fallback."""

    def test_fresh_fetch_populates_cache(self):
        f = _make_filter()
        with patch("urllib.request.urlopen", return_value=_urlopen_mock("PROMPT_V1")):
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result, "PROMPT_V1")
        self.assertIn(("chat-a", ""), f._prompt_cache)
        self.assertEqual(f._prompt_cache[("chat-a", "")][1], "PROMPT_V1")

    def test_cache_hit_within_ttl_skips_http(self):
        f = _make_filter()
        f._prompt_cache[("chat-a", "")] = (time.time(), "CACHED")
        with patch("urllib.request.urlopen", side_effect=AssertionError("urlopen must not be called")) as m:
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result, "CACHED")
        m.assert_not_called()

    def test_ttl_expiry_triggers_refetch(self):
        f = _make_filter()
        f._prompt_cache[("chat-a", "")] = (time.time() - 301, "OLD")
        with patch("urllib.request.urlopen", return_value=_urlopen_mock("FRESH")):
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result, "FRESH")
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
        f._prompt_cache[("chat-a", "")] = (time.time() - 9999, "STALE")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("conn refused")):
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result, "STALE")

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
        Regression guard for ruff S310: SYSTEM_PROMPT_URL=file:///etc/passwd used
        to read the file as the injected system prompt.
        """
        f = _make_filter()
        f.valves.SYSTEM_PROMPT_URL = "file:///etc/passwd"
        with patch("urllib.request.urlopen", side_effect=AssertionError("must not be called")) as m:
            result = f._fetch_system_prompt("chat-a", "")
        self.assertIsNone(result)
        m.assert_not_called()

    def test_rejects_non_http_scheme_serves_stale_cache_when_available(self):
        """If the scheme is invalid but a cached value exists, serve it (same
        policy as transport failure)."""
        f = _make_filter()
        f.valves.SYSTEM_PROMPT_URL = "ftp://example.com/prompt"
        f._prompt_cache[("chat-a", "")] = (time.time() - 9999, "STALE")
        with patch("urllib.request.urlopen", side_effect=AssertionError("must not be called")):
            result = f._fetch_system_prompt("chat-a", "")
        self.assertEqual(result, "STALE")

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
        self.assertEqual(a, "PROMPT_FOR_ALICE")
        self.assertEqual(b, "PROMPT_FOR_BOB")
        self.assertIn(("chat-shared", "alice@example.com"), f._prompt_cache)
        self.assertIn(("chat-shared", "bob@example.com"), f._prompt_cache)
        # No cross-contamination: Alice's cached entry still holds Alice's prompt
        self.assertEqual(f._prompt_cache[("chat-shared", "alice@example.com")][1], "PROMPT_FOR_ALICE")


class PreviewArtifact(unittest.TestCase):
    """Covers PREVIEW-01 (default iframe artifact), PREVIEW-03 (invariants for iframe), PREVIEW-04 (iframe idempotency)."""

    def test_outlet_appends_iframe_artifact_by_default(self):
        f = _make_filter()
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        content = body["messages"][0]["content"]
        self.assertIn('<iframe src="http://localhost:8081/preview/abc"', content)
        self.assertIn("```html", content)
        self.assertIn('allow="clipboard-write; keyboard-map"', content)

    def test_outlet_iframe_artifact_is_idempotent(self):
        f = _make_filter()
        body = _assistant_body_with_file()
        out1 = f.outlet(body, __metadata__={"chat_id": "abc"})
        out2 = f.outlet(out1, __metadata__={"chat_id": "abc"})
        self.assertEqual(out1["messages"][0]["content"], out2["messages"][0]["content"])
        self.assertEqual(out2["messages"][0]["content"].count("<iframe src="), 1)

    def test_outlet_iframe_artifact_disabled_when_valve_false(self):
        f = _make_filter()
        f.valves.PREVIEW_MODE = "button"  # artifact disabled (only button)
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        content = body["messages"][0]["content"]
        self.assertNotIn("<iframe", content)
        self.assertNotIn("```html", content)

    def test_outlet_iframe_artifact_respects_other_chat_ids(self):
        f = _make_filter()
        other_link = "http://localhost:8081/files/other-chat/report.pdf"
        original = f"see artefact from another chat: {other_link}"
        body = {"messages": [{"role": "assistant", "content": original}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertEqual(out["messages"][0]["content"], original)

    def test_outlet_iframe_not_added_to_non_assistant_roles(self):
        f = _make_filter()
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
        f = _make_filter("http://localhost:8081/")
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        content = body["messages"][0]["content"]
        self.assertNotIn("//preview/", content)
        self.assertIn('<iframe src="http://localhost:8081/preview/abc"', content)


class PreviewButton(unittest.TestCase):
    """Covers PREVIEW-02 (opt-in markdown button), PREVIEW-04 (button idempotency)."""

    def test_outlet_preview_button_off_by_default(self):
        f = _make_filter()
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        self.assertNotIn("[🖥️ Open preview]", body["messages"][0]["content"])

    def test_outlet_preview_button_appended_when_enabled(self):
        f = _make_filter()
        f.valves.PREVIEW_MODE = "both"
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        self.assertIn(
            "[🖥️ Open preview](http://localhost:8081/preview/abc)",
            body["messages"][0]["content"],
        )

    def test_outlet_preview_button_is_idempotent(self):
        f = _make_filter()
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
        f = _make_filter()
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

    def test_outlet_appends_iframe_on_browser_tool_without_file_url(self):
        """outlet() must inject preview iframe when a browser tool ran but produced no file."""
        f = _make_filter()
        content = "I navigated to the page. " + self._tool_call_details(name="playwright")
        body = {"messages": [{"role": "assistant", "content": content}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertIn('<iframe src="http://localhost:8081/preview/abc"', out["messages"][0]["content"])

    def test_outlet_preview_button_triggered_by_browser_tool(self):
        """When PREVIEW_MODE is "both", browser-tool trigger alone is enough to inject the button."""
        f = _make_filter()
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
        f = _make_filter()
        content = self._tool_call_details(name="screenshot")
        body = {"messages": [{"role": "assistant", "content": content}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertNotIn("archive", out["messages"][0]["content"].lower())

    def test_outlet_does_not_trigger_on_freetext_keyword(self):
        """Regression guard for false-positive scoping: assistant free text mentioning
        a browser tool must NOT receive preview decoration."""
        f = _make_filter()
        body = {"messages": [{"role": "assistant", "content": "Use playwright to click the button."}]}
        out = f.outlet(body, __metadata__={"chat_id": "abc"})
        self.assertNotIn("<iframe", out["messages"][0]["content"])
        self.assertNotIn("preview", out["messages"][0]["content"].lower())

    def test_outlet_browser_tool_trigger_is_idempotent(self):
        """Repeated outlet() calls on browser-tool-triggered content must not duplicate iframe."""
        f = _make_filter()
        content = self._tool_call_details(name="playwright")
        body = {"messages": [{"role": "assistant", "content": content}]}
        out1 = f.outlet(body, __metadata__={"chat_id": "abc"})
        out2 = f.outlet(out1, __metadata__={"chat_id": "abc"})
        self.assertEqual(out1["messages"][0]["content"], out2["messages"][0]["content"])
        self.assertEqual(out2["messages"][0]["content"].count("<iframe src="), 1)


class MigrationFromV320(unittest.TestCase):
    """Covers the v3.2.0 → v3.3.0 Valves backward-compat migration.

    The Filter.Valves._migrate_legacy @model_validator maps legacy boolean
    Valves (ENABLE_PREVIEW_ARTIFACT, ENABLE_PREVIEW_BUTTON, ENABLE_ARCHIVE_BUTTON)
    onto the new Literal Valves (PREVIEW_MODE, ARCHIVE_BUTTON) so existing
    deployments keep their user-saved preferences on upgrade.

    Critical invariant: the validator must NOT overwrite a new field the user
    explicitly set post-upgrade. model_fields_set is the gate.
    """

    def _valves(self, **kwargs) -> "computer_link_filter.Filter.Valves":
        """Instantiate Valves the same way Open WebUI does: Valves(**db_dict)."""
        return computer_link_filter.Filter.Valves(**kwargs)

    def test_fresh_deploy_uses_new_defaults(self):
        """Empty DB dict → new default PREVIEW_MODE=artifact, ARCHIVE_BUTTON=on.
        This is what a brand-new Open WebUI install sees on first load."""
        v = self._valves()
        self.assertEqual(v.PREVIEW_MODE, "artifact")
        self.assertEqual(v.ARCHIVE_BUTTON, "on")
        self.assertIsNone(v.ENABLE_PREVIEW_ARTIFACT)
        self.assertIsNone(v.ENABLE_PREVIEW_BUTTON)
        self.assertIsNone(v.ENABLE_ARCHIVE_BUTTON)

    def test_legacy_artifact_true_button_false_migrates_to_artifact(self):
        """v3.2.0 default state (artifact=True, button=False) → PREVIEW_MODE=artifact."""
        v = self._valves(ENABLE_PREVIEW_ARTIFACT=True, ENABLE_PREVIEW_BUTTON=False)
        self.assertEqual(v.PREVIEW_MODE, "artifact")

    def test_legacy_artifact_false_button_true_migrates_to_button(self):
        """User who flipped to button-only on v3.2.0 keeps button-only on v3.3.0."""
        v = self._valves(ENABLE_PREVIEW_ARTIFACT=False, ENABLE_PREVIEW_BUTTON=True)
        self.assertEqual(v.PREVIEW_MODE, "button")

    def test_legacy_both_true_migrates_to_both(self):
        """User who enabled both on v3.2.0 keeps both on v3.3.0."""
        v = self._valves(ENABLE_PREVIEW_ARTIFACT=True, ENABLE_PREVIEW_BUTTON=True)
        self.assertEqual(v.PREVIEW_MODE, "both")

    def test_legacy_both_false_migrates_to_off(self):
        """User who disabled all preview UI on v3.2.0 keeps it disabled on v3.3.0."""
        v = self._valves(ENABLE_PREVIEW_ARTIFACT=False, ENABLE_PREVIEW_BUTTON=False)
        self.assertEqual(v.PREVIEW_MODE, "off")

    def test_legacy_archive_button_false_migrates_to_off(self):
        v = self._valves(ENABLE_ARCHIVE_BUTTON=False)
        self.assertEqual(v.ARCHIVE_BUTTON, "off")

    def test_legacy_archive_button_true_maps_to_on(self):
        v = self._valves(ENABLE_ARCHIVE_BUTTON=True)
        self.assertEqual(v.ARCHIVE_BUTTON, "on")

    def test_explicit_new_value_wins_over_stale_legacy(self):
        """CRITICAL — a stale legacy value must NOT overwrite the user's new choice.

        Scenario: user upgrades to v3.3.0, sets PREVIEW_MODE='off' in the UI,
        saves. Open WebUI persists {'PREVIEW_MODE': 'off'} but the legacy field
        may still exist in the DB row from before the save (Open WebUI does a
        partial update via exclude_unset). On next load, Valves(**db_dict)
        receives BOTH. The explicit PREVIEW_MODE wins.
        """
        v = self._valves(PREVIEW_MODE="off", ENABLE_PREVIEW_ARTIFACT=True)
        self.assertEqual(v.PREVIEW_MODE, "off")

    def test_explicit_new_archive_wins_over_stale_legacy(self):
        v = self._valves(ARCHIVE_BUTTON="off", ENABLE_ARCHIVE_BUTTON=True)
        self.assertEqual(v.ARCHIVE_BUTTON, "off")

    def test_only_one_legacy_preview_field_set_still_migrates_correctly(self):
        """If the DB has only artifact=True (button unsaved), treat button as None."""
        v = self._valves(ENABLE_PREVIEW_ARTIFACT=True)
        self.assertEqual(v.PREVIEW_MODE, "artifact")
        v2 = self._valves(ENABLE_PREVIEW_BUTTON=True)
        self.assertEqual(v2.PREVIEW_MODE, "button")

    def test_outlet_honours_migrated_preview_mode(self):
        """End-to-end: legacy user's saved preference drives outlet() output."""
        f = _make_filter()
        f.valves = self._valves(ENABLE_PREVIEW_ARTIFACT=False, ENABLE_PREVIEW_BUTTON=True)
        f.valves.FILE_SERVER_URL = "http://localhost:8081"
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        content = body["messages"][0]["content"]
        self.assertIn("[🖥️ Open preview](http://localhost:8081/preview/abc)", content)
        self.assertNotIn("<iframe", content)

    def test_outlet_honours_migrated_archive_button(self):
        """Legacy ENABLE_ARCHIVE_BUTTON=False must suppress archive link in outlet."""
        f = _make_filter()
        f.valves = self._valves(ENABLE_ARCHIVE_BUTTON=False)
        f.valves.FILE_SERVER_URL = "http://localhost:8081"
        body = f.outlet(_assistant_body_with_file(), __metadata__={"chat_id": "abc"})
        self.assertNotIn("archive", body["messages"][0]["content"].lower())


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
