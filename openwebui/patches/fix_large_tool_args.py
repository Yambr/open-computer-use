#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Patch for Open WebUI: truncate large tool call arguments in HTML attributes
+ base64 storage of full arguments for reconstruction.

Problem: serialize_output() stores tool call arguments in an
HTML attribute <details arguments="html.escape(json.dumps(arguments))">.
When arguments are large (str_replace with multi-KB HTML), triple encoding
(json.dumps -> html.escape) inflates the attribute to 30-65+ KB.
The frontend markdown parser (marked) breaks on large attributes, UI freezes
on "Executing [tool]..." forever.

Solution:
1. arguments="..." -- truncated via _truncate_for_attr() > 2KB (for display)
2. arguments-raw="..." -- base64-encoded full JSON (for reconstruct_tool_messages)

Base64 is safe for HTML attributes: charset [A-Za-z0-9+/=], no special characters.
Regex [^"]* in the attribute parser runs O(n) without backtracking.

Frontend regex /(\\w+)="([^"]*)"/g skips arguments-raw (hyphen does not match \\w),
so base64 data is invisible to the frontend.

See https://github.com/open-webui/open-webui/issues/18743
"""

import os
import sys

_PATCH_TARGET_OVERRIDE = os.environ.get("_PATCH_TARGET_OVERRIDE", "")
MIDDLEWARE_PATH = _PATCH_TARGET_OVERRIDE or "/app/backend/open_webui/utils/middleware.py"

PATCH_MARKER = "_truncate_for_attr"
NEW_PATCH_MARKER = "FIX_LARGE_TOOL_ARGS"

FUNCTION_CODE = '''
# === PATCH: _truncate_for_attr + _b64_encode_args — fix UI freeze + preserve args for model ===
# FIX_LARGE_TOOL_ARGS
import base64 as _b64_module

_MAX_TOOL_ATTR_LEN = 2_000  # ~2KB before html.escape — tool panel is small, no point showing more


def _truncate_for_attr(data, max_len=_MAX_TOOL_ATTR_LEN, **kwargs):
    """Truncate tool arguments for HTML attribute display.

    Drop-in replacement for json.dumps() with size check.
    Returns json.dumps() output for normal data, truncated summary for oversized.
    If data has a 'description' field, shows it in the summary.
    Only used for the display `arguments` attribute, NOT for `arguments-raw`.
    """
    serialized = json.dumps(data, **kwargs)
    if len(serialized) <= max_len:
        return serialized
    # Try to extract description for a meaningful summary
    desc = None
    try:
        obj = data if isinstance(data, dict) else (json.loads(data) if isinstance(data, str) else None)
        if isinstance(obj, dict):
            desc = obj.get("description") or obj.get("desc")
    except Exception:
        pass
    size_kb = f"{len(serialized) / 1024:.1f}"
    if desc:
        result = {"description": str(desc), "_hidden": f"Arguments truncated ({size_kb} KB). Full text available to the model."}
    else:
        result = f"[Arguments hidden ({size_kb} KB). Full text available to the model.]"
    return json.dumps(result, ensure_ascii=False)


def _b64_encode_args(data):
    """Base64-encode tool arguments for safe storage in HTML attribute.

    Used for `arguments-raw` attribute. Base64 charset [A-Za-z0-9+/=] has no
    HTML special characters, so no html.escape() needed and no regex backtracking.

    Note: arguments may be a JSON string (OpenAI spec) or a dict.
    If already a string, use as-is; otherwise json.dumps() it.
    """
    try:
        raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        result = _b64_module.b64encode(raw.encode()).decode()
        return result
    except Exception as e:
        log.debug("_b64_encode_args failed: %s", e)
        return ""
# === END PATCH ===
'''

# Search pattern: the original html.escape(json.dumps(arguments)) inside f-string attribute
OLD_ARGS = 'arguments="{html.escape(json.dumps(arguments))}"'

# Replace with: truncated display attribute + base64 raw attribute
NEW_ARGS = 'arguments="{html.escape(_truncate_for_attr(arguments))}" arguments-raw="{_b64_encode_args(arguments)}"'


def apply_patch():
    """Apply patch to middleware.py"""

    if not os.path.exists(MIDDLEWARE_PATH):
        print(
            f"ERROR: fix_large_tool_args target file {MIDDLEWARE_PATH} not found. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(MIDDLEWARE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if PATCH_MARKER in content or NEW_PATCH_MARKER in content:
        print(f"ALREADY PATCHED: {MIDDLEWARE_PATH} contains {PATCH_MARKER}")
        return True

    # 1. Insert functions after imports
    import_marker = "from open_webui.models.chats import Chats"
    marker_idx = content.find(import_marker)
    if marker_idx < 0:
        print(
            f"ERROR: fix_large_tool_args import anchor 'from open_webui.models.chats "
            f"import Chats' not found in {MIDDLEWARE_PATH} — upstream may have "
            "restructured imports. Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)

    eol_idx = content.index("\n", marker_idx) + 1
    content = content[:eol_idx] + FUNCTION_CODE + content[eol_idx:]
    print("  Inserted _truncate_for_attr() + _b64_encode_args() functions after imports")

    # 2. Replace arguments attribute pattern — expected EXACTLY 2 occurrences in serialize_output
    occurrences = content.count(OLD_ARGS)
    if occurrences != 2:
        print(
            f"ERROR: fix_large_tool_args expected 2 occurrences of OLD_ARGS f-string in "
            f"serialize_output, found {occurrences}. v0.9.1 upstream may have restructured. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)

    content = content.replace(OLD_ARGS, NEW_ARGS)
    print(f"  Replaced {occurrences} occurrence(s): arguments + arguments-raw")

    with open(MIDDLEWARE_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("PATCHED: fix_large_tool_args applied successfully.")
    return True


if __name__ == "__main__":
    print("Applying large tool arguments patch to Open WebUI...")
    success = apply_patch()
    sys.exit(0 if success else 1)
