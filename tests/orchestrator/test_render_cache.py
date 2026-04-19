# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
render_system_prompt is called on every MCP request (via MCPContextMiddleware
pre-render for Tier 4). It MUST NOT hit skill_manager's HTTP provider every
time. Pin the 60s (chat_id, user_email) cache behavior.
"""
import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "computer-use-server"))

import system_prompt  # noqa: E402


class RenderCacheContract(unittest.TestCase):
    def setUp(self):
        system_prompt.invalidate_render_cache()

    def test_same_key_hits_cache(self):
        calls = []

        async def _fake_uncached(chat_id, user_email):
            calls.append((chat_id, user_email))
            return f"rendered:{chat_id}:{user_email}"

        with patch.object(system_prompt, "_render_uncached", side_effect=_fake_uncached):
            t1 = asyncio.run(system_prompt.render_system_prompt("c1", "u@x"))
            t2 = asyncio.run(system_prompt.render_system_prompt("c1", "u@x"))

        self.assertEqual(t1, t2)
        self.assertEqual(len(calls), 1, "second call should hit cache")

    def test_different_key_misses_cache(self):
        async def _fake_uncached(chat_id, user_email):
            return f"rendered:{chat_id}:{user_email}"

        with patch.object(system_prompt, "_render_uncached", side_effect=_fake_uncached) as m:
            asyncio.run(system_prompt.render_system_prompt("c1", "u@x"))
            asyncio.run(system_prompt.render_system_prompt("c2", "u@x"))
            asyncio.run(system_prompt.render_system_prompt("c1", None))
        self.assertEqual(m.call_count, 3)

    def test_invalidate_drops_entry(self):
        calls = []

        async def _fake_uncached(chat_id, user_email):
            calls.append(1)
            return "x"

        with patch.object(system_prompt, "_render_uncached", side_effect=_fake_uncached):
            asyncio.run(system_prompt.render_system_prompt("c1", None))
            system_prompt.invalidate_render_cache("c1")
            asyncio.run(system_prompt.render_system_prompt("c1", None))

        self.assertEqual(len(calls), 2, "invalidate_render_cache('c1') must drop the cached entry")

    def test_ttl_expires(self):
        calls = []

        async def _fake_uncached(chat_id, user_email):
            calls.append(1)
            return "y"

        real_ttl = system_prompt._RENDER_TTL_SECONDS
        try:
            system_prompt._RENDER_TTL_SECONDS = 0.01  # 10ms for the test
            with patch.object(system_prompt, "_render_uncached", side_effect=_fake_uncached):
                asyncio.run(system_prompt.render_system_prompt("c1", None))
                time.sleep(0.05)
                asyncio.run(system_prompt.render_system_prompt("c1", None))
        finally:
            system_prompt._RENDER_TTL_SECONDS = real_ttl

        self.assertEqual(len(calls), 2, "entry must be re-rendered after TTL")


if __name__ == "__main__":
    unittest.main()
