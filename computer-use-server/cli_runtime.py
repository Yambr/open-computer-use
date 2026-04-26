# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Sub-agent CLI runtime resolver and adapter dispatch.

Single source of truth for the SUBAGENT_CLI selection (CLI-03).
All downstream code (mcp_tools.sub_agent dispatch — Phase 7 onward,
per-CLI auth allowlists — Phase 6, ttyd autostart consumer — Phase 7)
goes through resolve_cli() — no scattered SUBAGENT_CLI string comparisons.

Module-load validation in docker_manager.py (D1) guarantees SUBAGENT_CLI is
in the allowlist by the time this module is imported, so Cli(SUBAGENT_CLI)
cannot raise ValueError in production. The defensive ValueError path is only
reachable if the constant is monkey-patched in tests.

Pitfall E (RESEARCH.md): import direction is cli_runtime FROM docker_manager,
NOT the reverse. docker_manager owns the constant; cli_runtime consumes it.
"""

import os
from enum import StrEnum

from docker_manager import (
    SUBAGENT_CLI,
    ANTHROPIC_DEFAULT_SONNET_MODEL,
    ANTHROPIC_DEFAULT_OPUS_MODEL,
    ANTHROPIC_DEFAULT_HAIKU_MODEL,
)
from cli_adapters import CliAdapter
from cli_adapters.claude import ClaudeAdapter
from cli_adapters.codex import CodexAdapter
from cli_adapters.opencode import OpenCodeAdapter


class Cli(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"


# Adapter dispatch — instantiated at module load. Stub adapters (codex,
# opencode) MUST have empty __init__ bodies so this wiring does not crash
# in Phase 4 (Pitfall C in RESEARCH.md). Their build_argv/parse_result
# methods raise NotImplementedError; that is the Phase 5 contract.
_ADAPTERS: dict[Cli, CliAdapter] = {
    Cli.CLAUDE: ClaudeAdapter(),
    Cli.CODEX: CodexAdapter(),
    Cli.OPENCODE: OpenCodeAdapter(),
}


def resolve_cli() -> Cli:
    """Return the active CLI runtime resolved from SUBAGENT_CLI.

    Module-load validation in docker_manager.py guarantees SUBAGENT_CLI is
    in the allowlist by the time this function is reachable, so Cli(...)
    cannot raise here in production.
    """
    return Cli(SUBAGENT_CLI)


def get_adapter(cli: Cli | None = None) -> CliAdapter:
    """Return the adapter instance for the given (or active) CLI.

    Convenience helper — Phase 7 dispatch flips through this. Phase 4 callers
    do not exist yet (success criterion #4: mcp_tools.sub_agent is unchanged).
    """
    return _ADAPTERS[cli if cli is not None else resolve_cli()]


# ===========================================================================
# ADAPT-06: per-CLI model resolution
# ===========================================================================
# resolve_subagent_model(alias_or_id, cli) -> (model_id, display_name)
#
# Claude path preserves v0.9.2.0 ALIAS_MAP behaviour from mcp_tools.py:909-924.
# Codex path hard-fails on Claude-only aliases (Pitfall 3 in PITFALLS.md) —
# silently letting "sonnet" through to codex would produce a remote 400.
# OpenCode path expands aliases to provider/model form ("sonnet" ->
# "anthropic/claude-sonnet-4-6") and warns (does not raise) when a
# direct id is missing the "provider/" prefix.

_CLAUDE_ALIAS_MAP = {
    "sonnet": lambda: ANTHROPIC_DEFAULT_SONNET_MODEL or "claude-sonnet-4-6",
    "opus":   lambda: ANTHROPIC_DEFAULT_OPUS_MODEL   or "claude-opus-4-6",
    "haiku":  lambda: ANTHROPIC_DEFAULT_HAIKU_MODEL  or "claude-haiku-4-5",
}

_OPENCODE_ALIAS_MAP = {
    "sonnet": "anthropic/claude-sonnet-4-6",
    "opus":   "anthropic/claude-opus-4-6",
    "haiku":  "anthropic/claude-haiku-4-5",
}


def _resolve_claude(requested: str, key: str) -> tuple[str, str]:
    if key in _CLAUDE_ALIAS_MAP:
        return _CLAUDE_ALIAS_MAP[key](), key
    if requested:
        return requested, requested
    return _CLAUDE_ALIAS_MAP["sonnet"](), "sonnet"


def _resolve_codex(requested: str, key: str) -> tuple[str, str]:
    # CODEX_SUB_AGENT_DEFAULT_MODEL > CODEX_MODEL > "gpt-5-codex".
    default = (
        os.getenv("CODEX_SUB_AGENT_DEFAULT_MODEL", "")
        or os.getenv("CODEX_MODEL", "")
        or "gpt-5-codex"
    )
    # Pitfall 3: Claude-only alias on codex => fail loud, do not silently 400.
    if key in _CLAUDE_ALIAS_MAP:
        raise ValueError(
            f"Model alias {key!r} is Claude-only; SUBAGENT_CLI=codex requires a "
            f"GPT model id (e.g. 'gpt-5-codex') or set CODEX_SUB_AGENT_DEFAULT_MODEL."
        )
    if requested:
        return requested, requested
    return default, default


def _resolve_opencode(requested: str, key: str) -> tuple[str, str]:
    default = (
        os.getenv("OPENCODE_SUB_AGENT_DEFAULT_MODEL", "")
        or os.getenv("OPENCODE_MODEL", "")
        or "anthropic/claude-sonnet-4-6"
    )
    if key in _OPENCODE_ALIAS_MAP:
        return _OPENCODE_ALIAS_MAP[key], key
    if requested:
        if "/" not in requested:
            # Soft warning (Pitfall 3 doesn't apply here — opencode just needs
            # provider/model form; we let it through and surface the failure
            # at runtime via opencode's own error path).
            print(
                f"[SUB-AGENT] WARNING: opencode model {requested!r} has no "
                f"provider prefix — may fail at runtime."
            )
        return requested, requested
    return default, default


def resolve_subagent_model(alias_or_id: str, cli: Cli) -> tuple[str, str]:
    """Resolve a model alias or direct ID for the given CLI.

    Returns (model_id, display_name). model_id is what we pass to the CLI's
    --model flag; display_name is what we put in the result blob.

    Raises ValueError when a Claude-only alias (sonnet/opus/haiku) is requested
    for SUBAGENT_CLI=codex (Pitfall 3 — prevents silent 400 from openai gateway).
    """
    requested = (alias_or_id or "").strip()
    key = requested.lower()
    if cli == Cli.CLAUDE:
        return _resolve_claude(requested, key)
    if cli == Cli.CODEX:
        return _resolve_codex(requested, key)
    if cli == Cli.OPENCODE:
        return _resolve_opencode(requested, key)
    raise ValueError(f"unknown CLI: {cli!r}")
