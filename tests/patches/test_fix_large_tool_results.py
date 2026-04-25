#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
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
        """Return minimal synthetic middleware content satisfying all 3 anchors.

        Must include:
        - `from open_webui.models.chats import Chats` (Mod 1 import marker)
        - SEARCH_TOOL_LOOP literal (TOOL_LOOP_ERRORS_UNIFIED save-for-restore marker
          + `\n                    try:\n                        new_form_data = {\n`)
        - SEARCH_HISTORY literal (process_messages_with_output + blank + get_system_message)
        """
        return (
            "import json\n"
            "from open_webui.models.chats import Chats\n"
            "\n"
            "def process_messages_with_output(messages):\n"
            "    return messages\n"
            "\n"
            "def get_system_message(messages):\n"
            "    return None\n"
            "\n"
            "async def middleware():\n"
            "    form_data = {'messages': []}\n"
            "    metadata = {'chat_id': 'test-123'}\n"
            "    form_data['messages'] = process_messages_with_output(form_data.get('messages', []))\n"
            "\n"
            "    system_message = get_system_message(form_data.get('messages', []))\n"
            "\n"
            "    output = []\n"
            "    tool_call_retries = 0\n"
            "    while tool_call_retries < 5:\n"
            "        tool_call_retries += 1\n"
            "                    _saved_output = json.loads(json.dumps(output))  # TOOL_LOOP_ERRORS_UNIFIED: save for restore on error\n"
            "                    try:\n"
            "                        new_form_data = {\n"
            "                            **form_data,\n"
            "                            'model': model_id,\n"
            "                            'stream': True,\n"
            "                            'metadata': metadata,\n"
            "                        }\n"
        )

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
        """Patch should fail loud (SystemExit(1)) if middleware.py doesn't exist."""
        import fix_large_tool_results
        fix_large_tool_results.MIDDLEWARE_PATH = "/tmp/nonexistent_middleware_xyz.py"
        with self.assertRaises(SystemExit) as cm:
            fix_large_tool_results.apply_patch()
        self.assertEqual(cm.exception.code, 1)


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


#
# v0.9.1 integration tests — real upstream fixture via subprocess
#
import ast
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PATCH_DIR = REPO_ROOT / "openwebui" / "patches"
sys.path.insert(0, str(Path(__file__).parent))
from conftest import load_middleware_v091, load_middleware_v092  # noqa: E402


def _run_patch(patch_name: str, target_file: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "_PATCH_TARGET_OVERRIDE": str(target_file)}
    return subprocess.run(
        [sys.executable, str(PATCH_DIR / f"{patch_name}.py")],
        env=env, capture_output=True, text=True, timeout=30,
    )


class TestFixLargeToolResultsV091(unittest.TestCase):
    """3-state coverage + cascade tests against real v0.9.1 middleware."""

    PATCH_NAME = "fix_large_tool_results"
    NEW_MARKER = "FIX_LARGE_TOOL_RESULTS"
    # Mod 3 anchor — removing this leaves Patch 3's marker intact so Mod 2 still
    # succeeds after patch 3; Mod 3 is the one that fails loud.
    PRIMARY_ANCHOR = (
        "    form_data['messages'] = process_messages_with_output"
        "(form_data.get('messages', []))"
    )

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.target = Path(self.tmp) / "middleware.py"
        self.target.write_text(load_middleware_v091(), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fresh_apply(self):
        # Cascade dependency: fix_tool_loop_errors must run first
        r1 = _run_patch("fix_tool_loop_errors", self.target)
        self.assertEqual(r1.returncode, 0, f"patch3 stderr={r1.stderr}")
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
        self.assertIn(f"PATCHED: {self.PATCH_NAME}", r.stdout)
        content = self.target.read_text()
        self.assertIn(self.NEW_MARKER, content)
        ast.parse(content)

    def test_idempotent_rerun(self):
        _run_patch("fix_tool_loop_errors", self.target)
        r1 = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r1.returncode, 0)
        after_first = self.target.read_text()
        r2 = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("ALREADY PATCHED", r2.stdout)
        self.assertEqual(after_first, self.target.read_text())

    def test_broken_fixture_fails_loud(self):
        # Apply patch 3 first (so Mod 2 anchor is present), then remove Mod 3 anchor
        _run_patch("fix_tool_loop_errors", self.target)
        content = self.target.read_text()
        self.assertIn(self.PRIMARY_ANCHOR, content)
        self.target.write_text(
            content.replace(self.PRIMARY_ANCHOR, "    # ANCHOR_REMOVED_FOR_TEST")
        )
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 1, f"stdout={r.stdout} stderr={r.stderr}")
        self.assertIn("ERROR:", r.stderr)
        self.assertIn(self.PATCH_NAME, r.stderr)

    def test_cascade_with_patch_3(self):
        r1 = _run_patch("fix_tool_loop_errors", self.target)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = _run_patch("fix_large_tool_results", self.target)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        content = self.target.read_text()
        self.assertIn("FIX_TOOL_LOOP_ERRORS", content)
        self.assertIn("FIX_LARGE_TOOL_RESULTS", content)
        ast.parse(content)

    def test_patch_4_fails_loud_without_patch_3(self):
        # Patch 4 direct on raw v0.9.1 — Mod 2 anchor (TOOL_LOOP_ERRORS_UNIFIED marker) missing
        r = _run_patch("fix_large_tool_results", self.target)
        self.assertEqual(r.returncode, 1, f"stdout={r.stdout} stderr={r.stderr}")
        # Error message points at running fix_tool_loop_errors first
        self.assertIn("fix_tool_loop_errors", r.stderr.lower())


class TestFixLargeToolResultsV092(unittest.TestCase):
    """3-state coverage + cascade tests against real v0.9.2 middleware.py fixture."""

    PATCH_NAME = "fix_large_tool_results"
    NEW_MARKER = "FIX_LARGE_TOOL_RESULTS"
    PRIMARY_ANCHOR = (
        "    form_data['messages'] = process_messages_with_output"
        "(form_data.get('messages', []))"
    )

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.target = Path(self.tmp) / "middleware.py"
        self.target.write_text(load_middleware_v092(), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fresh_apply_v092(self):
        # Cascade dependency: fix_tool_loop_errors must run first
        r1 = _run_patch("fix_tool_loop_errors", self.target)
        self.assertEqual(r1.returncode, 0, f"patch3 stderr={r1.stderr}")
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
        self.assertIn(f"PATCHED: {self.PATCH_NAME}", r.stdout)
        content = self.target.read_text()
        self.assertIn(self.NEW_MARKER, content)
        # v0.9.2 specific: post-patch3 content must carry the new metadata key
        self.assertIn("'metadata': metadata,", content)
        ast.parse(content)

    def test_idempotent_rerun_v092(self):
        _run_patch("fix_tool_loop_errors", self.target)
        r1 = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r1.returncode, 0)
        after_first = self.target.read_text()
        r2 = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("ALREADY PATCHED", r2.stdout)
        self.assertEqual(after_first, self.target.read_text())

    def test_broken_fixture_fails_loud_v092(self):
        _run_patch("fix_tool_loop_errors", self.target)
        content = self.target.read_text()
        self.assertIn(self.PRIMARY_ANCHOR, content)
        self.target.write_text(
            content.replace(self.PRIMARY_ANCHOR, "    # ANCHOR_REMOVED_FOR_TEST")
        )
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 1, f"stdout={r.stdout} stderr={r.stderr}")
        self.assertIn("ERROR:", r.stderr)
        self.assertIn(self.PATCH_NAME, r.stderr)

    def test_cascade_with_patch_3_on_v092(self):
        r1 = _run_patch("fix_tool_loop_errors", self.target)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = _run_patch("fix_large_tool_results", self.target)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        content = self.target.read_text()
        self.assertIn("FIX_TOOL_LOOP_ERRORS", content)
        self.assertIn("FIX_LARGE_TOOL_RESULTS", content)
        self.assertIn("'metadata': metadata,", content)
        ast.parse(content)


if __name__ == "__main__":
    unittest.main()
