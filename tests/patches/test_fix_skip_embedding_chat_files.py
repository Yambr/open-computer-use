# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for fix_skip_embedding_chat_files.py against v0.9.1 retrieval.py."""
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PATCH_DIR = REPO_ROOT / "openwebui" / "patches"
sys.path.insert(0, str(Path(__file__).parent))
from conftest import load_retrieval_v091, load_retrieval_v092  # noqa: E402


def _run_patch(patch_name: str, target_file: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "_PATCH_TARGET_OVERRIDE": str(target_file)}
    return subprocess.run(
        [sys.executable, str(PATCH_DIR / f"{patch_name}.py")],
        env=env, capture_output=True, text=True, timeout=30,
    )


class TestFixSkipEmbeddingChatFiles(unittest.TestCase):
    PATCH_NAME = "fix_skip_embedding_chat_files"
    NEW_MARKER = "FIX_SKIP_EMBEDDING_CHAT_FILES"
    PRIMARY_ANCHOR = "                collection_name = f'file-{file.id}'"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.target = Path(self.tmp) / "retrieval.py"
        self.target.write_text(load_retrieval_v091(), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fresh_apply(self):
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
        self.assertIn(f"PATCHED: {self.PATCH_NAME}", r.stdout)
        content = self.target.read_text()
        self.assertIn(self.NEW_MARKER, content)
        ast.parse(content)

    def test_idempotent_rerun(self):
        r1 = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r1.returncode, 0)
        after_first = self.target.read_text()
        r2 = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("ALREADY PATCHED", r2.stdout)
        self.assertEqual(after_first, self.target.read_text())

    def test_broken_fixture_fails_loud(self):
        content = self.target.read_text()
        self.assertIn(self.PRIMARY_ANCHOR, content)
        self.target.write_text(
            content.replace(self.PRIMARY_ANCHOR, "                # ANCHOR_REMOVED_FOR_TEST")
        )
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 1, f"stdout={r.stdout} stderr={r.stderr}")
        self.assertIn("ERROR:", r.stderr)
        self.assertIn(self.PATCH_NAME, r.stderr)


class TestFixSkipEmbeddingChatFilesV092(unittest.TestCase):
    """3-state coverage against real v0.9.2 retrieval.py fixture."""

    PATCH_NAME = "fix_skip_embedding_chat_files"
    NEW_MARKER = "FIX_SKIP_EMBEDDING_CHAT_FILES"
    PRIMARY_ANCHOR = "                collection_name = f'file-{file.id}'"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.target = Path(self.tmp) / "retrieval.py"
        self.target.write_text(load_retrieval_v092(), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fresh_apply_v092(self):
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
        self.assertIn(f"PATCHED: {self.PATCH_NAME}", r.stdout)
        content = self.target.read_text()
        self.assertIn(self.NEW_MARKER, content)
        ast.parse(content)

    def test_idempotent_rerun_v092(self):
        r1 = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r1.returncode, 0)
        after_first = self.target.read_text()
        r2 = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("ALREADY PATCHED", r2.stdout)
        self.assertEqual(after_first, self.target.read_text())

    def test_broken_fixture_fails_loud_v092(self):
        content = self.target.read_text()
        self.assertIn(self.PRIMARY_ANCHOR, content)
        self.target.write_text(
            content.replace(self.PRIMARY_ANCHOR, "                # ANCHOR_REMOVED_FOR_TEST")
        )
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 1, f"stdout={r.stdout} stderr={r.stderr}")
        self.assertIn("ERROR:", r.stderr)
        self.assertIn(self.PATCH_NAME, r.stderr)


if __name__ == "__main__":
    unittest.main()
