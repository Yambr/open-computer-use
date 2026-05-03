# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Unit tests for cli_runtime.resolve_subagent_model resolution order.

Phase 1 D-08/D-09 introduced per-CLI defaults. Phase 2 D-01/D-02 (CONTEXT.md
phases/02-...) DROPPED the hardcoded defaults for opencode and codex; only
claude retains a hardcoded fallback.

Updated resolution priority:
  caller-supplied alias/id > <CLI>_SUB_AGENT_DEFAULT_MODEL env > per-CLI fallback

Per-CLI fallback behavior (Phase 2):
  - claude  → expansion of 'sonnet' via _CLAUDE_ALIAS_MAP (hardcoded baseline preserved)
  - opencode → raises ValueError (no hardcoded baseline; explicit error guides operator)
  - codex   → raises ValueError (no hardcoded baseline; explicit error guides operator)
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

def test_opencode_no_default_raises(monkeypatch):
    """Phase 2 D-02: opencode has NO hardcoded default; raises ValueError when caller
    passes empty alias and no OPENCODE_SUB_AGENT_DEFAULT_MODEL env is set.

    The error message must point the operator at list-subagent-models and the env var.
    """
    monkeypatch.delenv("OPENCODE_SUB_AGENT_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("OPENCODE_MODEL", raising=False)
    monkeypatch.delenv("OPENCODE_MODEL_ALIASES", raising=False)
    with pytest.raises(ValueError) as exc_info:
        resolve_subagent_model("", Cli.OPENCODE)
    msg = str(exc_info.value)
    assert "OPENCODE_SUB_AGENT_DEFAULT_MODEL" in msg, msg
    assert "list-subagent-models" in msg, msg


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

def test_codex_no_default_raises(monkeypatch):
    """Phase 2 D-02: codex has NO hardcoded default; raises ValueError when caller
    passes empty alias and no CODEX_SUB_AGENT_DEFAULT_MODEL env is set.

    The error message must point the operator at list-subagent-models and the env var.
    """
    monkeypatch.delenv("CODEX_SUB_AGENT_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    with pytest.raises(ValueError) as exc_info:
        resolve_subagent_model("", Cli.CODEX)
    msg = str(exc_info.value)
    assert "CODEX_SUB_AGENT_DEFAULT_MODEL" in msg, msg
    assert "list-subagent-models" in msg, msg


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
