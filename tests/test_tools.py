# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for computer_use_tools (Open WebUI Tool).

Run: python -m pytest tests/test_tools.py -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "openwebui" / "tools"))

import computer_use_tools  # noqa: E402


class ValveSchema(unittest.TestCase):
    """v4.0.0: Tool Valve renamed FILE_SERVER_URL → ORCHESTRATOR_URL for
    consistency with the filter. Semantics unchanged — still the internal URL
    of the Computer Use server for MCP forwarding.
    """

    def test_orchestrator_url_valve_exists(self):
        valve_fields = set(computer_use_tools.Tools.Valves.model_fields.keys())
        self.assertIn("ORCHESTRATOR_URL", valve_fields)

    def test_file_server_url_valve_removed(self):
        valve_fields = set(computer_use_tools.Tools.Valves.model_fields.keys())
        self.assertNotIn("FILE_SERVER_URL", valve_fields)


class OrchestratorURLScheme(unittest.TestCase):
    """The orchestrator URL must be http(s).

    urllib honours ``file://``, ``ftp://`` and ``data://``, so a Valve holding
    one of those makes the health probe and the preflight read a local file and
    report the result as if it had come from the orchestrator. The check lives
    where the URL enters, so a scheme cannot reach any of the three call sites.
    """

    def _client(self, url):
        return computer_use_tools._MCPClient(url)

    def test_http_and_https_are_accepted(self):
        for url in ("http://orchestrator:8000", "https://orchestrator:8000"):
            with self.subTest(url=url):
                self._client(url)

    def test_file_scheme_is_refused(self):
        # The one that turns a network read into a local-file read.
        with self.assertRaises(ValueError) as caught:
            self._client("file:///etc/passwd")
        self.assertIn("file", str(caught.exception))

    def test_other_urllib_schemes_are_refused(self):
        for url in ("ftp://host/x", "data:text/plain,hi", "gopher://host/"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    self._client(url)

    def test_a_bare_host_without_a_scheme_is_refused(self):
        # urlparse reads `orchestrator:` as the scheme here, not as a host — so
        # this is refused for the same reason ftp:// is, and the operator gets a
        # message naming the Valve instead of a urlopen error far from here.
        with self.assertRaises(ValueError):
            self._client("orchestrator:8000/mcp")


class ResolveScopeSchemeGuard(unittest.TestCase):
    """`_resolve_chat_scope_sync` builds its own request and does not go
    through `_MCPClient`, so the constructor check alone left it open.

    It is the worse of the two paths: it catches every exception and degrades
    to the base scope, so a `file://` Valve would read a local file and any
    failure would look like an ordinary resolve miss.

    That degrade-on-anything behaviour is also why asserting the RETURN VALUE
    proves nothing here — without the guard, urlopen raises on the bad scheme
    and the method returns the base scope anyway. Every assertion below is
    bound to whether urlopen was REACHED, which is the thing the guard changes.
    """

    def _tools_with_url(self, url):
        tools = computer_use_tools.Tools()
        tools.valves.ORCHESTRATOR_URL = url
        tools.valves.OCU_FILESYSTEM_ID = "base-scope"
        return tools

    def _reached_urlopen(self, url):
        """Run the resolve path with urlopen instrumented; report if it ran."""
        import urllib.request

        original = urllib.request.urlopen
        seen = []

        def _record(req, *a, **kw):
            seen.append(getattr(req, "full_url", req))
            raise OSError("blocked by the test; the call itself is the signal")

        urllib.request.urlopen = _record
        try:
            scope = self._tools_with_url(url)._resolve_chat_scope_sync("chat-1")
        finally:
            urllib.request.urlopen = original
        return bool(seen), scope

    def test_a_refused_scheme_never_reaches_urlopen(self):
        for url in ("file:///etc/passwd", "ftp://host/x", "data:text/plain,hi"):
            with self.subTest(url=url):
                reached, scope = self._reached_urlopen(url)
                self.assertFalse(
                    reached,
                    f"{url} reached urlopen; the scheme guard did not run on "
                    "the resolve path, so a file:// Valve would read a local "
                    "file and the miss would look like any other miss",
                )
                self.assertEqual(scope, "base-scope")

    def test_an_http_url_does_reach_urlopen(self):
        # The control: without this, a guard that refused everything — or a
        # method that never issued a request at all — would pass the test above.
        reached, scope = self._reached_urlopen("http://orchestrator:8000")
        self.assertTrue(
            reached,
            "an http URL must still be attempted; if it is not, the assertion "
            "above is not about the scheme",
        )
        self.assertEqual(scope, "base-scope")


if __name__ == "__main__":
    unittest.main()
