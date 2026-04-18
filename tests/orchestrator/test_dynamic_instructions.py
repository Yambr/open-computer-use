# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Tier 4 — InitializeResult.instructions must be dynamic per-request via the
current_instructions ContextVar.

The ContextVar-driven property lives on a subclass of the lowlevel MCP Server
that was swapped onto mcp._mcp_server after FastMCP(...) constructed it. This
test exercises the property directly rather than spinning up a full HTTP
InitializeRequest — cheaper, same load-bearing guarantee.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "computer-use-server"))

import mcp_tools  # noqa: E402
from context_vars import current_instructions  # noqa: E402


class DynamicInstructionsContract(unittest.TestCase):
    def test_class_was_swapped(self):
        self.assertEqual(
            mcp_tools.mcp._mcp_server.__class__.__name__,
            "_DynamicInstructionsServer",
            "mcp._mcp_server class swap did not happen at import time",
        )

    def test_static_fallback_when_contextvar_unset(self):
        # Sanity: with no ContextVar, we get the static string
        tok = current_instructions.set(None)
        try:
            v = mcp_tools.mcp._mcp_server.instructions
            self.assertIn("README.md", v)
            self.assertIn("prompts/get", v)
        finally:
            current_instructions.reset(tok)

    def test_contextvar_value_wins(self):
        tok = current_instructions.set("PER-CHAT-DEMO")
        try:
            self.assertEqual(
                mcp_tools.mcp._mcp_server.instructions,
                "PER-CHAT-DEMO",
            )
        finally:
            current_instructions.reset(tok)

    def test_distinct_contextvar_values_return_distinct_instructions(self):
        t1 = current_instructions.set("chat-alpha")
        try:
            a = mcp_tools.mcp._mcp_server.instructions
        finally:
            current_instructions.reset(t1)

        t2 = current_instructions.set("chat-beta")
        try:
            b = mcp_tools.mcp._mcp_server.instructions
        finally:
            current_instructions.reset(t2)

        self.assertEqual(a, "chat-alpha")
        self.assertEqual(b, "chat-beta")


if __name__ == "__main__":
    unittest.main()
