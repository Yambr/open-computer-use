# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""
Static contract test for the OpenWebUI system prompt (parity ledger D1/D2/D3/D7).

No stand, no network. Loads the prompt text through the SAME mechanism init.sh
uses to seed params.system, then asserts the model-facing contract:

  - the <available_skills> block is present and enumerates the baked skills;
  - the three writable/readable mount roles are named;
  - the D3 self-verify instruction is present;
  - the file-sharing block is present;
  - none of the flat-mount-era / PoC-only artifacts survive
    (the "drop out of your listing" line, sub_agent, the {file_base_url}
    HTTP-URL placeholder).

init.sh reads the prompt from openwebui/system_prompt.txt (shipped into the
image next to init.sh) and seeds it verbatim as params.system. This test reads
the same file: if init.sh's read path changes, update _load_prompt() to match.
"""

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROMPT_FILE = _REPO_ROOT / "openwebui" / "system_prompt.txt"
_INIT_SH = _REPO_ROOT / "openwebui" / "init.sh"


def _load_prompt() -> str:
    """Load the prompt exactly as init.sh delivers it to params.system."""
    assert _PROMPT_FILE.is_file(), (
        f"prompt data file missing: {_PROMPT_FILE} - init.sh reads this file "
        f"and fails loud if it is absent"
    )
    return _PROMPT_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def prompt() -> str:
    return _load_prompt()


def test_prompt_is_ascii(prompt: str):
    # Committed data artifact: English-only, pure ASCII.
    non_ascii = [c for c in prompt if ord(c) > 127]
    assert not non_ascii, f"prompt contains non-ASCII bytes: {non_ascii[:10]!r}"


def test_available_skills_block_present(prompt: str):
    assert "<available_skills>" in prompt
    assert "</available_skills>" in prompt


def test_at_least_ten_skill_locations(prompt: str):
    locations = re.findall(r"/mnt/skills/public/[A-Za-z0-9_-]+/SKILL\.md", prompt)
    distinct = set(locations)
    assert len(distinct) >= 10, (
        f"expected >= 10 distinct /mnt/skills/public/<skill>/SKILL.md locations, "
        f"found {len(distinct)}: {sorted(distinct)}"
    )


def test_filesystem_map_roles_named(prompt: str):
    assert "/mnt/user-data/uploads" in prompt
    assert "/mnt/user-data/outputs" in prompt
    assert "/home/assistant" in prompt


def test_skills_first_protocol_present(prompt: str):
    # The "read SKILL.md before writing code" teaching must survive.
    assert "SKILL.md" in prompt
    assert "before" in prompt.lower()


def test_self_verify_instruction_present(prompt: str):
    # D3: after saving, list outputs and confirm the file is there, then name it.
    lowered = prompt.lower()
    assert "list /mnt/user-data/outputs" in lowered
    assert "confirm" in lowered
    # The exact self-verify phrasing this prompt ships.
    assert "confirm the file is present" in lowered


def test_sharing_block_present(prompt: str):
    assert "<sharing_files>" in prompt
    assert "</sharing_files>" in prompt


def test_no_flat_mount_dropout_line(prompt: str):
    # The false "a file you saved may drop out of your own listing" line is gone.
    assert "drop out of your" not in prompt.lower()


def test_no_sub_agent(prompt: str):
    lowered = prompt.lower()
    assert "sub_agent" not in lowered
    assert "sub-agent" not in lowered


def test_no_http_file_url_placeholder(prompt: str):
    # The fleet has no {file_base_url}/{archive_url}/{chat_id} HTTP file URLs.
    assert "{file_base_url}" not in prompt
    assert "{archive_url}" not in prompt


def test_init_sh_reads_the_prompt_file(prompt: str):
    # Guard the delivery contract: init.sh must actually read system_prompt.txt.
    init_text = _INIT_SH.read_text(encoding="utf-8")
    assert "system_prompt.txt" in init_text, (
        "init.sh no longer references system_prompt.txt - the delivery path this "
        "test asserts is stale"
    )
