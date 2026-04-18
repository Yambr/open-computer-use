# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Tier 1 — MCP tool descriptions must mention README.md as the recovery hint.

Static `instructions=` kwarg on the FastMCP constructor (Tier 3 fallback)
must also mention README.md, prompts/get, and resources/list — the entry
points a confused client would otherwise miss.
"""
import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "computer-use-server"))

import mcp_tools  # noqa: E402


class ToolDescriptionsContract(unittest.TestCase):
    def test_bash_tool_description_mentions_readme(self):
        tools = asyncio.run(mcp_tools.mcp.list_tools())
        bash = next((t for t in tools if t.name == "bash_tool"), None)
        self.assertIsNotNone(bash, "bash_tool tool missing from tools/list")
        self.assertIn("README.md", bash.description)
        self.assertIn("/home/assistant", bash.description)

    def test_view_description_mentions_readme(self):
        tools = asyncio.run(mcp_tools.mcp.list_tools())
        view = next((t for t in tools if t.name == "view"), None)
        self.assertIsNotNone(view, "view tool missing from tools/list")
        self.assertIn("README.md", view.description)

    def test_static_instructions_mentions_three_channels(self):
        static = mcp_tools._STATIC_INSTRUCTIONS
        # Three fallback pointers a confused client needs
        self.assertIn("README.md", static)
        self.assertIn("prompts/get", static)
        self.assertIn("resources/list", static)

    def test_total_tool_count_unchanged_at_five(self):
        """We promised the user: 5 tools before, 5 tools after."""
        tools = asyncio.run(mcp_tools.mcp.list_tools())
        self.assertEqual(len(tools), 5, f"tool count drifted: {[t.name for t in tools]}")


if __name__ == "__main__":
    unittest.main()
