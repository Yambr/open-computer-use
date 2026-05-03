# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""OpenCode CLI adapter (ADAPT-04) — Phase 5 implementation.

Invokes `opencode run "<prompt>" --model <provider/model> --format json
--dangerously-skip-permissions`. Justification for
--dangerously-skip-permissions: we run inside an isolated Docker sandbox
container; the CLI's own permission layer is redundant inside that
boundary (same rationale as codex --full-auto in cli_adapters/codex.py).

System-prompt injection is via concatenation into the prompt argument
("<system_prompt>\\n\\n---\\n\\n<task>") — opencode's per-mode system
prompt lives in the rendered config (Phase 6 concern), not on the CLI
(Pitfall 2 in PITFALLS.md).

Model MUST be in `provider/model` form (e.g. anthropic/claude-sonnet-4-6,
openrouter/qwen/qwen-3-coder). cli_runtime.resolve_subagent_model
expands single-word aliases ("sonnet" -> "anthropic/claude-sonnet-4-6")
before reaching this adapter; bare ids without a "/" prefix get a
runtime warning from the resolver.

cost_usd may be a float (when opencode's provider reports per-step cost)
or None (when not). Pitfall 4: caller renders None as "unavailable",
not "$0.00".

parse_result populates SubAgentResult.returncode with the passed-in
returncode so plan 05-05's mcp_tools error-rendering branch can switch
on it (rc=124 timeout, rc=137 SIGKILL, rc=143 SIGTERM, default non-zero
"failed with exit code N").
"""

import json

from .result import SubAgentResult


class OpenCodeAdapter:
    """Adapter for the `opencode` CLI (sst/opencode-ai 1.14.25)."""

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
        """Return argv for `opencode run <prompt> --model ... --format json ...`.

        Notes:
          - max_turns is NOT honored by opencode CLI (Claude-only flag);
            SUB_AGENT_TIMEOUT is the backstop (Pitfall 5).
          - resume_session_id is IGNORED with informational stderr warning;
            opencode `run --continue` requires a per-mode session config
            that we do not ship until Phase 6.
          - plan_file is part of the Protocol but not consumed here.
        """
        # Pitfall 2: opencode has no CLI flag for system prompt; concatenate
        # as task preamble (mirrors CodexAdapter shape).
        combined_prompt = (
            f"{system_prompt}\n\n---\n\n{task}" if system_prompt else task
        )

        if resume_session_id:
            import sys
            print(
                f"[opencode-adapter] WARNING: resume_session_id={resume_session_id!r} "
                f"ignored — opencode run is stateless (Phase 6 will add --continue).",
                file=sys.stderr,
            )

        return [
            "opencode", "run",
            combined_prompt,
            "--model", model,
            "--format", "json",
            "--dangerously-skip-permissions",
        ]

    def parse_result(
        self,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> SubAgentResult:
        """Parse opencode's --format json event stream.

        Schema (opencode.ai/docs/events) varies per provider; the parser is
        defensive — preserves raw_events for debugging even when the
        structured fields are missing.

        Recognised final-message event types:
          - assistant-message-completed
          - step-finish
          - message-completed

        Cost: summed from step-finish events when event.cost or
        event.usage.total_cost is present (numeric). Stays None if no
        cost-bearing events arrive (e.g. provider doesn't report cost).

        returncode is captured into SubAgentResult.returncode so the
        caller (plan 05-05) can render distinct messages for rc=124/137/143.
        """
        events: list[dict] = []
        last_message_text = ""
        cost_usd: float | None = None
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

            # Application-level error events (opencode exits rc=0 but emits these).
            # Must be checked first so the error branch wins over any text extraction
            # that might otherwise overwrite last_message_text with empty/garbage.
            if et == "error":
                is_error = True
                err_data = event.get("data", {}) or {}
                if isinstance(err_data, dict):
                    err_msg = err_data.get("message") or str(err_data)
                else:
                    err_msg = str(err_data)
                last_message_text = f"opencode error: {err_msg}"
                continue

            # Capture the final assistant text (last seen wins).
            if et in ("assistant-message-completed", "step-finish", "message-completed"):
                text_field = (
                    event.get("text")
                    or event.get("content")
                    or event.get("message", {}).get("content")
                )
                if isinstance(text_field, str):
                    last_message_text = text_field
                elif isinstance(text_field, list):
                    for block in text_field:
                        if isinstance(block, dict) and block.get("type") == "text":
                            last_message_text = block.get("text", last_message_text)

            # Cost aggregation: per-step cost on step-finish.
            if et == "step-finish":
                step_cost = event.get("cost")
                if step_cost is None:
                    usage = event.get("usage", {}) or {}
                    step_cost = usage.get("total_cost")
                if isinstance(step_cost, (int, float)):
                    cost_usd = (cost_usd or 0.0) + float(step_cost)

        # If opencode exits early with no parseable message AND no stdout, fall
        # back to stderr (mirrors codex adapter; same CodeRabbit PR#75 review).
        return SubAgentResult(
            text=last_message_text or stdout or stderr,
            cost_usd=cost_usd,
            turns=None,
            is_error=is_error,
            session_id=None,
            raw_events=events,
            returncode=returncode,
        )
