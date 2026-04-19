# SPDX-License-Identifier: BUSL-1.1
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


if __name__ == "__main__":
    unittest.main()
