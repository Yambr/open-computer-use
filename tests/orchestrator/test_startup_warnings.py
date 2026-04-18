# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for server startup warnings.

Covers #59: emit a one-time warning when PUBLIC_BASE_URL is still the
hardcoded internal-DNS default, to catch the #43-class "preview panel
never appears" misconfiguration at boot instead of in silent production
failure.

Run: cd computer-use-server && python -m pytest ../tests/orchestrator/test_startup_warnings.py -v
"""

import io
import os
import sys
import unittest
import importlib
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'computer-use-server'))


def _reload_docker_manager():
    """Re-import docker_manager after env changes so module-level PUBLIC_BASE_URL
    picks up the new value. Returns the freshly loaded module."""
    # Pop any previously imported version so os.getenv is re-evaluated.
    for mod in list(sys.modules):
        if mod == "docker_manager" or mod.startswith("docker_manager."):
            del sys.modules[mod]
    return importlib.import_module("docker_manager")


class PublicBaseUrlDefaultWarning(unittest.TestCase):
    """#59: warn_if_public_base_url_is_default() fires iff PUBLIC_BASE_URL is unset."""

    def setUp(self):
        self._saved = os.environ.get("PUBLIC_BASE_URL")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("PUBLIC_BASE_URL", None)
        else:
            os.environ["PUBLIC_BASE_URL"] = self._saved

    def test_warns_when_env_unset(self):
        os.environ.pop("PUBLIC_BASE_URL", None)
        dm = _reload_docker_manager()
        self.assertEqual(dm.PUBLIC_BASE_URL, dm.PUBLIC_BASE_URL_DEFAULT)
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitted = dm.warn_if_public_base_url_is_default()
        self.assertTrue(emitted)
        out = buf.getvalue()
        self.assertIn("PUBLIC_BASE_URL is still the hardcoded default", out)
        self.assertIn(dm.PUBLIC_BASE_URL_DEFAULT, out)
        self.assertIn("openwebui-filter.md", out)

    def test_silent_when_user_overrides_to_custom_url(self):
        os.environ["PUBLIC_BASE_URL"] = "http://myhost.example.com:8081"
        dm = _reload_docker_manager()
        self.assertEqual(dm.PUBLIC_BASE_URL, "http://myhost.example.com:8081")
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitted = dm.warn_if_public_base_url_is_default()
        self.assertFalse(emitted)
        self.assertEqual(buf.getvalue(), "")

    def test_warns_when_env_explicitly_set_to_default_value(self):
        """Matches the exact default string — still warns. The symptom is the
        value, not the mechanism (unset vs explicit)."""
        os.environ["PUBLIC_BASE_URL"] = "http://computer-use-server:8081"
        dm = _reload_docker_manager()
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitted = dm.warn_if_public_base_url_is_default()
        self.assertTrue(emitted)


class McpApiKeyMissingWarning(unittest.TestCase):
    """warn_if_mcp_api_key_missing() fires iff MCP_API_KEY is empty/unset.

    An empty key leaves /mcp endpoints unauthenticated — fine for local dev,
    dangerous for anything reachable from the internet.
    """

    def setUp(self):
        self._saved = os.environ.get("MCP_API_KEY")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("MCP_API_KEY", None)
        else:
            os.environ["MCP_API_KEY"] = self._saved

    def test_warns_when_env_unset(self):
        os.environ.pop("MCP_API_KEY", None)
        dm = _reload_docker_manager()
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitted = dm.warn_if_mcp_api_key_missing()
        self.assertTrue(emitted)
        self.assertIn("MCP_API_KEY is empty", buf.getvalue())

    def test_warns_when_env_empty_string(self):
        os.environ["MCP_API_KEY"] = ""
        dm = _reload_docker_manager()
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitted = dm.warn_if_mcp_api_key_missing()
        self.assertTrue(emitted)

    def test_silent_when_key_set(self):
        os.environ["MCP_API_KEY"] = "a-long-random-token"
        dm = _reload_docker_manager()
        buf = io.StringIO()
        with redirect_stdout(buf):
            emitted = dm.warn_if_mcp_api_key_missing()
        self.assertFalse(emitted)
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
