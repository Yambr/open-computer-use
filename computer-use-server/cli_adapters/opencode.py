# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""OpenCode CLI adapter — STUB. Phase 5 implements ADAPT-04."""

from .result import SubAgentResult


class OpenCodeAdapter:
    """Stub adapter for the `opencode` CLI (sst/opencode-ai).

    Phase 4 ships an empty __init__ so cli_runtime._ADAPTERS can instantiate
    this at module load without crashing (Pitfall C in 04-RESEARCH.md).
    Phase 5 implements build_argv and parse_result per ADAPT-04 (opencode run
    "<prompt>" --model <provider/model> --format json ...).
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
        raise NotImplementedError("ADAPT-04 — Phase 5")

    def parse_result(
        self,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> SubAgentResult:
        raise NotImplementedError("ADAPT-04 — Phase 5")
