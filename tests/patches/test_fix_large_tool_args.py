# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for fix_large_tool_args.py against v0.9.1 middleware.py.

3-state coverage: fresh apply / idempotent re-run / broken fixture fails loud.
Plus: count-assertion trigger test (3 occurrences -> hard fail).
"""
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
from conftest import load_middleware_v091, load_middleware_v092  # noqa: E402


def _run_patch(patch_name: str, target_file: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "_PATCH_TARGET_OVERRIDE": str(target_file)}
    return subprocess.run(
        [sys.executable, str(PATCH_DIR / f"{patch_name}.py")],
        env=env, capture_output=True, text=True, timeout=30,
    )


class TestFixLargeToolArgs(unittest.TestCase):
    PATCH_NAME = "fix_large_tool_args"
    NEW_MARKER = "FIX_LARGE_TOOL_ARGS"
    OLD_ARGS = 'arguments="{html.escape(json.dumps(arguments))}"'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.target = Path(self.tmp) / "middleware.py"
        self.target.write_text(load_middleware_v091(), encoding="utf-8")

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
        # Remove ONE of the 2 OLD_ARGS occurrences -> count==1 -> fails loud
        content = self.target.read_text()
        self.assertEqual(content.count(self.OLD_ARGS), 2)
        # Replace only first occurrence (count kwarg=1) to leave 1
        self.target.write_text(content.replace(self.OLD_ARGS, 'arguments="REMOVED"', 1))
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 1, f"stdout={r.stdout} stderr={r.stderr}")
        self.assertIn("ERROR:", r.stderr)
        self.assertIn("expected 2 occurrences", r.stderr)
        self.assertIn("found 1", r.stderr)

    def test_count_assertion_triggers_on_three(self):
        content = self.target.read_text()
        self.assertEqual(content.count(self.OLD_ARGS), 2)
        # Append a third at module-level as a string literal (still parseable)
        self.target.write_text(
            content + '\n_EXTRA = \'arguments="{html.escape(json.dumps(arguments))}"\'\n'
        )
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 1, f"stdout={r.stdout} stderr={r.stderr}")
        self.assertIn("expected 2 occurrences", r.stderr)
        self.assertIn("found 3", r.stderr)


class TestFixLargeToolArgsV092(unittest.TestCase):
    """3-state coverage against real v0.9.2 middleware.py fixture."""

    PATCH_NAME = "fix_large_tool_args"
    NEW_MARKER = "FIX_LARGE_TOOL_ARGS"
    OLD_ARGS = 'arguments="{html.escape(json.dumps(arguments))}"'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.target = Path(self.tmp) / "middleware.py"
        self.target.write_text(load_middleware_v092(), encoding="utf-8")

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
        self.assertEqual(content.count(self.OLD_ARGS), 2)
        self.target.write_text(content.replace(self.OLD_ARGS, 'arguments="REMOVED"', 1))
        r = _run_patch(self.PATCH_NAME, self.target)
        self.assertEqual(r.returncode, 1, f"stdout={r.stdout} stderr={r.stderr}")
        self.assertIn("ERROR:", r.stderr)
        self.assertIn("expected 2 occurrences", r.stderr)
        self.assertIn("found 1", r.stderr)


if __name__ == "__main__":
    unittest.main()
