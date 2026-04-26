# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Claude Code CLI adapter — byte-identical lift of mcp_tools.py.

LIFTED FROM (verbatim, no logic changes):
  - mcp_tools.py:812-857  → parse_result(...)  [JSON-line parser]
  - mcp_tools.py:967-1019 → build_argv(...)    [argv builder, two branches]

DORMANT in Phase 4: mcp_tools.sub_agent does NOT call this adapter yet.
The production path stays in mcp_tools.sub_agent through Phase 6 (success
criterion #4: "MCP sub_agent tool signature and behaviour are unchanged
in this phase"). Phase 7 flips dispatch through cli_runtime.

The byte-identicality of build_argv vs the v0.9.2.0 production code is
verified by tests/orchestrator/test_subagent_claude_compat.py (golden
snapshot, plan 04-04). The argv layer is what is asserted byte-identical;
the surrounding `cd <wd> && <headers_env> ...` shell-execution wrapper
stays in mcp_tools.sub_agent (RESEARCH.md note at line 215).
"""

import json

from .result import SubAgentResult


class ClaudeAdapter:
    """Adapter for the `claude` CLI (Anthropic Claude Code).

    Does NOT inherit from CliAdapter — structural typing via typing.Protocol
    is sufficient (RESEARCH.md lines 244-260).
    """

    def build_argv(
        self,
        task: str,
        system_prompt: str,
        model: str,
        max_turns: int,
        timeout_s: int,
        *,
        resume_session_id: str = "",
        plan_file: str = "",
    ) -> list[str]:
        """Return the argv list for invoking `claude --print ...`.

        Two branches (lifted from mcp_tools.py:962-1019):
          - RESUME: when resume_session_id is non-empty, build the resume argv.
          - NEW SESSION: otherwise, build the new-session argv with --model
            and --append-system-prompt.

        Common flags appended to BOTH branches (lifted from mcp_tools.py:954-959):
          --max-turns N --permission-mode bypassPermissions
          --disallowedTools AskUserQuestion,ExitPlanMode --output-format json

        Note: timeout_s is part of the Protocol but not consumed here — the
        existing v0.9.2.0 invocation enforces timeout via the asyncio wrapper
        in mcp_tools.sub_agent, NOT via a CLI flag. Accepted for Protocol
        uniformity; codex/opencode adapters will use it.

        Note: plan_file is part of the Protocol but not consumed here — the
        short-prompt construction (`Read and execute your task plan from
        <plan_file>`) lives in mcp_tools.sub_agent today and is passed in as
        `task`. Accepted for Protocol uniformity.
        """
        common = [
            "--max-turns", str(max_turns),
            "--permission-mode", "bypassPermissions",
            "--disallowedTools", "AskUserQuestion,ExitPlanMode",
            "--output-format", "json",
        ]

        if resume_session_id:
            # RESUME branch (lifted from mcp_tools.py:962-973)
            return [
                "claude",
                "-p", task,
                "--resume", resume_session_id,
                *common,
            ]

        # NEW SESSION branch (lifted from mcp_tools.py:974-1019)
        return [
            "claude",
            "-p", task,
            "--model", model,
            "--append-system-prompt", system_prompt,
            *common,
        ]

    def parse_result(
        self,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> SubAgentResult:
        """Parse Claude's `--output-format json` stream.

        Body lifted verbatim from mcp_tools.py:_format_sub_agent_result
        (lines 819-845). Tail (lines 847-855) is REMOVED here — string
        formatting belongs to a future render layer (Phase 7 concern), not
        the parser. Returns SubAgentResult instead.

        cost_usd → None when total_cost_usd is 0.0 OR missing (per Pitfall 4:
        render "cost: unavailable" rather than "$0.00" upstream).
        turns → None when num_turns is 0 OR missing (same rationale).
        session_id → None when empty string OR missing.

        is_error → True when the JSON `result` line says is_error=True OR when
        returncode != 0. The returncode gate aligns ClaudeAdapter with
        CodexAdapter/OpenCodeAdapter (Phase 5 BLOCKER 1) — without it, killed
        or timed-out claude runs (rc=137/143/124 with empty stdout) would
        silently render as success because there is no JSON `result` line to
        flip is_error.

        returncode → captured into SubAgentResult.returncode (added in plan
        05-02 Task 0) so the caller can render distinct user-facing messages
        for rc=124 (timeout), rc=137 (SIGKILL), rc=143 (SIGTERM).
        """
        response_text = ""
        cost = 0.0
        turns = 0
        is_error = False
        session_id = ""

        try:
            for line in stdout.strip().split("\n"):
                line = line.strip()
                if '"type"' in line and '"result"' in line:
                    try:
                        parsed = json.loads(line)
                        if parsed.get("type") == "result":
                            response_text = parsed.get("result", "")
                            cost = parsed.get("total_cost_usd", 0.0)
                            turns = parsed.get("num_turns", 0)
                            is_error = parsed.get("is_error", False)
                            session_id = parsed.get("session_id", "")
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            # Preserve operator-visible diagnostic from the original
            # _format_sub_agent_result (line 842).
            print(f"[SUB-AGENT] Failed to parse JSON output: {e}")

        if not response_text:
            response_text = stdout

        # BLOCKER 1: align with CodexAdapter/OpenCodeAdapter — non-zero rc is
        # ALWAYS an error, even when the JSON `result` line is missing
        # (killed/SIGKILL/SIGTERM/timeout cases). Without this gate,
        # rc=137 + empty stdout would silently produce is_error=False and
        # mcp_tools' Sub-Agent-Terminated branch would never fire.
        is_error = is_error or (returncode != 0)

        return SubAgentResult(
            text=response_text,
            cost_usd=cost if cost else None,
            turns=turns if turns else None,
            is_error=is_error,
            session_id=session_id or None,
            raw_events=[],
            returncode=returncode,
        )
