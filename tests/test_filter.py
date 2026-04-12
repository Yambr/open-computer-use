# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for computer_link_filter (Open WebUI Function).

Run: python -m pytest tests/test_filter.py -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "openwebui" / "functions"))

import computer_link_filter  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
