#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""Render CONTRAST.md from scenarios.yaml.

scenarios.yaml is the single source of truth; CONTRAST.md is generated. Run:

    python3 deploy/tests/journeys/render_contrast.py

Output is deterministic (scenarios sorted by id, groups A..G in order) so a
re-run with no scenario change yields a byte-identical file.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_SCENARIOS = _HERE / "scenarios.yaml"
_OUT = _HERE / "CONTRAST.md"

_GROUP_TITLES = {
    "A": "Group A — Auth & Bootstrap",
    "B": "Group B — Journey 1: create a docx and download it",
    "C": "Group C — Journey 2: upload, edit-in-guest, download from outputs",
    "D": "Group D — Authz boundary (every-hop enforcement, adversarial)",
    "E": "Group E — Auto-disconnect, lifecycle, kill-switch",
    "F": "Group F — Agentic-load simulation",
    "G": "Group G — Negative / adversarial / isolation invariants",
}

_HEADER = """<!-- SPDX-License-Identifier: FSL-1.1-Apache-2.0 -->
<!-- Copyright (c) 2025 Open Computer Use Contributors -->
<!-- GENERATED from scenarios.yaml by render_contrast.py. Do not hand-edit. -->

# PoC vs fleet — journey contrast

One row per scenario. `Proves` is the single invariant the scenario asserts;
`PoC` and `Fleet` are the per-system outcomes; `Bucket` classifies the gap
(IDENTICAL / HARDENED / PoC-HOLE). The negative / inversion keystone that keeps
each assertion non-vacuous lives in scenarios.yaml.
"""


def _sort_key(entry: dict) -> tuple[str, int]:
    """Sort by group letter, then numeric index within the group (A2 < A10)."""
    sid = entry["id"]
    group = sid[0]
    idx = int(sid[1:]) if sid[1:].isdigit() else 0
    return (group, idx)


def _esc(text: str) -> str:
    """Escape pipes so a cell never breaks the Markdown table."""
    return str(text).replace("|", "\\|").strip()


def _load() -> list[dict]:
    with _SCENARIOS.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return list(doc.get("scenarios", []))


def render(scenarios: list[dict]) -> str:
    ordered = sorted(scenarios, key=_sort_key)
    lines: list[str] = [_HEADER]

    for group in sorted(_GROUP_TITLES):
        group_rows = [s for s in ordered if s["group"] == group]
        if not group_rows:
            continue
        lines.append(f"## {_GROUP_TITLES[group]}\n")
        lines.append("| ID | Story | Proves | PoC | Fleet | Bucket |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for s in group_rows:
            lines.append(
                "| {id} | {story} | {proves} | {poc} | {fleet} | {bucket} |".format(
                    id=_esc(s["id"]),
                    story=_esc(s["story"]),
                    proves=_esc(s["proves"]),
                    poc=_esc(s["poc_expect"]),
                    fleet=_esc(s["fleet_expect"]),
                    bucket=_esc(s["bucket"]),
                )
            )
        lines.append("")

    counts = {"IDENTICAL": 0, "HARDENED": 0, "PoC-HOLE": 0}
    for s in ordered:
        bucket = s["bucket"]
        if bucket not in counts:
            raise ValueError(f"scenario {s['id']} has unknown bucket {bucket!r}")
        counts[bucket] += 1

    lines.append("## Bucket totals\n")
    lines.append(f"- IDENTICAL: {counts['IDENTICAL']}")
    lines.append(f"- HARDENED: {counts['HARDENED']}")
    lines.append(f"- PoC-HOLE: {counts['PoC-HOLE']}")
    lines.append(f"- total scenarios: {len(ordered)}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    scenarios = _load()
    output = render(scenarios)
    _OUT.write_text(output, encoding="utf-8")
    counts = {"IDENTICAL": 0, "HARDENED": 0, "PoC-HOLE": 0}
    for s in scenarios:
        counts[s["bucket"]] += 1
    print(f"wrote {_OUT} ({len(scenarios)} scenarios)")
    print(
        f"IDENTICAL={counts['IDENTICAL']} "
        f"HARDENED={counts['HARDENED']} "
        f"PoC-HOLE={counts['PoC-HOLE']}"
    )


if __name__ == "__main__":
    main()
