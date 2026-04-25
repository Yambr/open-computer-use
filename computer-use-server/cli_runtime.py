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

from enum import StrEnum

from docker_manager import SUBAGENT_CLI
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
