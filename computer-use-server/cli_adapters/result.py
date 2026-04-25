# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Normalised sub-agent result type returned by every CLI adapter.

cost_usd is Optional because non-Claude CLIs (codex, opencode) do not
surface a USD cost in their JSON output (Pitfall 4 in PITFALLS.md).
None is rendered as "cost: unavailable" in the result string by the
caller; never as "$0.00" (which would be operator-misleading).

turns and session_id are Optional for the same reason — codex/opencode
do not emit equivalent fields. The Claude adapter populates them when
present in the parsed JSON.

raw_events is reserved for future cost computation (model→price tables)
and debugging; Phase 4 leaves it empty for the Claude adapter.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SubAgentResult:
    text: str
    cost_usd: float | None
    turns: int | None
    is_error: bool
    session_id: str | None
    raw_events: list[dict] = field(default_factory=list)
