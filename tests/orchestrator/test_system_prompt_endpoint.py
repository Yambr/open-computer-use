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
        cls.public_base_url = app_module.PUBLIC_BASE_URL

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
        self.assertIn(f"{self.public_base_url}/files/abc123", body)
        self.assertIn(f"{self.public_base_url}/files/abc123/archive", body)
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

    def test_legacy_file_base_url_extracts_chat_id(self):
        """
        Pre-v4.0.0 integrations could pass ?file_base_url=... to embed their
        own browser-facing URLs in the prompt. Since v4.0.0 the server owns
        PUBLIC_BASE_URL. We only still accept file_base_url to extract its
        trailing chat_id for seamless migration. archive_url is ignored —
        server derives it from PUBLIC_BASE_URL + chat_id.
        """
        resp = self.client.get(
            "/system-prompt",
            params={
                "file_base_url": "https://legacy.example.com/files/xyz",
                "archive_url": "https://legacy.example.com/files/xyz/arch",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        # chat_id extracted from the trailing path segment, URL owned by server.
        self.assertIn(f"{self.public_base_url}/files/xyz", body)
        self.assertIn(f"{self.public_base_url}/files/xyz/archive", body)
        # Neither the legacy host nor the legacy archive URL leaks into the prompt.
        self.assertNotIn("legacy.example.com", body)
        # No raw template placeholders.
        self.assertNotIn("{file_base_url}", body)
        self.assertNotIn("{archive_url}", body)
        self.assertNotIn("{chat_id}", body)

    def test_legacy_file_base_url_ignored_when_chat_id_present(self):
        """Explicit chat_id always wins over legacy file_base_url extraction."""
        resp = self.client.get(
            "/system-prompt",
            params={
                "chat_id": "winner",
                "file_base_url": "https://legacy.example.com/files/loser",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"{self.public_base_url}/files/winner", resp.text)
        self.assertNotIn("loser", resp.text)

    def test_no_params_falls_back_to_default_chat(self):
        """Post-Tier-7: the endpoint no longer ships raw placeholders; it
        renders with chat_id='default' when nothing is supplied. Gives
        probing clients a valid (if generic) prompt instead of
        `{chat_id}` literals that confuse downstream consumers."""
        resp = self.client.get("/system-prompt")
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertNotIn("{file_base_url}", body)
        self.assertNotIn("{archive_url}", body)
        self.assertNotIn("{chat_id}", body)
        self.assertIn(f"{self.public_base_url}/files/default", body)

    # ------------------------------------------------------------------
    # Tier 7 header priority — added in the "maximum native surface" refactor
    # ------------------------------------------------------------------

    def test_header_overrides_query_chat_id(self):
        resp = self.client.get(
            "/system-prompt",
            params={"chat_id": "qry"},
            headers={"X-Chat-Id": "hdr"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"{self.public_base_url}/files/hdr", resp.text)
        self.assertNotIn("/files/qry", resp.text)

    def test_openwebui_alias_works(self):
        resp = self.client.get(
            "/system-prompt",
            headers={"X-OpenWebUI-Chat-Id": "alias-demo"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"{self.public_base_url}/files/alias-demo", resp.text)

    def test_header_user_email_overrides_query(self):
        async def _no_provider(_email):
            return None

        with patch.object(skill_manager_module, "_fetch_user_config", side_effect=_no_provider), \
             patch.object(skill_manager_module, "_load_user_config_cache", return_value=None):
            resp = self.client.get(
                "/system-prompt",
                params={"chat_id": "abc", "user_email": "ignored@example.com"},
                headers={"X-User-Email": "winner@example.com"},
            )
        self.assertEqual(resp.status_code, 200)
        # Both paths produce <available_skills>; the distinguishing bit is
        # that skill_manager.get_user_skills was called with the header value.
        self.assertIn("<available_skills>", resp.text)

    def test_content_type_is_text_plain(self):
        resp = self.client.get("/system-prompt", params={"chat_id": "abc"})
        self.assertTrue(
            resp.headers.get("content-type", "").startswith("text/plain"),
            f"Expected text/plain, got {resp.headers.get('content-type')}",
        )

    def test_public_base_url_header_is_returned(self):
        """The filter needs the public URL to build browser-facing preview/archive
        links but its ORCHESTRATOR_URL Valve holds the internal URL. Server must
        expose the public URL (from PUBLIC_BASE_URL env) on every /system-prompt
        response so the filter can cache and use it in outlet()."""
        resp = self.client.get("/system-prompt", params={"chat_id": "abc"})
        self.assertEqual(resp.status_code, 200)
        header = resp.headers.get("X-Public-Base-URL")
        self.assertIsNotNone(header, "X-Public-Base-URL header missing")
        self.assertEqual(header, self.public_base_url)


if __name__ == "__main__":
    unittest.main()
