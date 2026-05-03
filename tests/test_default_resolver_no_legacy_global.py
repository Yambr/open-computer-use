# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for D-01..D-04: legacy SUB_AGENT_DEFAULT_MODEL global removed;
per-CLI explicit defaults enforced in resolver; CLAUDE_SUB_AGENT_DEFAULT_MODEL
honored; codex/opencode raise on missing default.

Run: python -m pytest tests/test_default_resolver_no_legacy_global.py -v
"""

import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = str(ROOT / "computer-use-server")

if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

_ALL_MODEL_ENVS = (
    "SUB_AGENT_DEFAULT_MODEL",
    "CLAUDE_SUB_AGENT_DEFAULT_MODEL",
    "CODEX_SUB_AGENT_DEFAULT_MODEL",
    "OPENCODE_SUB_AGENT_DEFAULT_MODEL",
    "CODEX_MODEL",
    "OPENCODE_MODEL",
    "OPENCODE_MODEL_ALIASES",
)


def _scrub_all_model_envs(monkeypatch):
    """Remove all model-related env vars so tests start from a clean slate."""
    for var in _ALL_MODEL_ENVS:
        monkeypatch.delenv(var, raising=False)


def _fresh_cli_runtime(monkeypatch):
    """Drop + freshly import cli_runtime under current env."""
    for mod in ("cli_runtime", "docker_manager"):
        sys.modules.pop(mod, None)
    return importlib.import_module("cli_runtime")


# ---------------------------------------------------------------------------
# D-03: legacy global is gone from docker_manager
# ---------------------------------------------------------------------------

def test_docker_manager_has_no_sub_agent_default_model(monkeypatch):
    """D-03: docker_manager must NOT define SUB_AGENT_DEFAULT_MODEL attribute."""
    monkeypatch.delenv("SUB_AGENT_DEFAULT_MODEL", raising=False)
    for mod in ("cli_runtime", "docker_manager"):
        sys.modules.pop(mod, None)
    dm = importlib.import_module("docker_manager")
    assert not hasattr(dm, "SUB_AGENT_DEFAULT_MODEL"), (
        "SUB_AGENT_DEFAULT_MODEL global must be removed from docker_manager "
        "(Phase 2 D-03 — deprecation grace period is over)"
    )


def test_docker_manager_has_claude_sub_agent_default_model(monkeypatch):
    """D-04: docker_manager must define CLAUDE_SUB_AGENT_DEFAULT_MODEL."""
    for mod in ("cli_runtime", "docker_manager"):
        sys.modules.pop(mod, None)
    dm = importlib.import_module("docker_manager")
    assert hasattr(dm, "CLAUDE_SUB_AGENT_DEFAULT_MODEL"), (
        "CLAUDE_SUB_AGENT_DEFAULT_MODEL must be present in docker_manager"
    )


# ---------------------------------------------------------------------------
# D-01: claude default stays sonnet when no caller model and no env
# ---------------------------------------------------------------------------

def test_resolve_claude_empty_no_env_returns_sonnet(monkeypatch):
    """D-01: claude falls back to 'sonnet' when no caller model and no env."""
    _scrub_all_model_envs(monkeypatch)
    cr = _fresh_cli_runtime(monkeypatch)
    from cli_runtime import Cli
    model_id, display = cr.resolve_subagent_model("", Cli.CLAUDE)
    assert display == "sonnet"
    assert "sonnet" in model_id.lower()


# ---------------------------------------------------------------------------
# D-04: CLAUDE_SUB_AGENT_DEFAULT_MODEL env honored
# ---------------------------------------------------------------------------

def test_resolve_claude_honors_claude_sub_agent_default_model_env(monkeypatch):
    """D-04: CLAUDE_SUB_AGENT_DEFAULT_MODEL=opus -> alias lookup -> claude-opus-*."""
    _scrub_all_model_envs(monkeypatch)
    monkeypatch.setenv("CLAUDE_SUB_AGENT_DEFAULT_MODEL", "opus")
    cr = _fresh_cli_runtime(monkeypatch)
    from cli_runtime import Cli
    model_id, display = cr.resolve_subagent_model("", Cli.CLAUDE)
    assert display == "opus"
    assert "opus" in model_id.lower()


def test_resolve_claude_caller_model_takes_priority_over_env(monkeypatch):
    """Caller-passed model takes priority over CLAUDE_SUB_AGENT_DEFAULT_MODEL."""
    _scrub_all_model_envs(monkeypatch)
    monkeypatch.setenv("CLAUDE_SUB_AGENT_DEFAULT_MODEL", "opus")
    cr = _fresh_cli_runtime(monkeypatch)
    from cli_runtime import Cli
    model_id, display = cr.resolve_subagent_model("haiku", Cli.CLAUDE)
    assert display == "haiku"
    assert "haiku" in model_id.lower()


# ---------------------------------------------------------------------------
# D-02: codex raises ValueError on missing default
# ---------------------------------------------------------------------------

def test_resolve_codex_empty_no_env_raises(monkeypatch):
    """D-02: codex with no caller model and no env raises ValueError."""
    _scrub_all_model_envs(monkeypatch)
    cr = _fresh_cli_runtime(monkeypatch)
    from cli_runtime import Cli
    with pytest.raises(ValueError) as exc_info:
        cr.resolve_subagent_model("", Cli.CODEX)
    msg = str(exc_info.value)
    assert "SUBAGENT_CLI=codex" in msg
    assert "CODEX_SUB_AGENT_DEFAULT_MODEL" in msg
    assert "list-subagent-models" in msg


def test_resolve_codex_env_set_returns_model(monkeypatch):
    """D-02: CODEX_SUB_AGENT_DEFAULT_MODEL set -> returns that model."""
    _scrub_all_model_envs(monkeypatch)
    monkeypatch.setenv("CODEX_SUB_AGENT_DEFAULT_MODEL", "gpt-5-codex")
    cr = _fresh_cli_runtime(monkeypatch)
    from cli_runtime import Cli
    model_id, display = cr.resolve_subagent_model("", Cli.CODEX)
    assert model_id == "gpt-5-codex"
    assert display == "gpt-5-codex"


def test_resolve_codex_claude_alias_raises_pitfall3(monkeypatch):
    """Pitfall 3: passing a Claude-only alias to codex still raises."""
    _scrub_all_model_envs(monkeypatch)
    cr = _fresh_cli_runtime(monkeypatch)
    from cli_runtime import Cli
    with pytest.raises(ValueError) as exc_info:
        cr.resolve_subagent_model("sonnet", Cli.CODEX)
    assert "Claude-only" in str(exc_info.value)
