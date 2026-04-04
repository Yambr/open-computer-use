# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for single-user mode and default chat_id fallback.

Three modes via SINGLE_USER_MODE env var:
- Not set (default): lenient — use 'default' container + warning in response
- true: single-user — always 'default', no warnings
- false: strict multi-user — error if no X-Chat-Id

Run: cd computer-use-server && python -m pytest ../tests/orchestrator/test_single_user_mode.py -v
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'computer-use-server'))

from context_vars import current_chat_id


def _mock_container():
    """Create a mock Docker container."""
    c = MagicMock()
    c.id = "mock-container-id"
    c.name = "owui-chat-default"
    c.status = "running"
    return c


class TestValidateChatId(unittest.TestCase):
    """Tests for _validate_chat_id() with different SINGLE_USER_MODE values."""

    def test_lenient_mode_no_chat_id_returns_default(self):
        """Default mode (SINGLE_USER_MODE unset) + no chat_id → returns 'default', no error."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SINGLE_USER_MODE", None)
            # Re-import to pick up new env
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("default")
            chat_id, error = mcp_tools._validate_chat_id()
            self.assertEqual(chat_id, "default")
            self.assertIsNone(error)

    def test_lenient_mode_with_chat_id_returns_it(self):
        """Default mode + chat_id present → returns that chat_id, no error."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SINGLE_USER_MODE", None)
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("my-session-123")
            chat_id, error = mcp_tools._validate_chat_id()
            self.assertEqual(chat_id, "my-session-123")
            self.assertIsNone(error)

    def test_single_user_mode_always_returns_default(self):
        """SINGLE_USER_MODE=true → always 'default', even if chat_id was set."""
        with patch.dict(os.environ, {"SINGLE_USER_MODE": "true"}, clear=False):
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("should-be-ignored")
            chat_id, error = mcp_tools._validate_chat_id()
            self.assertEqual(chat_id, "default")
            self.assertIsNone(error)

    def test_single_user_mode_no_chat_id(self):
        """SINGLE_USER_MODE=true + no chat_id → 'default', no error."""
        with patch.dict(os.environ, {"SINGLE_USER_MODE": "true"}, clear=False):
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("default")
            chat_id, error = mcp_tools._validate_chat_id()
            self.assertEqual(chat_id, "default")
            self.assertIsNone(error)

    def test_multi_user_mode_no_chat_id_returns_error(self):
        """SINGLE_USER_MODE=false + no chat_id → error."""
        with patch.dict(os.environ, {"SINGLE_USER_MODE": "false"}, clear=False):
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("default")
            chat_id, error = mcp_tools._validate_chat_id()
            self.assertEqual(chat_id, "default")
            self.assertIsNotNone(error)
            self.assertIn("required", error.lower())

    def test_multi_user_mode_with_chat_id_works(self):
        """SINGLE_USER_MODE=false + chat_id present → normal, no error."""
        with patch.dict(os.environ, {"SINGLE_USER_MODE": "false"}, clear=False):
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("user-session-456")
            chat_id, error = mcp_tools._validate_chat_id()
            self.assertEqual(chat_id, "user-session-456")
            self.assertIsNone(error)


class TestDefaultChatWarning(unittest.TestCase):
    """Tests for _get_default_chat_warning() helper."""

    def test_lenient_mode_default_chat_returns_warning(self):
        """Default mode + default chat_id → returns warning text."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SINGLE_USER_MODE", None)
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("default")
            warning = mcp_tools._get_default_chat_warning()
            self.assertIn("SINGLE_USER_MODE", warning)
            self.assertIn("X-Chat-Id", warning)

    def test_lenient_mode_real_chat_no_warning(self):
        """Default mode + real chat_id → no warning."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SINGLE_USER_MODE", None)
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("real-session")
            warning = mcp_tools._get_default_chat_warning()
            self.assertEqual(warning, "")

    def test_single_user_mode_no_warning(self):
        """SINGLE_USER_MODE=true → no warning ever."""
        with patch.dict(os.environ, {"SINGLE_USER_MODE": "true"}, clear=False):
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("default")
            warning = mcp_tools._get_default_chat_warning()
            self.assertEqual(warning, "")

    def test_multi_user_mode_no_warning(self):
        """SINGLE_USER_MODE=false → no warning (error handled separately)."""
        with patch.dict(os.environ, {"SINGLE_USER_MODE": "false"}, clear=False):
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("default")
            warning = mcp_tools._get_default_chat_warning()
            self.assertEqual(warning, "")


class TestBashToolSingleUserMode(unittest.IsolatedAsyncioTestCase):
    """Integration: bash_tool appends warning in lenient mode."""

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_bash_tool_lenient_mode_appends_warning(self, mock_container, mock_token):
        """bash_tool with default chat_id in lenient mode → result + warning."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SINGLE_USER_MODE", None)
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("default")
            ctx = MagicMock()
            ctx.report_progress = AsyncMock()

            with patch("mcp_tools.execute_bash_streaming",
                       return_value={"output": "hello\n", "exit_code": 0, "success": True}):
                result = await mcp_tools.bash_tool("echo hello", "test", ctx)

            self.assertIn("hello", result)
            self.assertIn("SINGLE_USER_MODE", result)

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_bash_tool_single_user_no_warning(self, mock_container, mock_token):
        """bash_tool with SINGLE_USER_MODE=true → result without warning."""
        with patch.dict(os.environ, {"SINGLE_USER_MODE": "true"}, clear=False):
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("default")
            ctx = MagicMock()
            ctx.report_progress = AsyncMock()

            with patch("mcp_tools.execute_bash_streaming",
                       return_value={"output": "hello\n", "exit_code": 0, "success": True}):
                result = await mcp_tools.bash_tool("echo hello", "test", ctx)

            self.assertIn("hello", result)
            self.assertNotIn("SINGLE_USER_MODE", result)

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    async def test_bash_tool_multi_user_no_chat_id_returns_error(self, mock_container, mock_token):
        """bash_tool with SINGLE_USER_MODE=false + no chat_id → error."""
        with patch.dict(os.environ, {"SINGLE_USER_MODE": "false"}, clear=False):
            import importlib
            import mcp_tools
            importlib.reload(mcp_tools)
            current_chat_id.set("default")
            ctx = MagicMock()
            ctx.report_progress = AsyncMock()

            result = await mcp_tools.bash_tool("echo hello", "test", ctx)

            self.assertIn("required", result.lower())
            self.assertNotIn("hello", result)


if __name__ == "__main__":
    unittest.main()
