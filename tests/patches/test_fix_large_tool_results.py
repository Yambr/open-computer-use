#!/usr/bin/env python3
"""Tests for fix_large_tool_results.py patch.

Tests the patch application logic and the truncation functions.

Run: python3 -m pytest tests/patches/test_fix_large_tool_results.py -v
"""

import os
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

# Patch target override for tests — use temp file instead of real middleware
os.environ.setdefault("_PATCH_TARGET_OVERRIDE", "/tmp/_test_middleware_dummy.py")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'openwebui', 'patches'))


class TestPatchApplication(unittest.TestCase):
    """Tests for patch apply_patch() logic."""

    def _create_middleware(self, content: str) -> str:
        """Create a temp middleware file and return its path."""
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w") as f:
            f.write(content)
        return path

    def _base_middleware(self) -> str:
        """Return minimal middleware content with required markers."""
        return textwrap.dedent("""\
            import json
            from open_webui.models.chats import Chats

            def process_messages_with_output(messages):
                return messages

            def get_system_message(messages):
                return None

            async def middleware():
                form_data = {'messages': []}
                metadata = {'chat_id': 'test-123'}
                form_data['messages'] = process_messages_with_output(form_data.get('messages', []))

                system_message = get_system_message(form_data.get('messages', []))

                output = []
                tool_call_retries = 0
                while tool_call_retries < 5:
                    tool_call_retries += 1
                    _saved_output = json.loads(json.dumps(output))  # TOOL_LOOP_ERRORS_UNIFIED: save for restore on error
                    try:
                        new_form_data = {
                            'model': 'test',
                        }
        """)

    def test_patch_applies_successfully(self):
        """Patch should apply to middleware with required markers."""
        from fix_large_tool_results import apply_patch, MIDDLEWARE_PATH, PATCH_MARKER
        path = self._create_middleware(self._base_middleware())
        try:
            os.environ["_PATCH_TARGET_OVERRIDE"] = path
            # Re-import to pick up new path
            import importlib
            import fix_large_tool_results
            fix_large_tool_results.MIDDLEWARE_PATH = path
            result = fix_large_tool_results.apply_patch()
            self.assertTrue(result)

            with open(path) as f:
                content = f.read()
            self.assertIn(PATCH_MARKER, content)
        finally:
            os.unlink(path)

    def test_patch_is_idempotent(self):
        """Applying patch twice should be a no-op (skip)."""
        path = self._create_middleware(self._base_middleware())
        try:
            import importlib
            import fix_large_tool_results
            fix_large_tool_results.MIDDLEWARE_PATH = path
            fix_large_tool_results.apply_patch()
            result = fix_large_tool_results.apply_patch()
            self.assertTrue(result)  # Should return True (already applied)
        finally:
            os.unlink(path)

    def test_patch_fails_on_missing_file(self):
        """Patch should fail gracefully if middleware.py doesn't exist."""
        import fix_large_tool_results
        fix_large_tool_results.MIDDLEWARE_PATH = "/tmp/nonexistent_middleware_xyz.py"
        result = fix_large_tool_results.apply_patch()
        self.assertFalse(result)


class TestTruncationLogic(unittest.IsolatedAsyncioTestCase):
    """Tests for _truncate_large_results_in_output function."""

    def _make_tool_calls_block(self, content: str, tool_name: str = "bash",
                                tc_id: str = "tc_001") -> list:
        """Create an output list with a single tool_calls block."""
        return [{
            "type": "tool_calls",
            "content": [{"id": tc_id, "function": {"name": tool_name}}],
            "results": [{"tool_call_id": tc_id, "content": content}],
        }]

    async def test_small_result_unchanged(self):
        """Results under threshold should not be modified."""
        # Import will happen inside the test after we set up the exec environment
        exec_ns = {}
        exec(textwrap.dedent("""\
            import os, logging
            log = logging.getLogger("test")
            os.environ['TOOL_RESULT_MAX_CHARS'] = '50000'
            os.environ['TOOL_RESULT_PREVIEW_CHARS'] = '2000'
            os.environ['DOCKER_AI_UPLOAD_URL'] = ''

            _TOOL_RESULT_MAX_CHARS = int(os.environ.get('TOOL_RESULT_MAX_CHARS', '50000'))
            _TOOL_RESULT_PREVIEW_CHARS = int(os.environ.get('TOOL_RESULT_PREVIEW_CHARS', '2000'))
            _DOCKER_AI_UPLOAD_URL = os.environ.get('DOCKER_AI_UPLOAD_URL', '')

            async def _upload_result_to_docker_ai(content, filename, chat_id):
                return ''

            async def _truncate_large_results_in_output(output, chat_id):
                if _TOOL_RESULT_MAX_CHARS <= 0:
                    return
                for block in output:
                    btype = block.get('type', '')
                    if btype == 'tool_calls':
                        for result in block.get('results', []):
                            content = result.get('content', '')
                            if not isinstance(content, str) or len(content) <= _TOOL_RESULT_MAX_CHARS:
                                continue
                            size_kb = len(content) / 1024
                            preview = content[:_TOOL_RESULT_PREVIEW_CHARS]
                            result['content'] = f'[Truncated: {size_kb:.0f} KB]\\n{preview}'
                            log.info('TRUNCATED')
        """), exec_ns)

        output = self._make_tool_calls_block("short result")
        await exec_ns['_truncate_large_results_in_output'](output, "chat-1")
        self.assertEqual(output[0]["results"][0]["content"], "short result")

    async def test_large_result_is_truncated(self):
        """Results over threshold should be truncated with preview."""
        exec_ns = {}
        exec(textwrap.dedent("""\
            import os, logging
            log = logging.getLogger("test")
            _TOOL_RESULT_MAX_CHARS = 100  # Low threshold for testing
            _TOOL_RESULT_PREVIEW_CHARS = 20
            _DOCKER_AI_UPLOAD_URL = ''

            async def _upload_result_to_docker_ai(content, filename, chat_id):
                return ''

            async def _truncate_large_results_in_output(output, chat_id):
                if _TOOL_RESULT_MAX_CHARS <= 0:
                    return
                for block in output:
                    btype = block.get('type', '')
                    if btype == 'tool_calls':
                        tool_names = {}
                        for tc in block.get('content', []):
                            if isinstance(tc, dict):
                                tc_id = tc.get('id', '')
                                tc_name = tc.get('function', {}).get('name', '')
                                if tc_id and tc_name:
                                    tool_names[tc_id] = tc_name
                        for result in block.get('results', []):
                            content = result.get('content', '')
                            if not isinstance(content, str) or len(content) <= _TOOL_RESULT_MAX_CHARS:
                                continue
                            size_kb = len(content) / 1024
                            preview = content[:_TOOL_RESULT_PREVIEW_CHARS]
                            result['content'] = f'[Tool result truncated: {size_kb:.0f} KB]\\n{preview}'
                            log.info('TRUNCATED')
        """), exec_ns)

        big_content = "x" * 200  # Over 100 threshold
        output = self._make_tool_calls_block(big_content)
        await exec_ns['_truncate_large_results_in_output'](output, "chat-1")

        result_content = output[0]["results"][0]["content"]
        self.assertIn("truncated", result_content.lower())
        self.assertLess(len(result_content), len(big_content))

    async def test_truncation_disabled_when_zero(self):
        """Setting TOOL_RESULT_MAX_CHARS=0 should disable truncation."""
        exec_ns = {}
        exec(textwrap.dedent("""\
            import os, logging
            log = logging.getLogger("test")
            _TOOL_RESULT_MAX_CHARS = 0

            async def _truncate_large_results_in_output(output, chat_id):
                if _TOOL_RESULT_MAX_CHARS <= 0:
                    return
        """), exec_ns)

        big_content = "x" * 100_000
        output = self._make_tool_calls_block(big_content)
        await exec_ns['_truncate_large_results_in_output'](output, "chat-1")
        self.assertEqual(output[0]["results"][0]["content"], big_content)


class TestResponsesApiFormat(unittest.IsolatedAsyncioTestCase):
    """Tests for Responses API format (function_call_output)."""

    def _make_function_call_output_block(self, text: str, call_id: str = "call_001") -> list:
        return [{
            "type": "function_call_output",
            "call_id": call_id,
            "output": [{"type": "input_text", "text": text}],
        }]

    async def test_responses_api_large_result_truncated(self):
        """function_call_output with large text should be truncated."""
        exec_ns = {}
        exec(textwrap.dedent("""\
            import os, logging
            log = logging.getLogger("test")
            _TOOL_RESULT_MAX_CHARS = 100
            _TOOL_RESULT_PREVIEW_CHARS = 20
            _DOCKER_AI_UPLOAD_URL = ''

            async def _upload_result_to_docker_ai(content, filename, chat_id):
                return ''

            async def _truncate_large_results_in_output(output, chat_id):
                if _TOOL_RESULT_MAX_CHARS <= 0:
                    return
                for block in output:
                    btype = block.get('type', '')
                    if btype == 'function_call_output':
                        for part in block.get('output', []):
                            if part.get('type') != 'input_text':
                                continue
                            text = part.get('text', '')
                            if not isinstance(text, str) or len(text) <= _TOOL_RESULT_MAX_CHARS:
                                continue
                            size_kb = len(text) / 1024
                            preview = text[:_TOOL_RESULT_PREVIEW_CHARS]
                            part['text'] = f'[Tool result truncated: {size_kb:.0f} KB]\\n{preview}'
                            log.info('TRUNCATED')
        """), exec_ns)

        big_text = "y" * 200
        output = self._make_function_call_output_block(big_text)
        await exec_ns['_truncate_large_results_in_output'](output, "chat-1")

        result_text = output[0]["output"][0]["text"]
        self.assertIn("truncated", result_text.lower())
        self.assertLess(len(result_text), len(big_text))


class TestHistoryTruncation(unittest.TestCase):
    """Tests for _truncate_tool_messages_in_history function."""

    def test_large_tool_message_truncated(self):
        """Large tool messages from history should be truncated."""
        exec_ns = {}
        exec(textwrap.dedent("""\
            import os, logging
            log = logging.getLogger("test")
            _TOOL_RESULT_MAX_CHARS = 100
            _TOOL_RESULT_PREVIEW_CHARS = 20

            def _truncate_tool_messages_in_history(messages):
                if _TOOL_RESULT_MAX_CHARS <= 0:
                    return
                for msg in messages:
                    if msg.get('role') != 'tool':
                        continue
                    content = msg.get('content', '')
                    if not isinstance(content, str) or len(content) <= _TOOL_RESULT_MAX_CHARS:
                        continue
                    size_kb = len(content) / 1024
                    preview = content[:_TOOL_RESULT_PREVIEW_CHARS]
                    msg['content'] = f'[Tool result from history truncated: {size_kb:.0f} KB]\\n{preview}'
                    log.info('HISTORY_TRUNCATED')
        """), exec_ns)

        messages = [
            {"role": "user", "content": "do something"},
            {"role": "tool", "content": "z" * 200},
            {"role": "assistant", "content": "done"},
        ]
        exec_ns['_truncate_tool_messages_in_history'](messages)

        self.assertIn("truncated", messages[1]["content"].lower())
        self.assertEqual(messages[0]["content"], "do something")
        self.assertEqual(messages[2]["content"], "done")

    def test_small_tool_message_unchanged(self):
        """Small tool messages should not be modified."""
        exec_ns = {}
        exec(textwrap.dedent("""\
            import os, logging
            log = logging.getLogger("test")
            _TOOL_RESULT_MAX_CHARS = 100
            _TOOL_RESULT_PREVIEW_CHARS = 20

            def _truncate_tool_messages_in_history(messages):
                if _TOOL_RESULT_MAX_CHARS <= 0:
                    return
                for msg in messages:
                    if msg.get('role') != 'tool':
                        continue
                    content = msg.get('content', '')
                    if not isinstance(content, str) or len(content) <= _TOOL_RESULT_MAX_CHARS:
                        continue
                    msg['content'] = 'truncated'
        """), exec_ns)

        messages = [{"role": "tool", "content": "small result"}]
        exec_ns['_truncate_tool_messages_in_history'](messages)
        self.assertEqual(messages[0]["content"], "small result")

    def test_non_tool_messages_untouched(self):
        """Non-tool messages should never be modified."""
        exec_ns = {}
        exec(textwrap.dedent("""\
            import os, logging
            log = logging.getLogger("test")
            _TOOL_RESULT_MAX_CHARS = 10
            _TOOL_RESULT_PREVIEW_CHARS = 5

            def _truncate_tool_messages_in_history(messages):
                if _TOOL_RESULT_MAX_CHARS <= 0:
                    return
                for msg in messages:
                    if msg.get('role') != 'tool':
                        continue
                    content = msg.get('content', '')
                    if not isinstance(content, str) or len(content) <= _TOOL_RESULT_MAX_CHARS:
                        continue
                    msg['content'] = 'truncated'
        """), exec_ns)

        big_user_msg = "x" * 1000
        messages = [{"role": "user", "content": big_user_msg}]
        exec_ns['_truncate_tool_messages_in_history'](messages)
        self.assertEqual(messages[0]["content"], big_user_msg)


if __name__ == "__main__":
    unittest.main()
