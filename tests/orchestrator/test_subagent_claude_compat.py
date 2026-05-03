# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""ADAPT-02 byte-compat: ClaudeAdapter.build_argv must produce argv
byte-identical to the v0.9.2.0 production claude_command (argv layer).

The lifted code in cli_adapters/claude.py is DORMANT in Phase 4 (production
path stays in mcp_tools.sub_agent through Phase 6). This snapshot test is
the forcing function that prevents drift between the two copies, so when
Phase 7 flips dispatch through cli_runtime, the change is provably zero
regression for SUBAGENT_CLI=claude.

The shell-execution wrapper (`cd <wd> && <headers_env> ...`) lives in
mcp_tools.sub_agent and is NOT part of build_argv's contract — only the
argv list itself is asserted byte-identical.
"""

import json
import os
import sys

import pytest

_SERVER_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "computer-use-server"
)
sys.path.insert(0, _SERVER_DIR)

_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "cli", "claude_v0.9.2.0_argv.json"
)


@pytest.fixture(scope="module")
def fixture():
    with open(_FIXTURE_PATH) as f:
        return json.load(f)


def test_new_session_argv_byte_compat(fixture):
    """NEW SESSION branch (resume_session_id == ""): 15-element argv with
    --model + --append-system-prompt before the common flags."""
    from cli_adapters.claude import ClaudeAdapter
    adapter = ClaudeAdapter()
    case = fixture["new_session"]
    actual = adapter.build_argv(**case["inputs"])
    assert actual == case["expected_argv"], (
        f"build_argv NEW SESSION drifted from v0.9.2.0 baseline.\n"
        f"  expected: {case['expected_argv']}\n"
        f"  actual:   {actual}\n"
    )
    assert len(actual) == 15, f"expected 15-element argv, got {len(actual)}"


def test_resume_argv_byte_compat(fixture):
    """RESUME branch (resume_session_id non-empty): 13-element argv with
    --resume <session_id> in place of --model + --append-system-prompt."""
    from cli_adapters.claude import ClaudeAdapter
    adapter = ClaudeAdapter()
    case = fixture["resume"]
    actual = adapter.build_argv(**case["inputs"])
    assert actual == case["expected_argv"], (
        f"build_argv RESUME drifted from v0.9.2.0 baseline.\n"
        f"  expected: {case['expected_argv']}\n"
        f"  actual:   {actual}\n"
    )
    assert len(actual) == 13, f"expected 13-element argv, got {len(actual)}"


def test_disallowed_tools_value_is_unquoted(fixture):
    """The original mcp_tools.py:957 emits `--disallowedTools 'AskUserQuestion,ExitPlanMode'`
    inside a SHELL command string — the single quotes are shell quoting, not part
    of the argv value. In argv form the value is the literal string
    `AskUserQuestion,ExitPlanMode` with no quotes (RESEARCH.md line 215, plan
    04-02 SUMMARY line 97)."""
    for case_key in ("new_session", "resume"):
        argv = fixture[case_key]["expected_argv"]
        idx = argv.index("--disallowedTools")
        assert argv[idx + 1] == "AskUserQuestion,ExitPlanMode", (
            f"{case_key}: --disallowedTools value must be unquoted, got {argv[idx + 1]!r}"
        )


def test_parse_result_minimal_roundtrip():
    """parse_result consumes Claude's --output-format json line and populates
    SubAgentResult correctly. Smoke test (the format hasn't changed and won't
    change in Phase 4) plus the Pitfall 4 zero-cost-becomes-None invariant."""
    from cli_adapters.claude import ClaudeAdapter
    adapter = ClaudeAdapter()
    line = json.dumps({
        "type": "result",
        "result": "task complete",
        "total_cost_usd": 0.123,
        "num_turns": 5,
        "is_error": False,
        "session_id": "sess-xyz",
    })
    res = adapter.parse_result(stdout=line, stderr="", returncode=0)
    assert res.text == "task complete"
    assert res.cost_usd == 0.123
    assert res.turns == 5
    assert res.is_error is False
    assert res.session_id == "sess-xyz"

    # Pitfall 4: cost_usd -> None when 0.0 (render "unavailable", not "$0.00").
    zero_cost_line = json.dumps({
        "type": "result", "result": "x", "total_cost_usd": 0.0,
        "num_turns": 0, "is_error": False, "session_id": "",
    })
    res2 = adapter.parse_result(stdout=zero_cost_line, stderr="", returncode=0)
    assert res2.cost_usd is None
    assert res2.turns is None
    assert res2.session_id is None


# === Phase 5 / plan 05-06: end-to-end dispatch byte-compat ===
# Plan 05-05 flipped mcp_tools.sub_agent from inline claude_command to
# cli_runtime.dispatch -> ClaudeAdapter -> _execute_bash_capture. These
# tests assert the assembled shell command and the parsed SubAgentResult
# are byte-identical to what v0.9.2.0 would have produced for the same
# inputs.

import asyncio
import shlex as _shlex_mod
from types import SimpleNamespace
from unittest.mock import patch

# WARNING 2 fix: scrub model-override env vars so local-dev shells (where
# a developer might have e.g. ANTHROPIC_DEFAULT_SONNET_MODEL=my-deployment
# exported) don't break the byte-compat assertions. CI is clean; local
# dev gets the same guarantees.
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


def test_claude_dispatch_byte_compat(fixture, monkeypatch):
    """SUBAGENT_CLI=claude (default): cli_runtime.dispatch builds the same
    shell command as v0.9.2.0's mcp_tools.sub_agent inline claude_command,
    and parse_result returns the same SubAgentResult.

    We mock _execute_bash_capture to capture the shell command without
    needing a Docker container, then return a known stdout that the
    ClaudeAdapter.parse_result is expected to digest into a known
    SubAgentResult.
    """
    _scrub_dev_env(monkeypatch)

    # Drop modules so cli_runtime re-imports cleanly under the test env.
    for mod in ("cli_runtime", "docker_manager"):
        sys.modules.pop(mod, None)

    # Import the freshly-loaded dispatch + Cli.
    from cli_runtime import dispatch as cli_dispatch, Cli
    # Sanity: default SUBAGENT_CLI resolves to claude.
    from cli_runtime import resolve_cli
    assert resolve_cli() == Cli.CLAUDE

    # Inputs mirror the v0.9.2.0 NEW SESSION fixture. mcp_tools.sub_agent
    # passes these via cli_dispatch(...).
    case = fixture["new_session"]
    inputs = case["inputs"]
    expected_argv = case["expected_argv"]

    # The captured shell command we expect dispatch to construct:
    #   cd <wd> && [headers_env]<shlex.quote(argv) joined>
    working_directory = "/home/assistant"
    headers_env = ""  # No user_email path -> no ANTHROPIC_CUSTOM_HEADERS.
    expected_quoted = " ".join(_shlex_mod.quote(a) for a in expected_argv)
    expected_shell_cmd = (
        f"cd {_shlex_mod.quote(working_directory)} && "
        f"{headers_env}{expected_quoted}"
    )

    # Stub stdout fed to ClaudeAdapter.parse_result.
    with open(_FIXTURE_PATH.replace("argv.json", "stdout.json")) as f:
        stdout_fixture = json.load(f)
    happy = stdout_fixture["happy_path"]

    captured_cmd = {}

    def _fake_capture(container, command, timeout=None):
        captured_cmd["cmd"] = command
        captured_cmd["timeout"] = timeout
        return SimpleNamespace(
            stdout=happy["stdout"],
            stderr=happy["stderr"],
            returncode=happy["returncode"],
        )

    with patch("cli_runtime._execute_bash_capture", side_effect=_fake_capture):
        sub_result, model_id, model_display = asyncio.run(
            cli_dispatch(
                container=object(),  # opaque - _fake_capture ignores it
                task=inputs["task"],
                system_prompt=inputs["system_prompt"],
                model="sonnet",  # alias resolves to inputs["model"] via resolve_subagent_model
                max_turns=inputs["max_turns"],
                timeout_s=inputs["timeout_s"],
                working_directory=working_directory,
                resume_session_id="",
                plan_file="",
                headers_env=headers_env,
            )
        )

    # === Assert 1: shell command is byte-identical to v0.9.2.0 ===
    assert captured_cmd["cmd"] == expected_shell_cmd, (
        "Dispatch produced a shell command different from v0.9.2.0:\n"
        f"  expected: {expected_shell_cmd}\n"
        f"  actual:   {captured_cmd['cmd']}\n"
    )
    # Timeout passed through to the executor.
    assert captured_cmd["timeout"] == inputs["timeout_s"]

    # === Assert 2: parsed SubAgentResult matches the parse-side fixture ===
    exp = happy["expected"]
    assert sub_result.text == exp["text"]
    assert sub_result.cost_usd == exp["cost_usd"]
    assert sub_result.turns == exp["turns"]
    assert sub_result.session_id == exp["session_id"]
    assert sub_result.is_error is exp["is_error"]

    # === Assert 3: model resolution preserved v0.9.2.0 alias semantics ===
    # "sonnet" -> "claude-sonnet-4-6" (default), display "sonnet".
    assert model_id == "claude-sonnet-4-6"
    assert model_display == "sonnet"


def test_claude_dispatch_resume_byte_compat(fixture, monkeypatch):
    """RESUME branch byte-compat: same as above but with resume_session_id set.
    Verifies the resume argv (no --model, no --append-system-prompt) is
    assembled identically to v0.9.2.0."""
    _scrub_dev_env(monkeypatch)

    for mod in ("cli_runtime", "docker_manager"):
        sys.modules.pop(mod, None)

    from cli_runtime import dispatch as cli_dispatch
    case = fixture["resume"]
    inputs = case["inputs"]
    expected_argv = case["expected_argv"]

    working_directory = "/home/assistant"
    headers_env = ""
    expected_quoted = " ".join(_shlex_mod.quote(a) for a in expected_argv)
    expected_shell_cmd = (
        f"cd {_shlex_mod.quote(working_directory)} && "
        f"{headers_env}{expected_quoted}"
    )

    captured_cmd = {}

    def _fake_capture(container, command, timeout=None):
        captured_cmd["cmd"] = command
        return SimpleNamespace(
            stdout='{"type": "result", "result": "resumed ok", '
                   '"total_cost_usd": 0.05, "num_turns": 3, '
                   '"is_error": false, "session_id": "abc-123-session"}',
            stderr="",
            returncode=0,
        )

    with patch("cli_runtime._execute_bash_capture", side_effect=_fake_capture):
        sub_result, _, _ = asyncio.run(
            cli_dispatch(
                container=object(),
                task=inputs["task"],
                system_prompt=inputs["system_prompt"],
                model="sonnet",
                max_turns=inputs["max_turns"],
                timeout_s=inputs["timeout_s"],
                working_directory=working_directory,
                resume_session_id=inputs["resume_session_id"],
                plan_file="",
                headers_env=headers_env,
            )
        )

    assert captured_cmd["cmd"] == expected_shell_cmd, (
        f"Resume dispatch shell command drifted from v0.9.2.0:\n"
        f"  expected: {expected_shell_cmd}\n"
        f"  actual:   {captured_cmd['cmd']}\n"
    )
    assert sub_result.text == "resumed ok"
    assert sub_result.session_id == "abc-123-session"


def test_claude_dispatch_with_headers_env_byte_compat(fixture, monkeypatch):
    """Headers env (ANTHROPIC_CUSTOM_HEADERS path): when mcp_tools passes a
    non-empty headers_env (because user_email is set), dispatch concatenates
    it BEFORE the argv - exactly the v0.9.2.0 shape."""
    _scrub_dev_env(monkeypatch)

    for mod in ("cli_runtime", "docker_manager"):
        sys.modules.pop(mod, None)
    from cli_runtime import dispatch as cli_dispatch

    case = fixture["new_session"]
    inputs = case["inputs"]
    expected_argv = case["expected_argv"]

    working_directory = "/home/assistant"
    # Mirrors mcp_tools.sub_agent's headers_env construction (already shlex.quote'd).
    headers_env = (
        f"ANTHROPIC_CUSTOM_HEADERS="
        f"{_shlex_mod.quote('x-openwebui-user-email: alice@example.com')} "
    )
    expected_quoted = " ".join(_shlex_mod.quote(a) for a in expected_argv)
    expected_shell_cmd = (
        f"cd {_shlex_mod.quote(working_directory)} && "
        f"{headers_env}{expected_quoted}"
    )

    captured_cmd = {}

    def _fake_capture(container, command, timeout=None):
        captured_cmd["cmd"] = command
        return SimpleNamespace(
            stdout='{"type": "result", "result": "ok", "total_cost_usd": 0.1, '
                   '"num_turns": 1, "is_error": false, "session_id": "s1"}',
            stderr="",
            returncode=0,
        )

    with patch("cli_runtime._execute_bash_capture", side_effect=_fake_capture):
        asyncio.run(
            cli_dispatch(
                container=object(),
                task=inputs["task"],
                system_prompt=inputs["system_prompt"],
                model="sonnet",
                max_turns=inputs["max_turns"],
                timeout_s=inputs["timeout_s"],
                working_directory=working_directory,
                resume_session_id="",
                plan_file="",
                headers_env=headers_env,
            )
        )

    assert captured_cmd["cmd"] == expected_shell_cmd, (
        f"Dispatch with headers_env drifted from v0.9.2.0 contract:\n"
        f"  expected: {expected_shell_cmd}\n"
        f"  actual:   {captured_cmd['cmd']}\n"
    )
    # The ANTHROPIC_CUSTOM_HEADERS prefix appears verbatim (with the shell
    # quoting that mcp_tools.sub_agent applied) - preserves GATEWAY-07
    # contract from v0.8.12.9.
    assert "ANTHROPIC_CUSTOM_HEADERS=" in captured_cmd["cmd"]
    assert "x-openwebui-user-email: alice@example.com" in captured_cmd["cmd"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
