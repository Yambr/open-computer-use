# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Unit tests for cli_runtime.resolve_subagent_model resolution order (D-08/D-09).

Resolution priority (per CONTEXT.md D-08):
  caller-supplied alias/id > <CLI>_SUB_AGENT_DEFAULT_MODEL env > per-CLI hardcoded default

Covers all three CLIs:
  - claude  → default alias 'sonnet', fallback via _CLAUDE_ALIAS_MAP
  - opencode → default 'anthropic/claude-sonnet-4-6', env OPENCODE_SUB_AGENT_DEFAULT_MODEL
  - codex   → default 'gpt-5-codex', env CODEX_SUB_AGENT_DEFAULT_MODEL
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "computer-use-server"))

# We import only the resolver and alias maps; avoid pulling in FastMCP / docker SDK
# at module-parse time by importing lazily inside each test via the function references.
import cli_runtime
from cli_runtime import Cli, resolve_subagent_model, _CLAUDE_ALIAS_MAP


# ===========================================================================
# Claude
# ===========================================================================

def test_claude_default(monkeypatch):
    """Empty alias with claude CLI resolves to the canonical sonnet expansion."""
    # Clear any env overrides that could affect ANTHROPIC_DEFAULT_SONNET_MODEL
    monkeypatch.delenv("CLAUDE_SUB_AGENT_DEFAULT_MODEL", raising=False)
    model_id, _display = resolve_subagent_model("", Cli.CLAUDE)
    expected = _CLAUDE_ALIAS_MAP["sonnet"]()
    assert model_id == expected, (
        f"Expected claude default '{expected}', got '{model_id}'"
    )


def test_claude_caller_wins(monkeypatch):
    """Caller-supplied alias takes priority over default for claude CLI."""
    monkeypatch.delenv("CLAUDE_SUB_AGENT_DEFAULT_MODEL", raising=False)
    model_id, display = resolve_subagent_model("opus", Cli.CLAUDE)
    expected = _CLAUDE_ALIAS_MAP["opus"]()
    assert model_id == expected, (
        f"Expected opus expansion '{expected}', got '{model_id}'"
    )


# ===========================================================================
# opencode
# ===========================================================================

def test_opencode_hardcoded_default(monkeypatch):
    """Without env override, opencode defaults to anthropic/claude-sonnet-4-6."""
    monkeypatch.delenv("OPENCODE_SUB_AGENT_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("OPENCODE_MODEL", raising=False)
    monkeypatch.delenv("OPENCODE_MODEL_ALIASES", raising=False)
    model_id, _display = resolve_subagent_model("", Cli.OPENCODE)
    assert model_id == "anthropic/claude-sonnet-4-6", (
        f"Expected opencode hardcoded default 'anthropic/claude-sonnet-4-6', got '{model_id}'"
    )


def test_opencode_env_default(monkeypatch):
    """OPENCODE_SUB_AGENT_DEFAULT_MODEL env overrides hardcoded default."""
    monkeypatch.setenv("OPENCODE_SUB_AGENT_DEFAULT_MODEL", "openrouter/qwen/qwen-3-coder")
    monkeypatch.delenv("OPENCODE_MODEL", raising=False)
    monkeypatch.delenv("OPENCODE_MODEL_ALIASES", raising=False)
    model_id, _display = resolve_subagent_model("", Cli.OPENCODE)
    assert model_id == "openrouter/qwen/qwen-3-coder", (
        f"Expected env-driven opencode default 'openrouter/qwen/qwen-3-coder', got '{model_id}'"
    )


def test_opencode_alias_override_via_env(monkeypatch):
    """OPENCODE_MODEL_ALIASES can add custom aliases that caller can use."""
    monkeypatch.setenv(
        "OPENCODE_MODEL_ALIASES", '{"qwen": "openrouter/qwen/qwen-3-coder"}'
    )
    monkeypatch.delenv("OPENCODE_SUB_AGENT_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("OPENCODE_MODEL", raising=False)
    model_id, _display = resolve_subagent_model("qwen", Cli.OPENCODE)
    assert model_id == "openrouter/qwen/qwen-3-coder", (
        f"Expected alias-expanded id 'openrouter/qwen/qwen-3-coder', got '{model_id}'"
    )


# ===========================================================================
# codex
# ===========================================================================

def test_codex_hardcoded_default(monkeypatch):
    """Without env override, codex defaults to gpt-5-codex."""
    monkeypatch.delenv("CODEX_SUB_AGENT_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    model_id, _display = resolve_subagent_model("", Cli.CODEX)
    assert model_id == "gpt-5-codex", (
        f"Expected codex hardcoded default 'gpt-5-codex', got '{model_id}'"
    )


def test_codex_env_default(monkeypatch):
    """CODEX_SUB_AGENT_DEFAULT_MODEL env overrides hardcoded default."""
    monkeypatch.setenv("CODEX_SUB_AGENT_DEFAULT_MODEL", "gpt-4o")
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    model_id, _display = resolve_subagent_model("", Cli.CODEX)
    assert model_id == "gpt-4o", (
        f"Expected env-driven codex default 'gpt-4o', got '{model_id}'"
    )


def test_caller_wins_over_env(monkeypatch):
    """Caller-supplied id beats env default for codex CLI."""
    monkeypatch.setenv("CODEX_SUB_AGENT_DEFAULT_MODEL", "gpt-4o")
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    model_id, _display = resolve_subagent_model("o3", Cli.CODEX)
    assert model_id == "o3", (
        f"Expected caller-supplied 'o3' to win over env default, got '{model_id}'"
    )
