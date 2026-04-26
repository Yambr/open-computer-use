# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""TEST-03: per-CLI adapter argv-build + result-parse coverage.

Plan 05-04 of Phase 5. Covers:
  - CodexAdapter.build_argv shape (D1 verbatim)
  - CodexAdapter.parse_result against tests/fixtures/cli/codex_run.jsonl
  - OpenCodeAdapter.build_argv shape (D3 verbatim)
  - OpenCodeAdapter.parse_result against tests/fixtures/cli/opencode_run.jsonl
  - ClaudeAdapter.parse_result against tests/fixtures/cli/claude_v0.9.2.0_stdout.json
    (the build_argv byte-compat is in test_subagent_claude_compat.py — Phase 4)
  - ClaudeAdapter.parse_result returncode-as-error gate (BLOCKER 1):
    empty stdout + rc != 0 must produce is_error=True.

The Claude byte-compat invariant has TWO halves:
  - argv side: test_subagent_claude_compat.py + claude_v0.9.2.0_argv.json
  - parse side: this file + claude_v0.9.2.0_stdout.json
Both must stay green to keep ROADMAP success criterion #1 satisfied.

Note on test_claude_parse_result_nonzero_returncode_is_error:
  This test is marked pytest.mark.xfail(strict=True) in plan 05-04 because
  ClaudeAdapter.parse_result today (post-04, pre-05-05) ignores returncode
  and always returns the JSON-parsed is_error flag (False when stdout has
  no result line). Plan 05-05 Task 0 patches ClaudeAdapter to set
  `is_error = is_error or (returncode != 0)` and to thread returncode into
  SubAgentResult.returncode; once that lands, this test flips to PASS,
  strict=True turns the unexpected pass into a hard failure so the xfail
  marker is forced to be removed in lockstep with the fix. This is the
  agreed BLOCKER 1 regression guard handover from 05-04 -> 05-05.
"""

import json
import os
import sys

import pytest

_SERVER_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "computer-use-server"
)
sys.path.insert(0, _SERVER_DIR)

_FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "cli"
)


# ===========================================================================
# CodexAdapter
# ===========================================================================

def test_codex_build_argv_shape():
    from cli_adapters.codex import CodexAdapter
    argv = CodexAdapter().build_argv(
        task="run the thing",
        system_prompt="you are codex",
        model="gpt-5-codex",
        max_turns=25,
        timeout_s=3600,
    )
    # Head: literal command + subcommand
    assert argv[0:2] == ["codex", "exec"]
    # Required flags present (D1)
    for flag in ("--ephemeral", "--json", "--full-auto",
                 "--skip-git-repo-check", "--output-last-message",
                 "--cd", "--model"):
        assert flag in argv, f"missing flag {flag!r} in codex argv: {argv}"
    # --model carries through
    assert argv[argv.index("--model") + 1] == "gpt-5-codex"
    # --cd points at /tmp/codex-agents-<12-hex>
    cd_target = argv[argv.index("--cd") + 1]
    assert cd_target.startswith("/tmp/codex-agents-")
    assert len(cd_target.split("-")[-1]) == 12, cd_target
    # --output-last-message points inside the same workdir
    last_msg = argv[argv.index("--output-last-message") + 1]
    assert last_msg.startswith(cd_target + "/"), (cd_target, last_msg)
    # Final arg is the combined system_prompt + "---" + task
    assert "you are codex" in argv[-1]
    assert "---" in argv[-1]
    assert "run the thing" in argv[-1]
    # Pitfall: --full-auto is the safe choice, not --dangerously-bypass...
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv


def test_codex_build_argv_empty_system_prompt():
    from cli_adapters.codex import CodexAdapter
    argv = CodexAdapter().build_argv(
        task="hi", system_prompt="", model="gpt-5-codex",
        max_turns=25, timeout_s=60,
    )
    assert argv[-1] == "hi"


def test_codex_build_argv_warns_on_resume_session_id(capfd):
    from cli_adapters.codex import CodexAdapter
    CodexAdapter().build_argv(
        task="t", system_prompt="", model="gpt-5-codex",
        max_turns=25, timeout_s=60,
        resume_session_id="ignored-uuid",
    )
    err = capfd.readouterr().err
    assert "codex-adapter" in err
    assert "ignored-uuid" in err


def test_codex_parse_result_against_fixture():
    from cli_adapters.codex import CodexAdapter
    with open(os.path.join(_FIXTURE_DIR, "codex_run.jsonl")) as f:
        stdout = f.read()
    result = CodexAdapter().parse_result(stdout=stdout, stderr="", returncode=0)
    assert result.text == "Hello from codex. The answer is 42."
    # Pitfall 4: cost is None for codex.
    assert result.cost_usd is None
    assert result.turns is None
    assert result.session_id is None
    assert result.is_error is False
    assert result.returncode == 0
    # raw_events preserved.
    assert len(result.raw_events) >= 3
    assert any(e.get("type") == "turn.completed" for e in result.raw_events)


def test_codex_parse_result_error_returncode():
    from cli_adapters.codex import CodexAdapter
    result = CodexAdapter().parse_result(
        stdout="", stderr="something exploded", returncode=1
    )
    assert result.is_error is True
    assert result.returncode == 1


def test_codex_parse_result_returncode_field_propagated():
    """SubAgentResult.returncode is the rc passed in (added in plan 05-02 Task 0)."""
    from cli_adapters.codex import CodexAdapter
    for rc in (0, 1, 124, 137, 143):
        result = CodexAdapter().parse_result(stdout="", stderr="", returncode=rc)
        assert result.returncode == rc


def test_codex_parse_result_skips_malformed_lines():
    from cli_adapters.codex import CodexAdapter
    bad = '\n'.join([
        "this is not json",
        json.dumps({"type": "item.completed", "item": {"type": "message", "content": [{"type": "text", "text": "ok"}]}}),
        "{also not valid",
    ])
    result = CodexAdapter().parse_result(stdout=bad, stderr="", returncode=0)
    assert result.text == "ok"


# ===========================================================================
# OpenCodeAdapter
# ===========================================================================

def test_opencode_build_argv_shape():
    from cli_adapters.opencode import OpenCodeAdapter
    argv = OpenCodeAdapter().build_argv(
        task="say hi",
        system_prompt="you are oc",
        model="anthropic/claude-sonnet-4-6",
        max_turns=25,
        timeout_s=60,
    )
    assert argv[0:2] == ["opencode", "run"]
    # combined prompt is positional arg #3 (index 2)
    assert "you are oc" in argv[2]
    assert "---" in argv[2]
    assert "say hi" in argv[2]
    # --model + value
    assert argv[argv.index("--model") + 1] == "anthropic/claude-sonnet-4-6"
    # --format json
    assert argv[argv.index("--format") + 1] == "json"
    # --dangerously-skip-permissions present
    assert "--dangerously-skip-permissions" in argv


def test_opencode_build_argv_empty_system_prompt():
    from cli_adapters.opencode import OpenCodeAdapter
    argv = OpenCodeAdapter().build_argv(
        task="hi", system_prompt="",
        model="openrouter/qwen/qwen-3-coder",
        max_turns=25, timeout_s=60,
    )
    assert argv[2] == "hi"


def test_opencode_build_argv_warns_on_resume_session_id(capfd):
    from cli_adapters.opencode import OpenCodeAdapter
    OpenCodeAdapter().build_argv(
        task="t", system_prompt="",
        model="anthropic/claude-sonnet-4-6",
        max_turns=25, timeout_s=60,
        resume_session_id="ignored-uuid",
    )
    err = capfd.readouterr().err
    assert "opencode-adapter" in err
    assert "ignored-uuid" in err


def test_opencode_parse_result_against_fixture():
    from cli_adapters.opencode import OpenCodeAdapter
    with open(os.path.join(_FIXTURE_DIR, "opencode_run.jsonl")) as f:
        stdout = f.read()
    result = OpenCodeAdapter().parse_result(stdout=stdout, stderr="", returncode=0)
    assert result.text == "Hello from opencode. Answer: forty-two."
    # cost summed across two step-finish events: 0.0042 + 0.0011 = 0.0053
    assert result.cost_usd is not None
    assert abs(result.cost_usd - 0.0053) < 1e-9
    assert result.turns is None
    assert result.session_id is None
    assert result.is_error is False
    assert result.returncode == 0
    assert any(e.get("type") == "step-finish" for e in result.raw_events)


def test_opencode_parse_result_no_cost_path():
    from cli_adapters.opencode import OpenCodeAdapter
    sample = json.dumps({"type": "message-completed", "text": "done"})
    result = OpenCodeAdapter().parse_result(stdout=sample, stderr="", returncode=0)
    assert result.text == "done"
    assert result.cost_usd is None


def test_opencode_parse_result_returncode_field_propagated():
    """SubAgentResult.returncode is the rc passed in (added in plan 05-02 Task 0)."""
    from cli_adapters.opencode import OpenCodeAdapter
    for rc in (0, 1, 124, 137, 143):
        result = OpenCodeAdapter().parse_result(stdout="", stderr="", returncode=rc)
        assert result.returncode == rc


def test_opencode_parse_result_content_blocks():
    from cli_adapters.opencode import OpenCodeAdapter
    sample = json.dumps({
        "type": "assistant-message-completed",
        "content": [{"type": "text", "text": "from-blocks"}],
    })
    result = OpenCodeAdapter().parse_result(stdout=sample, stderr="", returncode=0)
    assert result.text == "from-blocks"


def test_opencode_parse_result_usage_total_cost_path():
    from cli_adapters.opencode import OpenCodeAdapter
    sample = "\n".join([
        json.dumps({"type": "step-finish", "usage": {"total_cost": 0.01}}),
        json.dumps({"type": "step-finish", "usage": {"total_cost": 0.02}}),
        json.dumps({"type": "assistant-message-completed", "text": "ok"}),
    ])
    result = OpenCodeAdapter().parse_result(stdout=sample, stderr="", returncode=0)
    assert abs(result.cost_usd - 0.03) < 1e-9


# ===========================================================================
# ClaudeAdapter — parse_result roundtrip (the build_argv side is in
# test_subagent_claude_compat.py and stays untouched).
# ===========================================================================

@pytest.fixture(scope="module")
def claude_stdout_fixture():
    with open(os.path.join(_FIXTURE_DIR, "claude_v0.9.2.0_stdout.json")) as f:
        return json.load(f)


def test_claude_parse_result_happy_path_byte_compat(claude_stdout_fixture):
    from cli_adapters.claude import ClaudeAdapter
    case = claude_stdout_fixture["happy_path"]
    result = ClaudeAdapter().parse_result(
        stdout=case["stdout"], stderr=case["stderr"], returncode=case["returncode"],
    )
    exp = case["expected"]
    assert result.text == exp["text"]
    assert result.cost_usd == exp["cost_usd"]
    assert result.turns == exp["turns"]
    assert result.is_error is exp["is_error"]
    assert result.session_id == exp["session_id"]


def test_claude_parse_result_zero_cost_becomes_none(claude_stdout_fixture):
    """Pitfall 4: total_cost_usd=0.0 becomes None (render 'unavailable'),
    same for num_turns=0 and session_id==''."""
    from cli_adapters.claude import ClaudeAdapter
    case = claude_stdout_fixture["zero_cost_path"]
    result = ClaudeAdapter().parse_result(
        stdout=case["stdout"], stderr=case["stderr"], returncode=case["returncode"],
    )
    exp = case["expected"]
    assert result.text == exp["text"]
    assert result.cost_usd is None
    assert result.turns is None
    assert result.session_id is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BLOCKER 1: ClaudeAdapter.parse_result returncode-as-error gate "
        "lands in plan 05-05 Task 0. Until that patch ships, parse_result "
        "ignores returncode and returns is_error=False for empty stdout + "
        "rc!=0. strict=True turns the unexpected pass after 05-05 lands "
        "into a hard failure so this xfail marker is forced to be removed "
        "in lockstep with the ClaudeAdapter fix."
    ),
)
def test_claude_parse_result_nonzero_returncode_is_error():
    """BLOCKER 1 regression guard.

    v0.9.2.0 detected killed/timed-out claude runs at the mcp_tools layer
    by checking exit_code in (137, 143, 124). Phase 5 lifts that into
    ClaudeAdapter.parse_result so the caller can act on
    SubAgentResult.is_error consistently across all CLIs.

    Without this fix, claude rc=137/143/124 with no JSON `result` line
    in stdout would silently return is_error=False and an empty text —
    plan 05-05's Sub-Agent-Terminated branch would never fire and the
    operator would see a "successful" but empty result.

    After plan 05-05 Task 0 patches ClaudeAdapter.parse_result to set
    `is_error = is_error or (returncode != 0)` and to thread the
    returncode into SubAgentResult.returncode, this test passes and the
    xfail marker above MUST be removed.
    """
    from cli_adapters.claude import ClaudeAdapter
    adapter = ClaudeAdapter()
    for rc in (124, 137, 143, 1, -9, -15):
        result = adapter.parse_result(stdout="", stderr="killed", returncode=rc)
        assert result.is_error is True, (
            f"rc={rc} with empty stdout must set is_error=True; got {result}"
        )
        # Plan 05-02 Task 0 added returncode field; plan 05-05 Task 0 populates it.
        assert result.returncode == rc, (
            f"rc={rc} must be threaded into SubAgentResult.returncode; "
            f"got {result.returncode}"
        )


def test_claude_parse_result_happy_path_returncode_zero():
    """Successful claude run: returncode=0 must NOT flip is_error to True.

    Today (pre-05-05) ClaudeAdapter does not pass returncode into
    SubAgentResult; the dataclass default returncode=0 applies, so
    result.returncode == 0 holds. After 05-05 Task 0 explicitly threads
    the rc, the same assertion holds for the rc=0 input. Either way:
    is_error stays False and returncode stays 0.
    """
    from cli_adapters.claude import ClaudeAdapter
    good_stdout = json.dumps({
        "type": "result",
        "result": "ok",
        "total_cost_usd": 0.5,
        "num_turns": 3,
        "is_error": False,
        "session_id": "s1",
    })
    result = ClaudeAdapter().parse_result(stdout=good_stdout, stderr="", returncode=0)
    assert result.is_error is False
    assert result.text == "ok"
    assert result.returncode == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
