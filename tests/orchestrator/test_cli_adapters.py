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


# ===========================================================================
# CodexAdapter — gap-closure tests (D-17 / D-18, plan 02-07)
# ===========================================================================

def test_codex_parse_result_usage_cost_extraction():
    """Codex adapter tracks token counts from turn.completed usage events.

    The codex protocol does NOT surface a USD cost (cost_usd is always None
    per the adapter docstring and Pitfall 4). Instead, the adapter accumulates
    tokens_in / tokens_out from turn.completed events. This test verifies that
    a turn.completed event with a usage block does NOT crash the parser and
    that cost_usd stays None (the documented behaviour — not a gap to fix here).
    Token counters are internal locals; we assert the visible field that IS
    documented: cost_usd == None.
    """
    from cli_adapters.codex import CodexAdapter
    stdout = "\n".join([
        json.dumps({"type": "turn.completed", "turn_id": "t-1",
                    "usage": {"input_tokens": 500, "output_tokens": 20}}),
        json.dumps({"type": "item.completed", "item": {
            "type": "message",
            "content": [{"type": "text", "text": "result with tokens"}],
        }}),
    ])
    result = CodexAdapter().parse_result(stdout=stdout, stderr="", returncode=0)
    # Codex never computes USD cost — cost_usd must remain None.
    assert result.cost_usd is None
    assert result.text == "result with tokens"
    assert result.is_error is False


def test_codex_parse_result_empty_event_stream():
    """Empty stdout with rc=0 should not raise and should produce is_error=False.

    Codex uses rc-based error detection only; rc=0 with no events is not
    classified as an error. text falls back to stdout (empty string).
    """
    from cli_adapters.codex import CodexAdapter
    result = CodexAdapter().parse_result(stdout="", stderr="", returncode=0)
    assert result.is_error is False
    assert result.returncode == 0
    assert result.text == ""


def test_codex_parse_result_error_event_in_stream():
    """Codex protocol has no application-level error event type.

    The adapter does not handle a codex 'error' event specially; rc=0 with
    any non-recognised event type produces is_error=False. This test documents
    the current behaviour explicitly so future maintainers know that codex
    error detection is entirely rc-based (unlike opencode which has et=='error').

    If a future codex protocol version emits error events, this test will fail
    and an adapter update will be required (follow-up: REQ-MCP-14 or newer).
    """
    from cli_adapters.codex import CodexAdapter
    # Construct a synthetic 'error' event in codex-style JSONL.
    stdout = json.dumps({"type": "error", "message": "model unavailable"})
    result = CodexAdapter().parse_result(stdout=stdout, stderr="", returncode=0)
    # Current behaviour: no special handling → is_error driven by rc only.
    assert result.is_error is False  # rc=0, no rc-based error gate triggered
    assert result.returncode == 0


# ===========================================================================
# OpenCodeAdapter — gap-closure tests (D-17 / D-18, plan 02-07)
# ===========================================================================

def test_opencode_parse_result_multi_event_stream():
    """Multi-event stdout: assistant-message-completed + step-finish + message-completed.

    The adapter uses "last seen wins" for text extraction across all three
    event types. A step-finish event in between should update text only if
    it has a text/content field; message-completed with text sets the final.
    """
    from cli_adapters.opencode import OpenCodeAdapter
    stdout = "\n".join([
        json.dumps({"type": "assistant-message-completed", "text": "first message"}),
        json.dumps({"type": "step-finish", "cost": 0.001}),
        json.dumps({"type": "message-completed", "text": "final answer"}),
    ])
    result = OpenCodeAdapter().parse_result(stdout=stdout, stderr="", returncode=0)
    assert result.is_error is False
    assert result.text == "final answer"
    assert result.cost_usd is not None
    assert abs(result.cost_usd - 0.001) < 1e-9


def test_opencode_parse_result_empty_stdout():
    """Empty stdout with rc=0: adapter should not raise.

    is_error is driven by returncode != 0 initially (rc=0 → False).
    text falls back through last_message_text (empty) → stdout (empty) → stderr (empty).
    """
    from cli_adapters.opencode import OpenCodeAdapter
    result = OpenCodeAdapter().parse_result(stdout="", stderr="", returncode=0)
    assert result.is_error is False
    assert result.returncode == 0
    assert result.text == ""


def test_opencode_parse_result_malformed_json_between_valid_events():
    """A malformed JSON line between valid events must not stop parsing.

    The adapter skips json.JSONDecodeError and continues to the next line.
    The final valid event must still be extracted.
    """
    from cli_adapters.opencode import OpenCodeAdapter
    stdout = "\n".join([
        json.dumps({"type": "assistant-message-completed", "text": "a"}),
        "{not valid json",
        json.dumps({"type": "message-completed", "text": "b"}),
    ])
    result = OpenCodeAdapter().parse_result(stdout=stdout, stderr="", returncode=0)
    assert result.text == "b"
    assert result.is_error is False


def test_opencode_parse_result_error_event_message_extraction():
    """Phase 1 D-11 regression guard: et=='error' sets is_error=True.

    opencode exits with rc=0 on application-level errors but emits an
    {"type": "error", "data": {"message": "..."}} event. The adapter must
    detect this, set is_error=True, and surface the error message prefixed
    with 'opencode error: '.
    """
    from cli_adapters.opencode import OpenCodeAdapter
    stdout = json.dumps({"type": "error", "data": {"message": "upstream auth failed"}})
    result = OpenCodeAdapter().parse_result(stdout=stdout, stderr="", returncode=0)
    assert result.is_error is True
    assert result.text == "opencode error: upstream auth failed"


# ===========================================================================
# ClaudeAdapter — gap-closure tests (D-17 / D-18, plan 02-07)
# ===========================================================================

def test_claude_parse_result_malformed_json():
    """Non-JSON garbage in stdout: adapter must not raise and must not crash.

    ClaudeAdapter wraps parsing in try/except; malformed stdout with rc=0
    should produce is_error=False (no JSON result line found, returncode=0
    so the BLOCKER-1 gate does not fire). text falls back to stdout raw.
    """
    from cli_adapters.claude import ClaudeAdapter
    result = ClaudeAdapter().parse_result(
        stdout="not-json garbage", stderr="", returncode=0
    )
    # No exception raised. text falls back to raw stdout.
    assert result.is_error is False
    assert result.returncode == 0
    # The fallback text is the raw stdout when no JSON result line is found.
    assert "garbage" in result.text


def test_claude_parse_result_empty_stdout():
    """Empty stdout with rc=0: is_error must be False.

    The BLOCKER-1 gate in ClaudeAdapter is `is_error = is_error or (returncode != 0)`.
    With rc=0 and no parseable result line, is_error stays False.
    text is the empty stdout string (the raw fallback).
    """
    from cli_adapters.claude import ClaudeAdapter
    result = ClaudeAdapter().parse_result(stdout="", stderr="", returncode=0)
    assert result.is_error is False
    assert result.returncode == 0
    # text fallback: response_text="" → stdout="" is the assigned value
    assert result.text == ""


def test_claude_parse_result_event_without_content():
    """Result JSON with null 'result' field: adapter must not crash.

    If the result line has type=='result' but result==null (or missing),
    response_text remains "" and the fallback logic kicks in. session_id
    and cost fields should still be extracted when present.
    """
    from cli_adapters.claude import ClaudeAdapter
    stdout = json.dumps({
        "type": "result",
        "result": None,
        "total_cost_usd": 0.0,
        "num_turns": 0,
        "is_error": False,
        "session_id": "sess-abc",
    })
    result = ClaudeAdapter().parse_result(stdout=stdout, stderr="", returncode=0)
    # result field is None → response_text stays "" → fallback to stdout
    assert result.is_error is False
    assert result.returncode == 0
    # session_id="sess-abc" is extracted from the JSON
    assert result.session_id == "sess-abc"
    # cost=0.0 → None (Pitfall 4)
    assert result.cost_usd is None


def test_codex_parse_result_partial_truncated_json():
    """Truncated last line (partial JSON) must be skipped without crashing.

    If the codex stream is cut off mid-event (e.g. timeout kills the process
    mid-write), the adapter should parse all complete events before the
    truncated line and return whatever text was accumulated so far.
    """
    from cli_adapters.codex import CodexAdapter
    stdout = "\n".join([
        json.dumps({"type": "item.completed", "item": {
            "type": "message",
            "content": [{"type": "text", "text": "partial run result"}],
        }}),
        '{"type": "turn.completed", "usage": {"input_tokens": 100,',  # truncated
    ])
    result = CodexAdapter().parse_result(stdout=stdout, stderr="", returncode=0)
    assert result.text == "partial run result"
    assert result.is_error is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
