# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Pinning tests for /system-prompt endpoint.

The endpoint at computer-use-server/app.py:1154-1205 is already a correct port
of the internal fork v3.7/v3.8. These tests pin the current contract so future
refactors cannot regress it. All tests should PASS on current HEAD.

Run: python -m pytest tests/orchestrator/test_system_prompt_endpoint.py -v
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "computer-use-server"))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
import skill_manager as skill_manager_module  # noqa: E402


class SystemPromptEndpointContract(unittest.TestCase):
    """Pin /system-prompt endpoint behaviour — DO NOT modify the endpoint to make these pass."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app_module.app)
        cls.file_server_url = app_module.FILE_SERVER_URL

    def setUp(self):
        # Ensure tests are hermetic: reset skill_manager memory cache so that
        # a prior test run (or another test in this file) cannot leak a cached
        # skill list for the same email. Tests that need an external provider
        # stub it explicitly below.
        skill_manager_module._memory_cache.clear()

    def test_chat_id_substitutes_urls_and_literal(self):
        resp = self.client.get("/system-prompt", params={"chat_id": "abc123"})
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn(f"{self.file_server_url}/files/abc123", body)
        self.assertIn(f"{self.file_server_url}/files/abc123/archive", body)
        self.assertIn("abc123", body)
        self.assertNotIn("{file_base_url}", body)
        self.assertNotIn("{archive_url}", body)
        self.assertNotIn("{chat_id}", body)

    def test_user_email_returns_default_skills_when_provider_unconfigured(self):
        # Hermetic: force _fetch_user_config -> None and _load_user_config_cache -> None
        # so get_user_skills() takes the DEFAULT_PUBLIC_SKILLS fallback path
        # regardless of MCP_TOKENS_URL / MCP_TOKENS_API_KEY env state on the host.
        async def _no_provider(_email):
            return None

        with patch.object(skill_manager_module, "_fetch_user_config", side_effect=_no_provider), \
             patch.object(skill_manager_module, "_load_user_config_cache", return_value=None):
            resp = self.client.get(
                "/system-prompt",
                params={"chat_id": "abc", "user_email": "test@example.com"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("<available_skills>", resp.text)
        # DEFAULT_PUBLIC_SKILLS must appear — pin a representative one
        self.assertIn("<name>\ndocx\n</name>", resp.text)

    def test_legacy_file_base_url_and_archive_url_substitute(self):
        resp = self.client.get(
            "/system-prompt",
            params={
                "file_base_url": "https://example.com/files/xyz",
                "archive_url": "https://example.com/files/xyz/arch",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn("https://example.com/files/xyz", body)
        self.assertIn("https://example.com/files/xyz/arch", body)
        self.assertIn("xyz", body)
        self.assertNotIn("{file_base_url}", body)
        self.assertNotIn("{archive_url}", body)
        self.assertNotIn("{chat_id}", body)

    def test_no_params_returns_unsubstituted_template(self):
        resp = self.client.get("/system-prompt")
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        # Degraded diagnostic path — at least one placeholder still present
        self.assertTrue(
            any(ph in body for ph in ("{file_base_url}", "{archive_url}", "{chat_id}")),
            "Expected un-substituted placeholders in no-params response",
        )

    def test_content_type_is_text_plain(self):
        resp = self.client.get("/system-prompt", params={"chat_id": "abc"})
        self.assertTrue(
            resp.headers.get("content-type", "").startswith("text/plain"),
            f"Expected text/plain, got {resp.headers.get('content-type')}",
        )


if __name__ == "__main__":
    unittest.main()
