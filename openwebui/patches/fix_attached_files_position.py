#!/usr/bin/env python3
"""
Patch for Open WebUI v0.8.11–0.8.12: append <attached_files> instead of prepend.

Problem:
  add_file_context() prepends <attached_files> to the beginning of user message.
  This breaks prompt cache: each new file changes the start of the message,
  invalidating the entire cached prefix.

Solution:
  Append <attached_files> to the end of the message -- system prompt cache
  and previous messages are preserved.

Note (v0.8.11–0.8.12):
  Zip misalignment (user_messages filter) and format_file_tag() are already
  fixed upstream (PR #21878). This patch affects ONLY the insertion position.
"""

import os

MIDDLEWARE_PATH = os.environ.get(
    "_PATCH_TARGET_OVERRIDE",
    "/app/backend/open_webui/utils/middleware.py",
)

PATCH_MARKER = "attached_files_append"

# Exact v0.8.11–0.8.12 code — prepend file_context before content
SEARCH_PATTERN = """\
        content = message.get('content', '')
        if isinstance(content, list):
            message['content'] = [{'type': 'text', 'text': file_context}] + content
        else:
            message['content'] = file_context + content"""

# Replace with append — file_context goes AFTER content (prompt cache friendly)
REPLACE_PATTERN = """\
        # PATCH: attached_files_append — append to end, not prepend (prompt cache friendly)
        content = message.get('content', '')
        if isinstance(content, list):
            message['content'] = content + [{'type': 'text', 'text': file_context}]
        else:
            message['content'] = (content + '\\n' + file_context) if content else file_context"""


def apply_patch():
    if not os.path.exists(MIDDLEWARE_PATH):
        print(f"ERROR: File not found: {MIDDLEWARE_PATH}")
        return False

    with open(MIDDLEWARE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if PATCH_MARKER in content:
        print("  Patch already applied, skipping...")
        return True

    if SEARCH_PATTERN not in content:
        print("ERROR: Could not find target code block in middleware.py")
        print("  Looking for: add_file_context prepend pattern (v0.8.11–0.8.12)")
        return False

    content = content.replace(SEARCH_PATTERN, REPLACE_PATTERN, 1)

    with open(MIDDLEWARE_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("  Patch applied successfully!")
    print("  <attached_files> appended to end of message (prompt cache friendly)")
    return True


if __name__ == "__main__":
    print("Applying attached-files-position patch to Open WebUI...")
    success = apply_patch()
    exit(0 if success else 1)
