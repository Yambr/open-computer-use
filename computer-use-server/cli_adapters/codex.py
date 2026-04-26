# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Codex CLI adapter (ADAPT-03) — Phase 5 implementation.

Invokes `codex exec --ephemeral --json --output-last-message <tmpfile> ...`
with --full-auto (NOT --dangerously-bypass-approvals-and-sandbox per
PITFALLS.md anti-pattern table). Justification for --full-auto: we run
inside an isolated Docker container that already provides the sandbox
boundary that codex's own approval layer would otherwise enforce.

System-prompt injection is via concatenation into the prompt argument
("<system_prompt>\\n\\n---\\n\\n<task>") — codex 0.125.0 has no
--append-system-prompt / --system flag (Pitfall 2 in PITFALLS.md).

The /tmp/codex-agents-<uuid> workdir is created by cli_runtime.dispatch
BEFORE invocation (codex requires --cd to point at an existing dir).
Adapter stays a pure function — no side effects.

cost_usd is always None — codex JSONL stream does not surface a USD cost
(Pitfall 4: render "unavailable" upstream, not "$0.00").

parse_result populates SubAgentResult.returncode with the passed-in
returncode so plan 05-05's mcp_tools error-rendering branch can switch
on it (rc=124 timeout, rc=137 SIGKILL, rc=143 SIGTERM, default non-zero
"failed with exit code N").
"""

import json
import uuid

from .result import SubAgentResult


class CodexAdapter:
    """Adapter for the `codex` CLI (@openai/codex 0.125.0).

    Does NOT inherit from CliAdapter — structural typing via typing.Protocol
    is sufficient (matches ClaudeAdapter pattern).
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
        """Return argv for `codex exec --ephemeral --json ...`.

        Notes:
          - max_turns is NOT honored by codex CLI (Claude-only flag); the
            SUB_AGENT_TIMEOUT backstop is the caller's responsibility
            (Pitfall 5 — codex turn-counting is a Phase 7 followup).
          - resume_session_id is IGNORED with informational stderr warning
            (codex --ephemeral is stateless by design; documented in
            Phase 8 docs).
          - plan_file is part of the Protocol but not consumed here — the
            short-prompt construction (`Read and execute your task plan ...`)
            is built by mcp_tools.sub_agent and passed in as `task`, same
            as ClaudeAdapter.
        """
        workdir = f"/tmp/codex-agents-{uuid.uuid4().hex[:12]}"
        last_msg_file = f"{workdir}/last_message.txt"

        # Pitfall 2: codex has no --append-system-prompt; concatenate as
        # task preamble. Empty system_prompt => task only.
        combined_prompt = (
            f"{system_prompt}\n\n---\n\n{task}" if system_prompt else task
        )

        if resume_session_id:
            # Inform the operator (stderr) that codex --ephemeral cannot
            # honor session resume. We do NOT raise — caller may have
            # supplied resume_session_id from a previous claude run; we
            # gracefully start a fresh ephemeral session.
            import sys
            print(
                f"[codex-adapter] WARNING: resume_session_id={resume_session_id!r} "
                f"ignored — codex --ephemeral is stateless.",
                file=sys.stderr,
            )

        return [
            "codex", "exec",
            "--ephemeral",
            "--json",
            "--output-last-message", last_msg_file,
            "--model", model,
            "--full-auto",
            "--cd", workdir,
            "--skip-git-repo-check",
            combined_prompt,
        ]

    def parse_result(
        self,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> SubAgentResult:
        """Parse codex's `--json` JSONL event stream.

        Schema (developers.openai.com/codex/noninteractive):
          - turn.started / turn.completed (with usage.input_tokens / output_tokens)
          - item.completed where item.type == "message" carries the
            assistant text in item.content[].text

        cost_usd is always None (Pitfall 4): codex doesn't surface USD
        cost in the stream; computing it would require a per-model price
        table (deferred to v0.9.x).

        turns is None (codex's turn.completed is per-turn, not cumulative
        count; we do not maintain a counter here).

        session_id is None (--ephemeral runs have no session id).

        returncode is captured into SubAgentResult.returncode so the
        caller (plan 05-05) can render distinct user-facing messages for
        rc=124/137/143/non-zero.
        """
        events: list[dict] = []
        last_message_text = ""
        tokens_in = 0
        tokens_out = 0
        is_error = (returncode != 0)

        for line in stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(event)
            et = event.get("type", "")
            if et == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "message":
                    for block in item.get("content", []) or []:
                        if isinstance(block, dict) and block.get("type") == "text":
                            last_message_text = block.get("text", last_message_text)
            if et == "turn.completed":
                usage = event.get("usage", {}) or {}
                tokens_in += usage.get("input_tokens", 0) or 0
                tokens_out += usage.get("output_tokens", 0) or 0

        # If codex exits early with no parseable message AND no stdout, fall back
        # to stderr so the caller surfaces the real CLI error instead of a generic
        # "failed with exit code N" banner. Per CodeRabbit PR#75 review.
        return SubAgentResult(
            text=last_message_text or stdout or stderr,
            cost_usd=None,
            turns=None,
            is_error=is_error,
            session_id=None,
            raw_events=events,
            returncode=returncode,
        )
