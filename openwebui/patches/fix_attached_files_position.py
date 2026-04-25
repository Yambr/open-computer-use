#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Patch for Open WebUI 0.9.2: append <attached_files> instead of prepend.

Problem:
  add_file_context() prepends <attached_files> to the beginning of user message.
  This breaks prompt cache: each new file changes the start of the message,
  invalidating the entire cached prefix.

Solution:
  Append <attached_files> to the end of the message -- system prompt cache
  and previous messages are preserved.

Note:
  Zip misalignment (user_messages filter) and format_file_tag() are already
  fixed upstream (PR #21878). This patch affects ONLY the insertion position.
"""

import os
import sys

_PATCH_TARGET_OVERRIDE = os.environ.get("_PATCH_TARGET_OVERRIDE", "")
MIDDLEWARE_PATH = _PATCH_TARGET_OVERRIDE or "/app/backend/open_webui/utils/middleware.py"

PATCH_MARKER = "attached_files_append"
NEW_PATCH_MARKER = "FIX_ATTACHED_FILES_POSITION"

# Exact v0.8.11-0.9.1 code — prepend file_context before content
SEARCH_PATTERN = """\
        content = message.get('content', '')
        if isinstance(content, list):
            message['content'] = [{'type': 'text', 'text': file_context}] + content
        else:
            message['content'] = file_context + content"""

# Replace with append — file_context goes AFTER content (prompt cache friendly)
REPLACE_PATTERN = """\
        # PATCH: attached_files_append — append to end, not prepend (prompt cache friendly); FIX_ATTACHED_FILES_POSITION
        content = message.get('content', '')
        if isinstance(content, list):
            message['content'] = content + [{'type': 'text', 'text': file_context}]
        else:
            message['content'] = (content + '\\n' + file_context) if content else file_context"""


def apply_patch():
    if not os.path.exists(MIDDLEWARE_PATH):
        print(
            f"ERROR: fix_attached_files_position target file {MIDDLEWARE_PATH} not found. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(MIDDLEWARE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if PATCH_MARKER in content or NEW_PATCH_MARKER in content:
        print(f"ALREADY PATCHED: {MIDDLEWARE_PATH} contains {PATCH_MARKER}")
        return True

    if SEARCH_PATTERN not in content:
        print(
            f"ERROR: fix_attached_files_position anchor (add_file_context prepend block) "
            f"not found in {MIDDLEWARE_PATH} — upstream may have refactored add_file_context. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)

    content = content.replace(SEARCH_PATTERN, REPLACE_PATTERN, 1)

    with open(MIDDLEWARE_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("PATCHED: fix_attached_files_position applied successfully.")
    print("  <attached_files> appended to end of message (prompt cache friendly)")
    return True


if __name__ == "__main__":
    print("Applying attached-files-position patch to Open WebUI...")
    success = apply_patch()
    sys.exit(0 if success else 1)
