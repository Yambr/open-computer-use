# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Per-CLI adapter package — uniform interface over claude/codex/opencode.

Each adapter exposes:
  build_argv(task, system_prompt, model, max_turns, timeout_s, *, resume_session_id="", plan_file="") -> list[str]
  parse_result(stdout, stderr, returncode) -> SubAgentResult

The CliAdapter Protocol below is structurally typed (typing.Protocol) — adapter
classes do NOT need to inherit from it. The type checker enforces conformance.

Phase 4 ships:
  - claude.py: byte-identical lift-and-shift of mcp_tools.py:812-857 + 967-1019
    (DORMANT — production path stays in mcp_tools.sub_agent through Phase 6)
  - codex.py / opencode.py: stubs raising NotImplementedError (Phase 5 implements)
"""

from typing import Protocol

from .result import SubAgentResult


class CliAdapter(Protocol):
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
        ...

    def parse_result(
        self,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> SubAgentResult:
        ...


__all__ = ["CliAdapter", "SubAgentResult"]
