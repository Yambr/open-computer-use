#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Patch for Open WebUI: truncate large tool results in output (DB + LLM).

Problem: MCP tools (Metabase, OpenSearch, Playwright, etc.) return
results 15K-100K+ chars. After 2-3 calls the model context is exhausted.
Full results are also saved to DB, bloating chat storage.

Solution: truncate results in output in-place BEFORE they reach
serialize_content_blocks (-> DB) and convert_content_blocks_to_messages (-> LLM).
Single interception point: in tool loop before _saved_output deep copy.

If ORCHESTRATOR_URL is set, full result is uploaded as a file
to computer-use-server, model receives preview + file_path.
Otherwise, only preview + truncation notice.

Two intercept points:
  Mod 2: Tool loop -- truncate CURRENT tool results before LLM + DB
  Mod 3: History -- truncate OLD tool results loaded from DB before LLM

Config env vars:
  TOOL_RESULT_MAX_CHARS (default: 50000) -- truncation threshold (~12.5K tokens). 0 = disable
  TOOL_RESULT_PREVIEW_CHARS (default: 2000) -- preview size
  ORCHESTRATOR_URL -- internal URL of computer-use-server for large-result uploads

Must run AFTER fix_tool_loop_errors.py (Mod 2 targets its marker).
Target: OpenWebUI v0.8.11-0.8.12
"""

import os

_PATCH_TARGET_OVERRIDE = os.environ.get("_PATCH_TARGET_OVERRIDE", "")
MIDDLEWARE_PATH = _PATCH_TARGET_OVERRIDE or "/app/backend/open_webui/utils/middleware.py"

PATCH_MARKER = "_truncate_large_results_in_output"

FUNCTION_CODE = '''
# === PATCH: _truncate_large_results_in_output -- truncate large MCP tool results (DB + LLM) ===
import os as _os_module

_TOOL_RESULT_MAX_CHARS = int(_os_module.environ.get('TOOL_RESULT_MAX_CHARS', '50000'))
_TOOL_RESULT_PREVIEW_CHARS = int(_os_module.environ.get('TOOL_RESULT_PREVIEW_CHARS', '2000'))
_ORCHESTRATOR_URL = _os_module.environ.get('ORCHESTRATOR_URL', '')


async def _upload_result_to_docker_ai(content: str, filename: str, chat_id: str) -> str:
    """Upload full tool result to docker-ai container. Returns file_path or empty string."""
    if not _ORCHESTRATOR_URL or not chat_id:
        return ''
    try:
        import aiohttp
        upload_url = f'{_ORCHESTRATOR_URL}/api/uploads/{chat_id}/{filename}'
        form = aiohttp.FormData()
        form.add_field('file', content.encode('utf-8'), filename=filename, content_type='text/plain')
        async with aiohttp.ClientSession() as session:
            async with session.post(upload_url, data=form, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status < 300:
                    return f'/mnt/user-data/uploads/{filename}'
                log.warning('TOOL_RESULT_UPLOAD: status=%d url=%s', resp.status, upload_url)
    except Exception as e:
        log.warning('TOOL_RESULT_UPLOAD_ERR: %s', e)
    return ''


async def _truncate_large_results_in_output(output: list, chat_id: str) -> None:
    """Truncate large tool results in output blocks IN-PLACE.

    Iterates output blocks, finds tool_calls results with content > threshold,
    optionally uploads full content to docker-ai, replaces with preview.
    Affects both DB storage (serialize_content_blocks) and LLM context
    (convert_content_blocks_to_messages) since both read from the same output.
    """
    if _TOOL_RESULT_MAX_CHARS <= 0:
        return
    import time as _time
    _trunc_msg = lambda size_kb, preview, fpath: (
        (f'[Tool result truncated: {size_kb:.0f} KB]\\n'
         f'Preview (first {_TOOL_RESULT_PREVIEW_CHARS} chars):\\n'
         f'{preview}\\n\\n---\\n'
         f'Full result saved to: {fpath}\\n'
         f'Read with: view {fpath} view_range=[1, 50]')
        if fpath else
        (f'[Tool result truncated: {size_kb:.0f} KB -> first {_TOOL_RESULT_PREVIEW_CHARS} chars]\\n'
         f'{preview}\\n\\n---\\n'
         f'[Result truncated. Full output was {size_kb:.0f} KB.]')
    )
    for block in output:
        btype = block.get('type', '')
        # --- Chat Completions format: type=tool_calls, results[].content ---
        if btype == 'tool_calls':
            tool_names = {}
            for tc in block.get('content', []):
                if not isinstance(tc, dict):
                    continue
                tc_id = tc.get('id', '')
                tc_name = tc.get('function', {}).get('name', '') if isinstance(tc.get('function'), dict) else ''
                if tc_id and tc_name:
                    tool_names[tc_id] = tc_name
            for result in block.get('results', []):
                content = result.get('content', '')
                if not isinstance(content, str) or len(content) <= _TOOL_RESULT_MAX_CHARS:
                    continue
                size_kb = len(content) / 1024
                tc_id = result.get('tool_call_id', 'unknown')
                tool_name = tool_names.get(tc_id, 'tool')
                preview = content[:_TOOL_RESULT_PREVIEW_CHARS]
                file_path = ''
                if _ORCHESTRATOR_URL and chat_id:
                    fname = f'tool_result_{tool_name}_{tc_id[:8]}_{int(_time.time())}.txt'
                    file_path = await _upload_result_to_docker_ai(content, fname, chat_id)
                result['content'] = _trunc_msg(size_kb, preview, file_path)
                log.info('TOOL_RESULT_TRUNCATED: fmt=tool_calls tool=%s orig_kb=%.1f uploaded=%s',
                         tool_name, size_kb, bool(file_path))
        # --- Responses API format: type=function_call_output, output[].text ---
        elif btype == 'function_call_output':
            for part in block.get('output', []):
                if part.get('type') != 'input_text':
                    continue
                text = part.get('text', '')
                if not isinstance(text, str) or len(text) <= _TOOL_RESULT_MAX_CHARS:
                    continue
                size_kb = len(text) / 1024
                preview = text[:_TOOL_RESULT_PREVIEW_CHARS]
                call_id = block.get('call_id', 'unknown')
                file_path = ''
                if _ORCHESTRATOR_URL and chat_id:
                    fname = f'tool_result_{call_id[:12]}_{int(_time.time())}.txt'
                    file_path = await _upload_result_to_docker_ai(text, fname, chat_id)
                part['text'] = _trunc_msg(size_kb, preview, file_path)
                log.info('TOOL_RESULT_TRUNCATED: fmt=function_call_output call_id=%s orig_kb=%.1f uploaded=%s',
                         call_id[:12], size_kb, bool(file_path))


def _truncate_tool_messages_in_history(messages: list) -> None:
    """Truncate large tool result messages from chat history IN-PLACE.

    Sync version (no upload) for old results loaded from DB via
    process_messages_with_output(). Prevents context window overflow
    from accumulated tool results in long chat sessions.
    """
    if _TOOL_RESULT_MAX_CHARS <= 0:
        return
    for msg in messages:
        if msg.get('role') != 'tool':
            continue
        content = msg.get('content', '')
        if not isinstance(content, str) or len(content) <= _TOOL_RESULT_MAX_CHARS:
            continue
        size_kb = len(content) / 1024
        preview = content[:_TOOL_RESULT_PREVIEW_CHARS]
        msg['content'] = (
            f'[Tool result from history truncated: {size_kb:.0f} KB -> first {_TOOL_RESULT_PREVIEW_CHARS} chars]\\n'
            f'{preview}\\n\\n---\\n'
            f'[Result truncated. Full output was {size_kb:.0f} KB.]'
        )
        log.info('TOOL_RESULT_HISTORY_TRUNCATED: orig_kb=%.1f', size_kb)
# === END PATCH: _truncate_large_results_in_output ===
'''

# Search pattern: targets code AFTER fix_tool_loop_errors.py (TOOL_LOOP_ERRORS_UNIFIED marker)
SEARCH_TOOL_LOOP = (
    "                    _saved_output = json.loads(json.dumps(output))"
    "  # TOOL_LOOP_ERRORS_UNIFIED: save for restore on error\n"
    "                    try:\n"
    "                        new_form_data = {\n"
)

REPLACE_TOOL_LOOP = (
    "                    await _truncate_large_results_in_output("
    "output, metadata.get('chat_id', ''))  # LARGE_TOOL_RESULTS\n"
    "                    _saved_output = json.loads(json.dumps(output))"
    "  # TOOL_LOOP_ERRORS_UNIFIED: save for restore on error\n"
    "                    try:\n"
    "                        new_form_data = {\n"
)


# Mod 3: Truncate historical tool messages loaded from DB
SEARCH_HISTORY = (
    "    form_data['messages'] = process_messages_with_output(form_data.get('messages', []))\n"
    "\n"
    "    system_message = get_system_message(form_data.get('messages', []))\n"
)

REPLACE_HISTORY = (
    "    form_data['messages'] = process_messages_with_output(form_data.get('messages', []))\n"
    "    _truncate_tool_messages_in_history(form_data['messages'])  # LARGE_TOOL_RESULTS: trim old results\n"
    "\n"
    "    system_message = get_system_message(form_data.get('messages', []))\n"
)


def apply_patch():
    """Apply large tool results truncation patch to middleware.py."""

    if not os.path.exists(MIDDLEWARE_PATH):
        print(f"  ERROR: File not found: {MIDDLEWARE_PATH}")
        return False

    with open(MIDDLEWARE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if already applied
    if PATCH_MARKER in content:
        print("  Patch already applied, skipping...")
        return True

    original = content
    changes = 0

    # Mod 1: Inject functions after imports
    import_marker = "from open_webui.models.chats import Chats"
    marker_idx = content.find(import_marker)
    if marker_idx < 0:
        print("  ERROR: Could not find import marker in middleware.py")
        return False

    eol_idx = content.index("\n", marker_idx) + 1
    content = content[:eol_idx] + FUNCTION_CODE + content[eol_idx:]
    print("  [1/3] Injected functions: _truncate_large_results_in_output, _truncate_tool_messages_in_history, _upload_result_to_docker_ai")
    changes += 1

    # Mod 2: Add truncation call before _saved_output in tool loop
    if SEARCH_TOOL_LOOP in content:
        content = content.replace(SEARCH_TOOL_LOOP, REPLACE_TOOL_LOOP, 1)
        print("  [2/3] Tool loop: truncate current results before _saved_output")
        changes += 1
    else:
        print("  WARNING: Tool loop pattern not found (TOOL_LOOP_ERRORS_UNIFIED marker)")
        print("  This patch requires fix_tool_loop_errors.py to be applied first")

    # Mod 3: Truncate historical tool messages from DB
    if SEARCH_HISTORY in content:
        content = content.replace(SEARCH_HISTORY, REPLACE_HISTORY, 1)
        print("  [3/3] History: truncate old tool results from DB")
        changes += 1
    else:
        print("  WARNING: History pattern not found (process_messages_with_output)")

    if content == original:
        print("  ERROR: No changes made!")
        return False

    with open(MIDDLEWARE_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  Large tool results patch applied! {changes}/3 modifications.")
    print(f"  Config: TOOL_RESULT_MAX_CHARS (default 50000), TOOL_RESULT_PREVIEW_CHARS (default 2000)")
    print(f"  Upload: ORCHESTRATOR_URL (optional, for Computer Use)")
    print(f"  Log markers: TOOL_RESULT_TRUNCATED, TOOL_RESULT_HISTORY_TRUNCATED")
    return True


if __name__ == "__main__":
    print("Applying large tool results truncation patch to middleware.py...")
    success = apply_patch()
    print("  Done!" if success else "  FAILED!")
    exit(0 if success else 1)
