# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for per-CLI sub_agent docstring variants (REQ-MCP-01 / Plan 01-04).

Tests the _subagent_docstring_for_cli helper and related constants directly
from source without importing the full mcp_tools module (which requires the
docker/mcp runtime environment).

Run: python -m pytest tests/test_subagent_docstring.py -v
"""

import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "computer-use-server" / "mcp_tools.py"


def _load_docstring_helpers():
    """Extract and exec only the docstring-related portion of mcp_tools.py.

    Avoids importing the full module (which requires mcp, docker, etc.).
    Returns a module-like namespace with the three constants and the helper.
    """
    src = SRC.read_text()

    # Extract lines from _SUBAGENT_DOC_CLAUDE through end of _subagent_docstring_for_cli
    lines = src.splitlines()
    start = None
    end = None
    for i, line in enumerate(lines):
        if start is None and line.startswith("_SUBAGENT_DOC_CLAUDE = "):
            start = i
        if start is not None and line.startswith("    return _SUBAGENT_DOC_CLAUDE"):
            end = i + 1
            break

    assert start is not None, "Could not find _SUBAGENT_DOC_CLAUDE in mcp_tools.py"
    assert end is not None, "Could not find end of _subagent_docstring_for_cli"

    snippet = "\n".join(lines[start:end])
    ns: dict = {}
    exec(compile(snippet, str(SRC), "exec"), ns)  # noqa: S102
    return ns


_NS = _load_docstring_helpers()


class TestSubagentDocstringForCli(unittest.TestCase):
    """_subagent_docstring_for_cli returns the correct variant per CLI."""

    def _doc(self, cli: str) -> str:
        return _NS["_subagent_docstring_for_cli"](cli)

    # --- list-subagent-models redirect in all variants ---

    def test_claude_has_list_subagent_models_redirect(self):
        assert "list-subagent-models" in self._doc("claude")

    def test_opencode_has_list_subagent_models_redirect(self):
        assert "list-subagent-models" in self._doc("opencode")

    def test_codex_has_list_subagent_models_redirect(self):
        assert "list-subagent-models" in self._doc("codex")

    # --- claude variant contains all three aliases ---

    def test_claude_contains_sonnet(self):
        assert "sonnet" in self._doc("claude")

    def test_claude_contains_opus(self):
        assert "opus" in self._doc("claude")

    def test_claude_contains_haiku(self):
        assert "haiku" in self._doc("claude")

    # --- codex variant is alias-free ---

    def test_codex_no_bare_sonnet(self):
        assert "sonnet" not in self._doc("codex").lower()

    def test_codex_no_bare_opus(self):
        assert "opus" not in self._doc("codex").lower()

    def test_codex_no_bare_haiku(self):
        assert "haiku" not in self._doc("codex").lower()

    # --- opencode variant does not expose bare Claude aliases ---

    def test_opencode_no_bare_haiku(self):
        # 'haiku' must not appear as a bare alias (only as part of provider/model is OK)
        doc = self._doc("opencode")
        # Allow 'anthropic/claude-haiku-*' but not standalone 'haiku'
        without_provider = re.sub(r'anthropic/claude-\S+', '', doc)
        assert "haiku" not in without_provider.lower()

    # --- unknown CLI falls back to claude ---

    def test_unknown_cli_falls_back_to_claude(self):
        assert self._doc("unknown") == self._doc("claude")

    def test_empty_cli_falls_back_to_claude(self):
        assert self._doc("") == self._doc("claude")

    # --- OPENCODE_MODEL_ALIASES hint present in opencode variant ---

    def test_opencode_mentions_alias_env(self):
        assert "OPENCODE_MODEL_ALIASES" in self._doc("opencode")

    # --- per-CLI env var hints present ---

    def test_claude_mentions_claude_env(self):
        assert "CLAUDE_SUB_AGENT_DEFAULT_MODEL" in self._doc("claude")

    def test_opencode_mentions_opencode_env(self):
        assert "OPENCODE_SUB_AGENT_DEFAULT_MODEL" in self._doc("opencode")

    def test_codex_mentions_codex_env(self):
        assert "CODEX_SUB_AGENT_DEFAULT_MODEL" in self._doc("codex")


class TestMcpToolsStructure(unittest.TestCase):
    """Static source checks on mcp_tools.py registration structure."""

    def setUp(self):
        self.src = SRC.read_text()

    def test_no_decorator_on_sub_agent(self):
        """@mcp.tool() decorator must not appear on the sub_agent def."""
        lines = self.src.splitlines()
        for i, line in enumerate(lines):
            if "async def sub_agent(" in line:
                # Check two lines above for @mcp.tool()
                preceding = lines[max(0, i - 3):i]
                for prev in preceding:
                    self.assertNotIn("@mcp.tool()", prev,
                                     "sub_agent still has @mcp.tool() decorator")
                break
        else:
            self.fail("Could not find async def sub_agent")

    def test_doc_assignment_present(self):
        """sub_agent.__doc__ = _subagent_docstring_for_cli(...) must be present."""
        assert "sub_agent.__doc__ = _subagent_docstring_for_cli" in self.src

    def test_mcp_add_tool_call_present(self):
        """mcp.add_tool(sub_agent) must be present (not counting comments)."""
        code_lines = [l for l in self.src.splitlines()
                      if "mcp.add_tool(sub_agent)" in l and not l.strip().startswith("#")]
        self.assertEqual(len(code_lines), 1,
                         f"Expected exactly 1 mcp.add_tool(sub_agent) call, found: {code_lines}")

    def test_no_sub_agent_default_model_usage(self):
        """Legacy bare SUB_AGENT_DEFAULT_MODEL must be absent; per-CLI env must be documented.

        Phase 2 D-03: the legacy global is removed from docker_manager.py and the
        module docstring is updated to document the three per-CLI env vars instead.
        This assertion verifies the docstring update happened.

        Note: check for the bare legacy name without a CLI prefix (CLAUDE_/OPENCODE_/CODEX_).
        The per-CLI variants CLAUDE_SUB_AGENT_DEFAULT_MODEL etc. are expected and fine.
        """
        import re
        # The legacy line was "- SUB_AGENT_DEFAULT_MODEL: Default model ..."
        # Per-CLI lines like "- CLAUDE_SUB_AGENT_DEFAULT_MODEL: ..." are OK.
        legacy_pattern = re.compile(r'(?<![A-Z_])SUB_AGENT_DEFAULT_MODEL: Default model')
        assert not legacy_pattern.search(self.src), (
            "Legacy bare SUB_AGENT_DEFAULT_MODEL docstring entry still present in mcp_tools.py"
        )
        assert "CLAUDE_SUB_AGENT_DEFAULT_MODEL" in self.src, (
            "CLAUDE_SUB_AGENT_DEFAULT_MODEL must be documented in mcp_tools.py module docstring"
        )

    def test_resolve_subagent_model_used(self):
        """resolve_subagent_model('', resolve_cli()) must be the fallback."""
        assert 'resolve_subagent_model("", resolve_cli())' in self.src


if __name__ == "__main__":
    unittest.main()
