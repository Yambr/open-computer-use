# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Tier 6 — uploaded files as MCP resources.

Exercises:
  - sync_chat_resources + list_resources for flat and nested paths
  - read_resource returning text for text/*, bytes for everything else
  - tenancy: a fresh chat has no inherited resources
  - idempotent re-sync (no duplicate registrations)
  - concurrency safety: sync while list_resources iterates
"""
import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


class McpResourcesContract(unittest.TestCase):
    """Needs BASE_DATA_DIR set BEFORE uploads/mcp_resources are imported."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="ocu-resource-test-")
        os.environ["BASE_DATA_DIR"] = cls._tmp

        sys.path.insert(0, str(ROOT / "computer-use-server"))
        # Fresh imports so BASE_DATA_DIR is picked up
        import uploads as uploads_mod
        import importlib
        importlib.reload(uploads_mod)

        import mcp_tools  # noqa: F401 — the singleton
        import mcp_resources as mr
        importlib.reload(mr)

        cls.mcp_tools = mcp_tools
        cls.mcp_resources = mr
        cls.uploads = uploads_mod

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _make_upload(self, chat_id: str, rel_path: str, content: str):
        target = Path(self._tmp) / chat_id / "uploads" / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def test_flat_and_nested_list_read(self):
        self._make_upload("demoa", "hello.txt", "hi")
        self._make_upload("demoa", "sub/nested.json", '{"k":1}')
        n = asyncio.run(self.mcp_resources.sync_chat_resources("demoa"))
        self.assertEqual(n, 2)

        resources = asyncio.run(self.mcp_tools.mcp.list_resources())
        uris = {str(r.uri) for r in resources}
        self.assertIn("file://uploads/demoa/hello.txt", uris)
        self.assertIn("file://uploads/demoa/sub%2Fnested.json", uris)

        from pydantic import AnyUrl
        flat = list(asyncio.run(self.mcp_tools.mcp.read_resource(
            AnyUrl("file://uploads/demoa/hello.txt"))))
        self.assertEqual(flat[0].content, "hi")
        nested = list(asyncio.run(self.mcp_tools.mcp.read_resource(
            AnyUrl("file://uploads/demoa/sub%2Fnested.json"))))
        self.assertEqual(nested[0].content, '{"k":1}')

    def test_tenancy_empty_for_unknown_chat(self):
        # Plant a real upload for tenant A so the global resource registry
        # has at least one entry. Then assert tenant B sees ZERO resources
        # AND the registry-level list contains tenant A's URI but not any
        # tenant-B URI — proves there is no leak across chats via the
        # shared FastMCP._resource_manager._resources dict.
        self._make_upload("tenant-a", "secret.txt", "A-only")
        asyncio.run(self.mcp_resources.sync_chat_resources("tenant-a"))

        n = asyncio.run(self.mcp_resources.sync_chat_resources("tenant-b"))
        self.assertEqual(n, 0)

        all_uris = {
            str(r.uri) for r in asyncio.run(self.mcp_tools.mcp.list_resources())
        }
        # Tenant A's resource must still be present (sync_chat_resources(B)
        # must not have wiped A).
        self.assertIn("file://uploads/tenant-a/secret.txt", all_uris)
        # And NO resource URI should mention tenant-b.
        leaked = [u for u in all_uris if "tenant-b" in u]
        self.assertEqual(leaked, [], f"tenant-b leaked URIs: {leaked}")

    def test_idempotent_resync(self):
        self._make_upload("demob", "once.txt", "only")
        asyncio.run(self.mcp_resources.sync_chat_resources("demob"))
        asyncio.run(self.mcp_resources.sync_chat_resources("demob"))
        resources = asyncio.run(self.mcp_tools.mcp.list_resources())
        demob_uris = [r for r in resources if "demob" in str(r.uri)]
        self.assertEqual(len(demob_uris), 1, "re-sync must not duplicate entries")

    def test_concurrent_sync_and_list(self):
        """Stress: sync + list in parallel. Without the lock around the
        clear-then-rebuild, `dict changed size during iteration` fires."""
        self._make_upload("democ", "a.txt", "A")
        self._make_upload("democ", "b.txt", "B")

        async def _stress():
            await self.mcp_resources.sync_chat_resources("democ")
            tasks = []
            for _ in range(20):
                tasks.append(self.mcp_resources.sync_chat_resources("democ"))
                tasks.append(self.mcp_tools.mcp.list_resources())
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    raise r
            return len(results)

        n = asyncio.run(_stress())
        self.assertEqual(n, 40)

    def test_list_changed_notification_skipped_outside_request_context(self):
        """sync_chat_resources is called from docker_manager._create_container
        on a worker thread — no `request_ctx` is set, and we must NOT blow up.
        Notification is silently skipped; fresh list still surfaces on the
        next resources/list call."""
        self._make_upload("demod", "skip.txt", "no ctx")
        # Confirm we actually have no request context right now
        from mcp.server.lowlevel.server import request_ctx
        self.assertRaises(LookupError, request_ctx.get)
        # Should not raise — graceful skip of the notification branch
        n = asyncio.run(self.mcp_resources.sync_chat_resources("demod"))
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
