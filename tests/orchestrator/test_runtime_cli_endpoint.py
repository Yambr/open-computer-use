# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Phase 9.5 — pin the /api/runtime/cli endpoint contract.

The endpoint surfaces the resolved SUBAGENT_CLI plus the per-CLI default
model so the Preview SPA can render an active-CLI badge. Pure additive,
no auth — but the shape MUST stay byte-stable because the SPA falls back
silently on missing fields.

Contract:
  GET /api/runtime/cli -> 200
  body.cli            in {"claude", "codex", "opencode"}
  body.default_model  non-empty string
  body.supports_cost  bool, true ONLY for claude
  Cache-Control: no-store
  Method allowlist: GET only (HEAD/POST/PUT/DELETE -> 405)
"""

import sys
import unittest
from importlib import reload
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "computer-use-server"))

# The full server stack (mcp, pptx, docx, ...) is heavy and not installed
# in every dev venv. Skip cleanly if any server import fails — CI has the
# full requirements installed and will exercise the contract there.
pytest.importorskip("mcp", reason="server stack not available in this venv")
pytest.importorskip("httpx", reason="fastapi.testclient needs httpx")

from fastapi.testclient import TestClient  # noqa: E402


def _client_with_cli(cli: str) -> TestClient:
    """Reload docker_manager + app under SUBAGENT_CLI=<cli> and return a TestClient.

    docker_manager reads SUBAGENT_CLI at import time (module-load validation
    is a project invariant — see Pitfall E in cli_runtime RESEARCH.md), so
    the env var must be patched before the module is imported. We use a
    single env patch + reload pair per CLI value.
    """
    with patch.dict("os.environ", {"SUBAGENT_CLI": cli}, clear=False):
        import docker_manager  # noqa: F401
        reload(docker_manager)
        # cli_runtime binds `from docker_manager import SUBAGENT_CLI` at
        # import time — must reload after docker_manager so resolve_cli()
        # sees the patched value, not the first-import snapshot.
        import cli_runtime
        reload(cli_runtime)
        import app as app_module
        reload(app_module)
        return TestClient(app_module.app)


class RuntimeCliEndpointContract(unittest.TestCase):

    def test_default_claude(self):
        client = _client_with_cli("claude")
        resp = client.get("/api/runtime/cli")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["cli"], "claude")
        self.assertTrue(body["default_model"], "default_model must be non-empty")
        self.assertIs(body["supports_cost"], True)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")

    def test_codex(self):
        # Phase 2: codex has no hardcoded default — without
        # CODEX_SUB_AGENT_DEFAULT_MODEL env, default_model is null. The
        # endpoint surfaces this as None instead of crashing on the
        # ValueError raised by resolve_subagent_model.
        client = _client_with_cli("codex")
        body = client.get("/api/runtime/cli").json()
        self.assertEqual(body["cli"], "codex")
        self.assertIs(body["supports_cost"], False)
        self.assertIsNone(body["default_model"])

    def test_opencode(self):
        # Phase 2: opencode has no hardcoded default — without
        # OPENCODE_SUB_AGENT_DEFAULT_MODEL env, default_model is null.
        client = _client_with_cli("opencode")
        body = client.get("/api/runtime/cli").json()
        self.assertEqual(body["cli"], "opencode")
        self.assertIs(body["supports_cost"], False)
        self.assertIsNone(body["default_model"])

    def test_method_allowlist(self):
        client = _client_with_cli("claude")
        self.assertEqual(client.post("/api/runtime/cli").status_code, 405)
        self.assertEqual(client.put("/api/runtime/cli").status_code, 405)
        self.assertEqual(client.delete("/api/runtime/cli").status_code, 405)

    def test_response_shape_is_minimal(self):
        """No leaked internals — only the three documented keys."""
        client = _client_with_cli("claude")
        body = client.get("/api/runtime/cli").json()
        self.assertEqual(set(body.keys()), {"cli", "default_model", "supports_cost"})


if __name__ == "__main__":
    unittest.main()
