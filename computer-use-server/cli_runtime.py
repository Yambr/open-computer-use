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

import asyncio
import json
import logging
import os
import shlex
from enum import StrEnum

_LOG = logging.getLogger("cli_runtime")

from docker_manager import (
    SUBAGENT_CLI,
    ANTHROPIC_DEFAULT_SONNET_MODEL,
    ANTHROPIC_DEFAULT_OPUS_MODEL,
    ANTHROPIC_DEFAULT_HAIKU_MODEL,
    _execute_bash_capture,
)
from cli_adapters import CliAdapter
from cli_adapters.claude import ClaudeAdapter
from cli_adapters.codex import CodexAdapter
from cli_adapters.opencode import OpenCodeAdapter
from cli_adapters.result import SubAgentResult


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
# OpenCode path (D-05/D-06): alias map starts empty; operator must supply
# aliases via OPENCODE_MODEL_ALIASES env. Raises ValueError when alias not
# found or no default configured. Provider/model ids (containing '/') pass through.

_CLAUDE_ALIAS_MAP = {
    "sonnet": lambda: ANTHROPIC_DEFAULT_SONNET_MODEL or "claude-sonnet-4-6",
    "opus":   lambda: ANTHROPIC_DEFAULT_OPUS_MODEL   or "claude-opus-4-6",
    "haiku":  lambda: ANTHROPIC_DEFAULT_HAIKU_MODEL  or "claude-haiku-4-5",
}

# D-05: no Anthropic baseline. Aliases come exclusively from
# OPENCODE_MODEL_ALIASES env (merged in _merge_opencode_alias_map below).
# The previous Anthropic defaults were a silent fallback that masked the
# operator's actual provider choice.
_OPENCODE_ALIAS_MAP: dict[str, str] = {}


def _merge_opencode_alias_map() -> dict[str, str]:
    """Return _OPENCODE_ALIAS_MAP merged with operator overrides from
    OPENCODE_MODEL_ALIASES env (JSON object string).

    Built-in keys remain as the Anthropic baseline unless overridden. Malformed
    JSON, non-dict payloads, or non-string values are logged and ignored — never
    silently half-merged. Read at call time so env changes take effect without
    restart. See D-07 (CONTEXT.md) and OPENCODE_MODEL_ALIASES note in
    docs/multi-cli.md (deferred docs phase).
    """
    merged = dict(_OPENCODE_ALIAS_MAP)
    raw = os.getenv("OPENCODE_MODEL_ALIASES", "").strip()
    if not raw:
        return merged
    try:
        overrides = json.loads(raw)
    except json.JSONDecodeError as e:
        _LOG.warning(
            "OPENCODE_MODEL_ALIASES is not valid JSON (%s); using built-in map only",
            e,
        )
        return merged
    if not isinstance(overrides, dict):
        _LOG.warning(
            "OPENCODE_MODEL_ALIASES must be a JSON object, got %s; using built-in map only",
            type(overrides).__name__,
        )
        return merged
    for k, v in overrides.items():
        if not isinstance(k, str) or not isinstance(v, str) or not k or not v:
            _LOG.warning(
                "OPENCODE_MODEL_ALIASES entry skipped (key=%r value=%r): both must be non-empty strings",
                k, v,
            )
            continue
        merged[k] = v
    return merged


def _resolve_claude(requested: str, key: str) -> tuple[str, str]:
    # D-01: claude default stays `sonnet` when no caller model and no env.
    # Resolution order: caller > CLAUDE_SUB_AGENT_DEFAULT_MODEL env > 'sonnet'.
    if key in _CLAUDE_ALIAS_MAP:
        return _CLAUDE_ALIAS_MAP[key](), key
    if requested:
        return requested, requested
    env_default = os.getenv("CLAUDE_SUB_AGENT_DEFAULT_MODEL", "").strip()
    if env_default:
        env_key = env_default.lower()
        if env_key in _CLAUDE_ALIAS_MAP:
            return _CLAUDE_ALIAS_MAP[env_key](), env_key
        return env_default, env_default
    return _CLAUDE_ALIAS_MAP["sonnet"](), "sonnet"


def _resolve_codex(requested: str, key: str) -> tuple[str, str]:
    # D-02: codex has NO hardcoded default. Caller > CODEX_SUB_AGENT_DEFAULT_MODEL
    # > CODEX_MODEL > raise. Pitfall 3: Claude-only aliases still fail loud.
    if key in _CLAUDE_ALIAS_MAP:
        raise ValueError(
            f"Model alias {key!r} is Claude-only; SUBAGENT_CLI=codex requires a "
            f"concrete model id. Run list-subagent-models to discover valid ids "
            f"or set CODEX_SUB_AGENT_DEFAULT_MODEL env."
        )
    if requested:
        return requested, requested
    default = (
        os.getenv("CODEX_SUB_AGENT_DEFAULT_MODEL", "").strip()
        or os.getenv("CODEX_MODEL", "").strip()
    )
    if default:
        return default, default
    raise ValueError(
        "SUBAGENT_CLI=codex requires either a caller-passed model id or "
        "CODEX_SUB_AGENT_DEFAULT_MODEL env var. "
        "Run list-subagent-models to discover valid ids for this CLI."
    )


def _resolve_opencode(requested: str, key: str) -> tuple[str, str]:
    # D-02 / D-06: opencode has NO hardcoded default. Resolution order:
    #   1. caller-passed `requested` (when truthy)
    #   2. OPENCODE_SUB_AGENT_DEFAULT_MODEL env (or legacy OPENCODE_MODEL)
    #   3. raise ValueError pointing to list-subagent-models + env vars
    # The alias map (D-05) starts empty; entries come from
    # OPENCODE_MODEL_ALIASES env via _merge_opencode_alias_map().
    alias_map = _merge_opencode_alias_map()
    if key in alias_map:
        return alias_map[key], key
    if requested:
        if "/" not in requested:
            # Caller passed an alias-shaped string that is not in the map.
            # Per D-06, fail loud rather than silently letting opencode 4xx.
            raise ValueError(
                f"Model alias {key!r} is not defined for SUBAGENT_CLI=opencode. "
                f"Either pass a fully-qualified provider/model id "
                f"(e.g. '<provider>/<model-id>') or add the alias to "
                f"OPENCODE_MODEL_ALIASES env (JSON object). "
                f"Run list-subagent-models to discover available ids."
            )
        return requested, requested
    default = (
        os.getenv("OPENCODE_SUB_AGENT_DEFAULT_MODEL", "").strip()
        or os.getenv("OPENCODE_MODEL", "").strip()
    )
    if default:
        return default, default
    raise ValueError(
        "SUBAGENT_CLI=opencode requires either a caller-passed model id or "
        "OPENCODE_SUB_AGENT_DEFAULT_MODEL env var. "
        "Run list-subagent-models to discover valid ids for this CLI."
    )


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


# ===========================================================================
# ADAPT-02 / ADAPT-05 / Phase 5: dispatch — single entry point.
# ===========================================================================
# Resolves active CLI -> picks adapter -> resolves model -> builds argv ->
# creates per-CLI workdir if needed -> executes inside container via
# _execute_bash_capture -> parses result.
#
# mcp_tools.sub_agent calls THIS, not the adapters directly. The function
# is async because the underlying docker exec_run blocks on I/O; we wrap
# it in asyncio.to_thread to keep the FastAPI event loop free.

async def dispatch(
    *,
    container,
    task: str,
    system_prompt: str,
    model: str,
    max_turns: int,
    timeout_s: int,
    working_directory: str,
    resume_session_id: str = "",
    plan_file: str = "",
    headers_env: str = "",
) -> "tuple[SubAgentResult, str, str]":
    """Build argv via active adapter, execute inside container, parse result.

    Returns (result, model_id, model_display) — the model_display is
    threaded back to the caller's result formatting (existing v0.9.2.0
    contract: ALIAS_MAP returned `model_display` separately from
    `model_id`; we preserve that here so mcp_tools.sub_agent can render
    the user-facing display name unchanged).

    SECURITY (Phase 5 threat model T-05-05-02): every argv element is
    shlex.quote'd before joining into the shell command. headers_env is
    operator-controlled (currently only ANTHROPIC_CUSTOM_HEADERS) and is
    already shlex.quote'd by mcp_tools.sub_agent BEFORE being passed in
    (preserves v0.9.2.0 contract — the dispatch helper does NOT re-quote
    headers_env; it concatenates verbatim).
    """
    cli = resolve_cli()
    adapter = get_adapter(cli)
    model_id, model_display = resolve_subagent_model(model, cli)

    # Per-CLI workdir setup. Codex requires --cd <existing dir>; we
    # extract the workdir from the argv (it is the value following --cd)
    # and `mkdir -p` it inside the container BEFORE exec.
    argv = adapter.build_argv(
        task=task,
        system_prompt=system_prompt,
        model=model_id,
        max_turns=max_turns,
        timeout_s=timeout_s,
        resume_session_id=resume_session_id,
        plan_file=plan_file,
    )

    if cli == Cli.CODEX and "--cd" in argv:
        cd_target = argv[argv.index("--cd") + 1]
        # mkdir inside the container (NOT on orchestrator host) — the
        # cd_target lives on the sandbox container's tmpfs.
        mkdir_cmd = f"mkdir -p {shlex.quote(cd_target)}"
        await asyncio.to_thread(
            _execute_bash_capture, container, mkdir_cmd, 10,
        )

    quoted_argv = " ".join(shlex.quote(a) for a in argv)
    shell_cmd = (
        f"cd {shlex.quote(working_directory)} && "
        f"{headers_env}{quoted_argv}"
    )

    proc = await asyncio.to_thread(
        _execute_bash_capture, container, shell_cmd, timeout_s,
    )
    result = adapter.parse_result(
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
    )
    return result, model_id, model_display
