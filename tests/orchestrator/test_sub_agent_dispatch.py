# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""TEST-04: end-to-end dispatch suite for mcp_tools.sub_agent.

Mocks the subprocess boundary (cli_runtime.dispatch is replaced with an
AsyncMock that returns a synthetic SubAgentResult) and asserts:

1. The MCP tool signature is byte-identical to the v0.9.2.0 contract:
   sub_agent(task, description, ctx, model='', max_turns=0,
             working_directory='/home/assistant', resume_session_id='').
2. dispatch routes to the correct adapter for each SUBAGENT_CLI value
   ({claude, codex, opencode}) — verified by inspecting cli_runtime.resolve_cli()
   under the active env at dispatch time.
3. Cost-guardrail caveat (Phase 7 success criterion 5; PITFALLS.md Pitfall 4):
   when SubAgentResult.cost_usd is None (codex always; opencode when usage
   is missing), the rendered MCP result string contains the literal
   "unavailable" and contains NO "$0.0" / "$0.00" substring.
   When cost_usd is a float, the rendered string contains "$X.XXXX".

The cost rendering branch was inlined into mcp_tools.sub_agent by Phase 5
plan 05-05 (verified at mcp_tools.py:1092-1095). This suite is the
regression guard that prevents future drift.

Mirrors the env-scrub + module-reload pattern from
tests/orchestrator/test_subagent_claude_compat.py so local-dev shells
with model-override env vars exported do not break the assertions.
"""

import asyncio
import importlib
import inspect
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

_SERVER_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "computer-use-server"
)
sys.path.insert(0, _SERVER_DIR)


# ---------------------------------------------------------------------------
# Env scrub — mirror test_subagent_claude_compat.py so local dev does not
# poison the model-resolution assertions.
# ---------------------------------------------------------------------------
_DEV_ENV_VARS_TO_SCRUB = (
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_SUB_AGENT_DEFAULT_MODEL",
    "CODEX_SUB_AGENT_DEFAULT_MODEL",
    "OPENCODE_SUB_AGENT_DEFAULT_MODEL",
    "CODEX_MODEL",
    "OPENCODE_MODEL",
    "OPENCODE_MODEL_ALIASES",
)


def _scrub_dev_env(monkeypatch):
    for var in _DEV_ENV_VARS_TO_SCRUB:
        monkeypatch.delenv(var, raising=False)


def _make_result(*, cost_usd, text="OK", is_error=False, turns=1, returncode=0):
    """Build a synthetic SubAgentResult.

    Matches cli_adapters/result.py SubAgentResult fields exactly
    (frozen dataclass: text, cost_usd, turns, is_error, session_id,
    raw_events, returncode).
    """
    from cli_adapters.result import SubAgentResult
    return SubAgentResult(
        text=text,
        cost_usd=cost_usd,
        turns=turns,
        is_error=is_error,
        session_id="test-session",
        raw_events=[],
        returncode=returncode,
    )


def _make_ctx():
    """Minimal FastMCP Context double — only the methods sub_agent calls."""
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    ctx.info = MagicMock()
    ctx.warning = MagicMock()
    ctx.error = MagicMock()
    return ctx


def _reload_runtime():
    """Reload cli_runtime + mcp_tools so module-level env reads settle.

    Order matters: docker_manager validates SUBAGENT_CLI at import time,
    cli_runtime imports from docker_manager, mcp_tools imports from
    cli_runtime.
    """
    for mod_name in ("docker_manager", "cli_runtime", "mcp_tools"):
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            importlib.import_module(mod_name)


def _unwrap_tool(tool_obj):
    """Return the original async function behind FastMCP @mcp.tool() wrapping."""
    return getattr(tool_obj, "fn", None) or getattr(tool_obj, "__wrapped__", None) or tool_obj


def _install_common_stubs(monkeypatch, mcp_tools, fake_dispatch):
    """Stub the side-effect-heavy collaborators so sub_agent can run on host.

    - cli_dispatch: replaced with the per-test fake (the boundary under test)
    - _get_or_create_container: opaque MagicMock (dispatch never touches it
      because we stub cli_dispatch wholesale)
    - _ensure_gitlab_token: no-op AsyncMock
    - _execute_bash: returns an empty result so the marker-file write +
      _stream_session_logs body bail immediately
    - _validate_chat_id: returns a deterministic ('test', None) tuple so we
      do not depend on contextvar state
    - skill_manager: no real skills lookup
    """
    monkeypatch.setattr(mcp_tools, "cli_dispatch", fake_dispatch)
    monkeypatch.setattr(
        mcp_tools, "_get_or_create_container", lambda *a, **kw: MagicMock()
    )
    monkeypatch.setattr(
        mcp_tools, "_ensure_gitlab_token", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        mcp_tools, "_execute_bash", lambda *a, **kw: {"output": "", "exit_code": 0}
    )
    monkeypatch.setattr(
        mcp_tools, "_validate_chat_id", lambda: ("test", None)
    )
    monkeypatch.setattr(
        mcp_tools.skill_manager, "get_user_skills_sync", lambda *a, **kw: []
    )
    monkeypatch.setattr(
        mcp_tools.skill_manager, "build_sub_agent_skills_text", lambda *a, **kw: ""
    )


# ===========================================================================
# Test 1 — MCP signature regression guard.
# ===========================================================================

def test_signature_is_byte_identical(monkeypatch):
    """v0.9.2.0 contract: sub_agent(task, description, ctx, model='',
    max_turns=0, working_directory='/home/assistant', resume_session_id='').

    Any drift breaks every existing skill caller.
    """
    _scrub_dev_env(monkeypatch)
    monkeypatch.setenv("SUBAGENT_CLI", "claude")
    _reload_runtime()
    import mcp_tools

    fn = _unwrap_tool(mcp_tools.sub_agent)
    sig = inspect.signature(fn)
    params = list(sig.parameters.items())
    names = [n for n, _ in params]

    assert names == [
        "task", "description", "ctx",
        "model", "max_turns", "working_directory", "resume_session_id",
    ], f"sub_agent parameters drifted from v0.9.2.0 contract: {names}"

    defaults = {n: p.default for n, p in params if p.default is not inspect.Parameter.empty}
    assert defaults["model"] == ""
    assert defaults["max_turns"] == 0
    assert defaults["working_directory"] == "/home/assistant"
    assert defaults["resume_session_id"] == ""


# ===========================================================================
# Test 2 — dispatch routes to the correct adapter per SUBAGENT_CLI value.
# ===========================================================================

@pytest.mark.parametrize("cli_value,expected_cli_str", [
    ("claude", "claude"),
    ("codex", "codex"),
    ("opencode", "opencode"),
])
def test_dispatch_routes_to_correct_adapter(
    monkeypatch, cli_value, expected_cli_str,
):
    """resolve_cli() inside the dispatch boundary must reflect SUBAGENT_CLI."""
    _scrub_dev_env(monkeypatch)
    monkeypatch.setenv("SUBAGENT_CLI", cli_value)
    # Phase 2: opencode/codex no longer have hardcoded defaults — set the
    # per-CLI default env so resolve_subagent_model("", ...) doesn't raise
    # before fake_dispatch is reached. The actual id is irrelevant; the test
    # only checks that dispatch was invoked with the right CLI.
    if cli_value == "opencode":
        monkeypatch.setenv("OPENCODE_SUB_AGENT_DEFAULT_MODEL", "anthropic/claude-sonnet-4-6")
    elif cli_value == "codex":
        monkeypatch.setenv("CODEX_SUB_AGENT_DEFAULT_MODEL", "gpt-5-codex")
    _reload_runtime()
    import cli_runtime
    import mcp_tools

    captured = {}

    async def fake_dispatch(**kwargs):
        captured.update(kwargs)
        captured["_cli_seen"] = cli_runtime.resolve_cli()
        # Codex never has cost; claude does; opencode optional.
        cost = 0.0042 if cli_value == "claude" else None
        return (
            _make_result(cost_usd=cost, text="hello world"),
            f"resolved-{cli_value}-model",
            "sonnet",
        )

    _install_common_stubs(monkeypatch, mcp_tools, fake_dispatch)

    fn = _unwrap_tool(mcp_tools.sub_agent)
    # claude is the only CLI where 'sonnet' is a valid model alias for the
    # default model resolution path that runs inside sub_agent BEFORE
    # dispatch. For codex/opencode we pass an empty model so the per-CLI
    # default kicks in inside resolve_subagent_model (called by the real
    # dispatch — but we replace dispatch wholesale, so the model value is
    # captured verbatim). Either way the model arg flows through to
    # captured kwargs and we only assert the routing.
    result = asyncio.run(fn(
        task="hello", description="d", ctx=_make_ctx(),
    ))

    seen_cli = captured.get("_cli_seen")
    assert seen_cli is not None, "fake_dispatch was not invoked"
    assert seen_cli.value == expected_cli_str, (
        f"resolve_cli() returned {seen_cli!r}; expected {expected_cli_str!r}"
    )
    # Sanity: dispatch was awaited once (captured kwargs are present).
    assert "task" in captured
    assert "system_prompt" in captured
    # Result string carries the completion banner + the synthetic text.
    assert "Sub-Agent Completed" in result, (
        f"missing completion banner; first 300 chars: {result[:300]}"
    )
    assert "hello world" in result


# ===========================================================================
# Test 3 — cost rendering: cost_usd=None must render "unavailable".
# ===========================================================================

@pytest.mark.parametrize("cli_value", ["codex", "opencode"])
def test_cost_rendering_unavailable_for_none(monkeypatch, cli_value):
    """Pitfall 4 + Phase 7 success criterion 5.

    cost_usd=None (codex always; opencode when usage is missing) must
    render as the literal "unavailable" — NEVER as "$0.00" / "$0.0000",
    which would mislead the operator into thinking the run was free.
    """
    _scrub_dev_env(monkeypatch)
    monkeypatch.setenv("SUBAGENT_CLI", cli_value)
    # Phase 2: per-CLI default env required for opencode/codex.
    if cli_value == "opencode":
        monkeypatch.setenv("OPENCODE_SUB_AGENT_DEFAULT_MODEL", "anthropic/claude-sonnet-4-6")
    elif cli_value == "codex":
        monkeypatch.setenv("CODEX_SUB_AGENT_DEFAULT_MODEL", "gpt-5-codex")
    _reload_runtime()
    import mcp_tools

    async def fake_dispatch(**kwargs):
        return (
            _make_result(cost_usd=None, text="ok"),
            "model-id",
            "model-display",
        )

    _install_common_stubs(monkeypatch, mcp_tools, fake_dispatch)

    fn = _unwrap_tool(mcp_tools.sub_agent)
    result = asyncio.run(fn(
        task="t", description="d", ctx=_make_ctx(),
    ))

    assert "unavailable" in result, (
        f"expected literal 'unavailable' in result for cost_usd=None; "
        f"first 400 chars: {result[:400]}"
    )
    # Negative assertions: never let a None cost render as a dollar amount.
    assert "$0.0" not in result, (
        f"cost_usd=None must NOT render as $0.0X; first 400 chars: {result[:400]}"
    )
    assert "$0.00" not in result
    assert "$0.0000" not in result


def test_cost_rendering_dollar_for_float(monkeypatch):
    """Positive case: a float cost renders as $X.XXXX (4-decimal USD)."""
    _scrub_dev_env(monkeypatch)
    monkeypatch.setenv("SUBAGENT_CLI", "claude")
    _reload_runtime()
    import mcp_tools

    async def fake_dispatch(**kwargs):
        return (
            _make_result(cost_usd=0.0042, text="ok"),
            "claude-sonnet-4-6",
            "sonnet",
        )

    _install_common_stubs(monkeypatch, mcp_tools, fake_dispatch)

    fn = _unwrap_tool(mcp_tools.sub_agent)
    result = asyncio.run(fn(
        task="t", description="d", ctx=_make_ctx(),
    ))

    assert "$0.0042" in result, (
        f"expected '$0.0042' for cost_usd=0.0042; first 400 chars: {result[:400]}"
    )
    assert "unavailable" not in result, (
        "float cost must NOT render as 'unavailable'"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
