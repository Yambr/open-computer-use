# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Tier 5 — @mcp.prompt('system') primitive.

Uses FastMCP's in-process list_prompts / get_prompt to avoid the ASGI round
trip. Header → ContextVars is simulated directly via current_chat_id.set(...)
since MCPContextMiddleware is out of scope here — the prompt handler reads
ContextVars regardless of how they got populated.
"""
import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "computer-use-server"))

import mcp_tools  # noqa: E402
import mcp_prompts  # noqa: F401, E402 — registers the @mcp.prompt handler
import system_prompt as sp_module  # noqa: E402
from context_vars import current_chat_id  # noqa: E402


class McpPromptsContract(unittest.TestCase):
    def setUp(self):
        sp_module.invalidate_render_cache()

    def test_system_prompt_listed(self):
        prompts = asyncio.run(mcp_tools.mcp.list_prompts())
        names = [p.name for p in prompts]
        self.assertIn("system", names)

    def test_get_prompt_returns_user_message_with_chat_id(self):
        result = asyncio.run(
            mcp_tools.mcp.get_prompt("system", {"chat_id": "from-arg"})
        )
        self.assertTrue(len(result.messages) >= 1)
        msg = result.messages[0]
        self.assertEqual(msg.role, "user")
        self.assertIn("from-arg", msg.content.text)

    def test_header_wins_over_argument(self):
        tok = current_chat_id.set("from-header")
        try:
            result = asyncio.run(
                mcp_tools.mcp.get_prompt("system", {"chat_id": "from-arg-should-lose"})
            )
        finally:
            current_chat_id.reset(tok)
        body = result.messages[0].content.text
        self.assertIn("from-header", body)
        self.assertNotIn("from-arg-should-lose", body)

    def test_no_args_no_header_defaults(self):
        result = asyncio.run(mcp_tools.mcp.get_prompt("system", {}))
        body = result.messages[0].content.text
        self.assertIn("/files/default", body)


if __name__ == "__main__":
    unittest.main()
