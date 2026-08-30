# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""Tool-surface contract guard (parity ledger D7).

Asserts the OpenWebUI Tools class advertises EXACTLY the four tools the fleet
gateway forwards - bash_tool, str_replace, create_file, view - and no more. The
gateway advertises only these four; a fifth public async tool method (the
removed sub_agent) would be advertised to the model but fail on call.

Static AST parse (not import) so the test pulls none of the module's runtime
deps. The module path is resolved relative to this test's repo location.
"""

import ast
from pathlib import Path

_MODULE = (
    Path(__file__).resolve().parents[2]
    / "openwebui"
    / "tools"
    / "computer_use_tools.py"
)

EXPECTED = {"bash_tool", "str_replace", "create_file", "view"}


def _public_async_tool_methods() -> set:
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Tools":
            return {
                n.name
                for n in node.body
                if isinstance(n, ast.AsyncFunctionDef) and not n.name.startswith("_")
            }
    raise AssertionError("class Tools not found in computer_use_tools.py")


def test_tool_surface_is_exactly_four():
    surface = _public_async_tool_methods()
    assert surface == EXPECTED, (
        f"Tools public async surface {sorted(surface)} != {sorted(EXPECTED)} "
        f"(extra: {sorted(surface - EXPECTED)}, missing: {sorted(EXPECTED - surface)})"
    )


def test_no_sub_agent_anywhere_in_module():
    text = _MODULE.read_text(encoding="utf-8")
    assert "sub_agent" not in text, "sub_agent must be gone from the module"
    assert "SUB_AGENT_CLIENT_TIMEOUT" not in text, "unused constant must be gone"
