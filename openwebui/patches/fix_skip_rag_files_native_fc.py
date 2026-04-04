#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Patch for Open WebUI: disable forced RAG for chat files
when the ai_computer_use tool is enabled.

Problem: Chat files always trigger the RAG pipeline
(chat_completion_files_handler) on every message, even when unnecessary.

Solution: When ai_computer_use is enabled, skip RAG for regular files.
Full-context files (context == "full") are processed normally.
Knowledge bases are not affected.
"""

import os

MIDDLEWARE_PATH = "/app/backend/open_webui/utils/middleware.py"

PATCH_MARKER = "skip_rag_files_ai_computer_use"

# Search pattern (original v0.8.11–0.8.12 code)
SEARCH_PATTERN = """    if file_context_enabled:
        try:
            form_data, flags = await chat_completion_files_handler(request, form_data, extra_params, user)
            sources.extend(flags.get('sources', []))
        except Exception as e:
            log.exception(e)"""

# Replacement
REPLACE_PATTERN = """    if file_context_enabled:
        # PATCH: skip_rag_files_ai_computer_use
        # When ai_computer_use is enabled, skip RAG for regular files.
        # Full-context files (context == "full") are processed normally.
        # NB: tools_dict keys are function names from tool specs,
        # not tool IDs. bash_tool is a function from ai_computer_use tool.
        if 'bash_tool' in tools_dict:
            _all_files = form_data.get('metadata', {}).get('files', None)
            if _all_files:
                _full_ctx = [f for f in _all_files if f.get('context') == 'full']
                if _full_ctx:
                    _orig = form_data['metadata']['files']
                    form_data['metadata']['files'] = _full_ctx
                    try:
                        form_data, flags = await chat_completion_files_handler(request, form_data, extra_params, user)
                        sources.extend(flags.get('sources', []))
                    except Exception as e:
                        log.exception(e)
                    finally:
                        form_data['metadata']['files'] = _orig
        else:
            try:
                form_data, flags = await chat_completion_files_handler(request, form_data, extra_params, user)
                sources.extend(flags.get('sources', []))
            except Exception as e:
                log.exception(e)"""


def apply_patch():
    if not os.path.exists(MIDDLEWARE_PATH):
        print(f"ERROR: File not found: {MIDDLEWARE_PATH}")
        return False

    with open(MIDDLEWARE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if PATCH_MARKER in content:
        print("  Patch already applied, skipping...")
        return True

    # Remove old patch (skip_rag_files_native_fc) if it was applied
    OLD_MARKER = "skip_rag_files_native_fc"
    if OLD_MARKER in content:
        # Old patch used a different condition -- needs rollback
        # Find the old REPLACE and revert to original, then apply the new one
        print("  WARNING: Old patch (native_fc) detected, will be replaced")
        # Applying on top since Docker build starts from a clean image

    if SEARCH_PATTERN not in content:
        print("ERROR: Could not find target code block in middleware.py")
        print("  Looking for: if file_context_enabled: ... chat_completion_files_handler ...")
        return False

    content = content.replace(SEARCH_PATTERN, REPLACE_PATTERN, 1)

    with open(MIDDLEWARE_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("  Patch applied successfully!")
    print("  When ai_computer_use is enabled: full-context files still work, RAG for others is skipped")
    return True


if __name__ == "__main__":
    print("Applying skip-RAG-for-files (ai_computer_use) patch to Open WebUI...")
    success = apply_patch()
    exit(0 if success else 1)
