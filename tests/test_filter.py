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


if __name__ == "__main__":
    unittest.main()
