# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Test that sub_agent FastMCP Tool.description is correct per SUBAGENT_CLI.

Verifies Plan 01-04 behaviour (D-05):
- claude/unset: all three Claude aliases (sonnet, opus, haiku) appear in doc
- opencode: no bare Claude alias tokens; doc contains list-subagent-models redirect
- codex: no Claude alias tokens at all; doc contains list-subagent-models redirect
- unknown CLI falls back to the claude variant

Uses snippet extraction (same pattern as test_subagent_docstring.py) to avoid
importing the full mcp_tools module which requires docker/mcp runtime.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "computer-use-server" / "mcp_tools.py"

CLAUDE_ALIASES = ("sonnet", "opus", "haiku")


def _load_docstring_helpers():
    """Extract and exec only the docstring-related portion of mcp_tools.py.

    Avoids importing the full module (which requires mcp, docker, etc.).
    Returns a namespace dict with the three constants and the helper function.
    """
    src = SRC.read_text()
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


def _get_subagent_doc(cli: str) -> str:
    """Return the sub_agent docstring for the given CLI value."""
    return _NS["_subagent_docstring_for_cli"](cli)


# ---------------------------------------------------------------------------
# Claude CLI — all three aliases must appear
# ---------------------------------------------------------------------------

def test_claude_doc_contains_aliases():
    doc = _get_subagent_doc("claude")
    for alias in CLAUDE_ALIASES:
        assert alias in doc, f"Expected alias '{alias}' in claude sub_agent doc"


def test_unset_cli_doc_contains_aliases():
    """Empty string (unset SUBAGENT_CLI) falls back to claude variant."""
    doc = _get_subagent_doc("")
    for alias in CLAUDE_ALIASES:
        assert alias in doc, f"Expected alias '{alias}' in unset-CLI sub_agent doc"


# ---------------------------------------------------------------------------
# opencode CLI — no bare Claude alias tokens; list-subagent-models present
# ---------------------------------------------------------------------------

def test_opencode_doc_contains_list_subagent_models():
    doc = _get_subagent_doc("opencode")
    assert "list-subagent-models" in doc, (
        "opencode sub_agent doc must mention 'list-subagent-models'"
    )


def test_opencode_doc_no_bare_aliases():
    """opencode doc must not expose bare sonnet/opus/haiku tokens.

    The doc may legitimately reference anthropic/claude-sonnet-4-6 in an
    example; that is acceptable because the alias is embedded in a
    provider/model id (preceded by 'claude-' or '/'). The assertion here
    only rejects bare occurrences where no such prefix is present.
    """
    doc = _get_subagent_doc("opencode")
    for alias in CLAUDE_ALIASES:
        matches = list(re.finditer(rf"\b{alias}\b", doc))
        for m in matches:
            pre = doc[max(0, m.start() - 10) : m.start()]
            assert "/" in pre or "claude-" in pre, (
                f"Bare alias '{alias}' found at offset {m.start()} in opencode doc: "
                f"...{doc[max(0, m.start()-20):m.end()+20]}..."
            )


# ---------------------------------------------------------------------------
# codex CLI — zero Claude alias tokens; list-subagent-models present
# ---------------------------------------------------------------------------

def test_codex_doc_contains_list_subagent_models():
    doc = _get_subagent_doc("codex")
    assert "list-subagent-models" in doc, (
        "codex sub_agent doc must mention 'list-subagent-models'"
    )


def test_codex_doc_no_aliases():
    """codex doc must have zero occurrences of any Claude alias."""
    doc = _get_subagent_doc("codex")
    for alias in CLAUDE_ALIASES:
        assert alias.lower() not in doc.lower(), (
            f"Unexpected alias '{alias}' found in codex sub_agent doc"
        )


# ---------------------------------------------------------------------------
# Unknown CLI falls back to claude variant
# ---------------------------------------------------------------------------

def test_unknown_cli_falls_back_to_claude():
    claude_doc = _get_subagent_doc("claude")
    unknown_doc = _get_subagent_doc("banana")
    assert unknown_doc == claude_doc, (
        "Unknown CLI 'banana' must fall back to claude sub_agent doc"
    )
