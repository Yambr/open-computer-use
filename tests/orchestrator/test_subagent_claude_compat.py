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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
