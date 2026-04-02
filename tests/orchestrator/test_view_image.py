"""Tests for view() image processing path — Pillow 12 API and return structure.

Run: cd computer-use-server && python -m pytest ../tests/orchestrator/test_view_image.py -v
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'computer-use-server'))

from context_vars import current_chat_id

FAKE_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def _mock_container():
    c = MagicMock()
    c.id = "mock-container-id"
    c.name = "owui-chat-test"
    c.status = "running"
    return c


class TestViewImagePillow12Api(unittest.IsolatedAsyncioTestCase):
    """Verify that view() generates Pillow 12-compatible Python code (Image.Resampling.LANCZOS)."""

    def setUp(self):
        current_chat_id.set("test-chat")

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    @patch("mcp_tools._execute_bash")
    async def test_command_uses_resampling_lanczos(self, mock_exec, mock_container, mock_token):
        """The resize command sent to the container must use Image.Resampling.LANCZOS (Pillow 12 API)."""
        from mcp_tools import view

        captured = []

        def capture(container, cmd):
            captured.append(cmd)
            return {"output": FAKE_B64, "exit_code": 0}

        mock_exec.side_effect = capture
        await view("check api", "/tmp/image.png")

        self.assertTrue(captured, "Expected _execute_bash to be called for image file")
        cmd = captured[0]
        self.assertIn(
            "Image.Resampling.LANCZOS",
            cmd,
            "Pillow 12 requires Image.Resampling.LANCZOS — old Image.LANCZOS was removed",
        )

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    @patch("mcp_tools._execute_bash")
    async def test_command_does_not_use_deprecated_lanczos(self, mock_exec, mock_container, mock_token):
        """The resize command must NOT use the deprecated bare Image.LANCZOS attribute."""
        from mcp_tools import view

        captured = []

        def capture(container, cmd):
            captured.append(cmd)
            return {"output": FAKE_B64, "exit_code": 0}

        mock_exec.side_effect = capture
        await view("check api", "/tmp/photo.jpg")

        self.assertTrue(captured)
        cmd = captured[0]
        # Image.LANCZOS without .Resampling is the deprecated Pillow 11 attribute
        # It appears as ",Image.LANCZOS)" or " Image.LANCZOS)" — not as part of "Resampling.LANCZOS"
        import re
        deprecated = re.search(r'(?<!Resampling\.)Image\.LANCZOS', cmd)
        self.assertIsNone(
            deprecated,
            f"Deprecated Image.LANCZOS found in command (use Image.Resampling.LANCZOS): {cmd!r}",
        )


class TestViewImageReturnsStructuredContent(unittest.IsolatedAsyncioTestCase):
    """Verify the structured [text, image_url] return format for image files."""

    def setUp(self):
        current_chat_id.set("test-chat")

    def _make_exec_mock(self, b64=FAKE_B64, exit_code=0):
        return MagicMock(return_value={"output": b64, "exit_code": exit_code})

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    @patch("mcp_tools._execute_bash")
    async def test_png_returns_list_with_two_items(self, mock_exec, mock_container, mock_token):
        from mcp_tools import view
        mock_exec.side_effect = self._make_exec_mock()
        result = await view("view image", "/tmp/test.png")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    @patch("mcp_tools._execute_bash")
    async def test_first_item_is_text_type(self, mock_exec, mock_container, mock_token):
        from mcp_tools import view
        mock_exec.side_effect = self._make_exec_mock()
        result = await view("view image", "/tmp/test.png")
        self.assertEqual(result[0]["type"], "text")

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    @patch("mcp_tools._execute_bash")
    async def test_second_item_is_image_url_type(self, mock_exec, mock_container, mock_token):
        from mcp_tools import view
        mock_exec.side_effect = self._make_exec_mock()
        result = await view("view image", "/tmp/test.png")
        self.assertEqual(result[1]["type"], "image_url")

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    @patch("mcp_tools._execute_bash")
    async def test_image_url_is_data_uri(self, mock_exec, mock_container, mock_token):
        from mcp_tools import view
        mock_exec.side_effect = self._make_exec_mock()
        result = await view("view image", "/tmp/test.png")
        url = result[1]["image_url"]["url"]
        self.assertTrue(
            url.startswith("data:image/jpeg;base64,"),
            f"Expected data URI, got: {url[:60]}",
        )

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    @patch("mcp_tools._execute_bash")
    async def test_data_uri_contains_b64_payload(self, mock_exec, mock_container, mock_token):
        from mcp_tools import view
        mock_exec.side_effect = self._make_exec_mock(b64=FAKE_B64)
        result = await view("view image", "/tmp/test.png")
        url = result[1]["image_url"]["url"]
        self.assertIn(FAKE_B64, url)

    @patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock)
    @patch("mcp_tools._get_or_create_container", return_value=_mock_container())
    @patch("mcp_tools._execute_bash")
    async def test_container_failure_returns_error_string(self, mock_exec, mock_container, mock_token):
        """When the container command fails, view() must return a plain error string."""
        from mcp_tools import view
        mock_exec.side_effect = self._make_exec_mock(b64="Permission denied", exit_code=1)
        result = await view("view image", "/tmp/secret.png")
        self.assertIsInstance(result, str)
        self.assertIn("Error", result)


class TestViewImageExtensions(unittest.IsolatedAsyncioTestCase):
    """All declared image extensions must trigger image processing path, not text path."""

    def setUp(self):
        current_chat_id.set("test-chat")

    async def _check_ext(self, ext):
        from mcp_tools import view

        with patch("mcp_tools._ensure_gitlab_token", new_callable=AsyncMock), \
             patch("mcp_tools._get_or_create_container", return_value=_mock_container()), \
             patch("mcp_tools._execute_bash", return_value={"output": FAKE_B64, "exit_code": 0}):
            result = await view("view image", f"/tmp/file{ext}")

        self.assertIsInstance(
            result, list,
            f"Extension {ext!r} should return structured content list, got: {type(result).__name__}",
        )

    async def test_jpg_extension(self):
        await self._check_ext(".jpg")

    async def test_jpeg_extension(self):
        await self._check_ext(".jpeg")

    async def test_png_extension(self):
        await self._check_ext(".png")

    async def test_gif_extension(self):
        await self._check_ext(".gif")

    async def test_webp_extension(self):
        await self._check_ext(".webp")

    async def test_uppercase_png_extension(self):
        """Extension matching must be case-insensitive."""
        await self._check_ext(".PNG")

    async def test_uppercase_jpg_extension(self):
        await self._check_ext(".JPG")


if __name__ == "__main__":
    unittest.main()
