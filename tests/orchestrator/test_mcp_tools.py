# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for MCP tools — output truncation, command semantics, uniqueness check.

Uses mock Docker to test tool logic without real containers.

Run: cd computer-use-server && python -m pytest ../tests/orchestrator/test_mcp_tools.py -v
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Add computer-use-server to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'computer-use-server'))

from context_vars import current_chat_id


def _mock_exec_result(output="", exit_code=0, success=True):
    """Create a mock execute_bash result."""
    return {"output": output, "exit_code": exit_code, "success": success}


def _mock_container():
    """Create a mock Docker container."""
    c = MagicMock()
    c.id = "mock-container-id"
    c.name = "owui-chat-test"
    c.status = "running"
    return c


class TestBashToolOutputTruncation(unittest.IsolatedAsyncioTestCase):
    """Tests for bash_tool output truncation (Claude Code best practice: maxResultSizeChars=30K)."""

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_large_output_is_truncated(self, mock_container, mock_token):
        """Output >30K chars should be truncated with head+tail and a message."""
        from mcp_tools import bash_tool
        current_chat_id.set("test-chat")
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()

        big_output = "x" * 60_000  # 60K chars
        with patch("mcp_tools.execute_bash_streaming",
                   return_value={"output": big_output, "exit_code": 0, "success": True}):
            result = await bash_tool("cat big_file", "read big file", ctx)

        self.assertIn("truncated", result.lower())
        self.assertLessEqual(len(result), 32_000)  # 30K + truncation message

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_short_output_not_truncated(self, mock_container, mock_token):
        """Output <30K chars should be returned as-is."""
        from mcp_tools import bash_tool
        current_chat_id.set("test-chat")
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()

        short_output = "hello world\n" * 100  # ~1.2K chars
        with patch("mcp_tools.execute_bash_streaming",
                   return_value={"output": short_output, "exit_code": 0, "success": True}):
            result = await bash_tool("echo hello", "test", ctx)

        self.assertEqual(result, short_output)
        self.assertNotIn("truncated", result.lower())


class TestBashToolCommandSemantics(unittest.IsolatedAsyncioTestCase):
    """Tests for command semantics (grep/find/diff exit code 1 != error)."""

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_grep_exit1_returns_no_matches(self, mock_container, mock_token):
        """grep exit code 1 should return 'No matches found', not an error."""
        from mcp_tools import bash_tool
        current_chat_id.set("test-chat")
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()

        with patch("mcp_tools.execute_bash_streaming",
                   return_value={"output": "", "exit_code": 1, "success": False}):
            result = await bash_tool("grep -r TODO /repo", "search", ctx)

        self.assertIn("No matches found", result)
        self.assertNotIn("Exit code", result)

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_grep_exit2_is_error(self, mock_container, mock_token):
        """grep exit code 2+ should be reported as error."""
        from mcp_tools import bash_tool
        current_chat_id.set("test-chat")
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()

        with patch("mcp_tools.execute_bash_streaming",
                   return_value={"output": "grep: invalid option", "exit_code": 2, "success": False}):
            result = await bash_tool("grep --bad-flag /repo", "search", ctx)

        self.assertIn("grep: invalid option", result)

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_diff_exit1_returns_files_differ(self, mock_container, mock_token):
        """diff exit code 1 should return 'Files differ', not an error."""
        from mcp_tools import bash_tool
        current_chat_id.set("test-chat")
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()

        with patch("mcp_tools.execute_bash_streaming",
                   return_value={"output": "", "exit_code": 1, "success": False}):
            result = await bash_tool("diff a.txt b.txt", "compare", ctx)

        self.assertIn("Files differ", result)
        self.assertNotIn("Exit code", result)

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_regular_command_exit1_is_error(self, mock_container, mock_token):
        """Non-semantic commands: exit code 1 remains an error."""
        from mcp_tools import bash_tool
        current_chat_id.set("test-chat")
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()

        with patch("mcp_tools.execute_bash_streaming",
                   return_value={"output": "", "exit_code": 1, "success": False}):
            result = await bash_tool("python3 script.py", "run script", ctx)

        self.assertIn("Exit code: 1", result)


class TestOutputSyncIntegration(unittest.IsolatedAsyncioTestCase):
    """Tests for appending Open WebUI-native file references to tool results."""

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_bash_tool_appends_synced_output_links(self, mock_container, mock_token):
        from mcp_tools import bash_tool
        current_chat_id.set("test-chat")
        ctx = MagicMock()
        ctx.report_progress = AsyncMock()

        with patch("mcp_tools.execute_bash_streaming",
                   return_value={"output": "done", "exit_code": 0, "success": True}), \
             patch("mcp_tools._sync_outputs_if_configured", new_callable=AsyncMock,
                   return_value=[{"filename": "hello.txt", "file_id": "file-1", "url": "/api/v1/files/file-1/content"}]):
            result = await bash_tool("echo hi", "test", ctx)

        self.assertIn("done", result)
        self.assertIn("Synced to Open WebUI", result)
        self.assertIn("/api/v1/files/file-1/content", result)


class TestViewTruncation(unittest.IsolatedAsyncioTestCase):
    """Tests for view output truncation at 30K (increased from 16K)."""

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_view_truncation_at_30k(self, mock_container, mock_token):
        """Output >30K should be truncated with head+tail."""
        from mcp_tools import view
        current_chat_id.set("test-chat")

        big_output = "line\n" * 10_000  # ~50K chars
        with patch("mcp_tools._execute_bash",
                   return_value={"output": big_output, "exit_code": 0}):
            result = await view("read big file", "/tmp/big.log")

        self.assertIn("truncated", result.lower())
        self.assertLessEqual(len(result), 32_000)

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_view_no_truncation_under_30k(self, mock_container, mock_token):
        """Output of 20K (between old 16K and new 30K) should NOT be truncated."""
        from mcp_tools import view
        current_chat_id.set("test-chat")

        # 20K chars -- above old 16K threshold but below new 30K
        normal_output = "x" * 20_000
        with patch("mcp_tools._execute_bash",
                   return_value={"output": normal_output, "exit_code": 0}):
            result = await view("read file", "/tmp/file.py")

        self.assertEqual(result, normal_output)
        self.assertNotIn("truncated", result.lower())


class TestStrReplaceUniqueness(unittest.IsolatedAsyncioTestCase):
    """Tests for str_replace uniqueness check."""

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_multiple_matches_returns_error(self, mock_container, mock_token):
        """str_replace should error when old_str appears multiple times."""
        from mcp_tools import str_replace
        current_chat_id.set("test-chat")

        # The Python script inside container should detect multiple occurrences
        error_output = "Error: Found 3 occurrences of old_str in /tmp/test.py. Add more context to make it unique."
        with patch("mcp_tools._execute_python_with_stdin",
                   return_value={"output": error_output, "exit_code": 1, "success": False}):
            result = await str_replace("fix", "print('hello')", "/tmp/test.py", "print('world')")

        self.assertIn("occurrences", result.lower())


class TestHelperFunctions(unittest.TestCase):
    """Tests for helper functions: _get_first_command, _apply_command_semantics, _truncate_output."""

    def test_get_first_command_simple(self):
        from mcp_tools import _get_first_command
        self.assertEqual(_get_first_command("grep -r TODO ."), "grep")

    def test_get_first_command_with_path(self):
        from mcp_tools import _get_first_command
        self.assertEqual(_get_first_command("/usr/bin/grep pattern"), "grep")

    def test_get_first_command_with_env_vars(self):
        from mcp_tools import _get_first_command
        self.assertEqual(_get_first_command("FOO=bar python3 script.py"), "python3")

    def test_get_first_command_with_sudo(self):
        from mcp_tools import _get_first_command
        self.assertEqual(_get_first_command("sudo grep pattern"), "grep")

    def test_truncate_output_short(self):
        from mcp_tools import _truncate_output
        self.assertEqual(_truncate_output("hello", 100), "hello")

    def test_truncate_output_long(self):
        from mcp_tools import _truncate_output
        result = _truncate_output("x" * 100, 50)
        self.assertIn("truncated", result.lower())
        self.assertLessEqual(len(result), 200)  # 50 + message overhead


if __name__ == "__main__":
    unittest.main()
