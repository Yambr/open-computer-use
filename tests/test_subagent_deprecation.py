# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for SUB_AGENT_DEFAULT_MODEL deprecation warning in docker_manager.py.

Exercises the at-import-time deprecation warning introduced in Plan 01-04 Task 2.
Each test case forces a fresh import so the module-level guard fires each time.

Run: python -m pytest tests/test_subagent_deprecation.py -v
"""

import importlib
import io
import logging
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = str(ROOT / "computer-use-server")


def _fresh_import(env_overrides: dict) -> str:
    """Force a fresh import of docker_manager with given env vars.

    Returns the content captured from the 'docker_manager' logger at WARNING level.
    """
    # Patch env
    saved = {}
    for k, v in env_overrides.items():
        saved[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    # Capture log output
    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.WARNING)
    logger = logging.getLogger("docker_manager")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)

    try:
        if SERVER_DIR not in sys.path:
            sys.path.insert(0, SERVER_DIR)
        sys.modules.pop("docker_manager", None)
        try:
            import docker_manager  # noqa: F401
        except Exception:
            # Allow import errors from missing docker/etc — we only care about
            # the warning that fires before those imports complete.
            pass
        return log_buf.getvalue()
    finally:
        logger.removeHandler(handler)
        # Restore env
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        sys.modules.pop("docker_manager", None)


class TestSUBAgentDefaultModelDeprecation(unittest.TestCase):
    """SUB_AGENT_DEFAULT_MODEL deprecation warning fires at module import time."""

    def test_warning_fires_for_opencode(self):
        out = _fresh_import({
            "SUB_AGENT_DEFAULT_MODEL": "sonnet",
            "SUBAGENT_CLI": "opencode",
        })
        self.assertIn("deprecated", out.lower(),
                      f"Expected deprecation warning for opencode, got: {out!r}")

    def test_warning_fires_for_codex(self):
        out = _fresh_import({
            "SUB_AGENT_DEFAULT_MODEL": "sonnet",
            "SUBAGENT_CLI": "codex",
        })
        self.assertIn("deprecated", out.lower(),
                      f"Expected deprecation warning for codex, got: {out!r}")

    def test_no_warning_when_subagent_cli_is_claude(self):
        out = _fresh_import({
            "SUB_AGENT_DEFAULT_MODEL": "sonnet",
            "SUBAGENT_CLI": "claude",
        })
        self.assertNotIn("deprecated", out.lower(),
                         f"Unexpected deprecation warning for claude: {out!r}")

    def test_no_warning_when_subagent_cli_unset(self):
        out = _fresh_import({
            "SUB_AGENT_DEFAULT_MODEL": "sonnet",
            "SUBAGENT_CLI": None,
        })
        self.assertNotIn("deprecated", out.lower(),
                         f"Unexpected deprecation warning when SUBAGENT_CLI unset: {out!r}")

    def test_no_warning_when_env_not_set(self):
        out = _fresh_import({
            "SUB_AGENT_DEFAULT_MODEL": None,
            "SUBAGENT_CLI": "opencode",
        })
        self.assertNotIn("deprecated", out.lower(),
                         f"Unexpected deprecation warning when env unset: {out!r}")

    def test_warning_includes_cli_name(self):
        out = _fresh_import({
            "SUB_AGENT_DEFAULT_MODEL": "sonnet",
            "SUBAGENT_CLI": "opencode",
        })
        self.assertIn("opencode", out,
                      f"Warning should include CLI name 'opencode': {out!r}")

    def test_warning_includes_replacement_env(self):
        out = _fresh_import({
            "SUB_AGENT_DEFAULT_MODEL": "sonnet",
            "SUBAGENT_CLI": "opencode",
        })
        self.assertIn("OPENCODE_SUB_AGENT_DEFAULT_MODEL", out,
                      f"Warning should mention replacement env: {out!r}")


class TestDockerManagerStructure(unittest.TestCase):
    """Static source checks on docker_manager.py deprecation block."""

    def setUp(self):
        self.src = (ROOT / "computer-use-server" / "docker_manager.py").read_text()

    def test_legacy_global_preserved(self):
        assert 'SUB_AGENT_DEFAULT_MODEL = os.getenv("SUB_AGENT_DEFAULT_MODEL"' in self.src

    def test_deprecation_comment_present(self):
        assert "SUB_AGENT_DEFAULT_MODEL is deprecated" in self.src

    def test_warning_message_present(self):
        assert "deprecated for SUBAGENT_CLI" in self.src


if __name__ == "__main__":
    unittest.main()
