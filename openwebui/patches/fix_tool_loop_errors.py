#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Unified patch: error handling for tool loop, code interpreter, SSE, and background tasks.

Replaces 3 separate patches:
- fix_debug_streaming_errors.py (TEMPORARY debug logging)
- fix_transport_retry.py (transport error handling + non-streaming errors)
- fix_tool_loop_error.py (budget error display + background tasks)

Problems solved:
1. Tool loop errors silently swallowed (log.debug + break) — user sees garbage
2. Transport errors (aiohttp.ClientPayloadError) leave partial output
3. Non-streaming errors (JSONResponse 400) silently break
4. "Model not found" on budget exhaustion — cryptic message for user
5. Background tasks (follow_ups/title/tags) crash on 404 after budget exceeded
6. SSE parse errors logged at debug level only

Applied at Docker build time. Works on ORIGINAL middleware.py (no dependencies).
Target: OpenWebUI v0.8.11-0.9.1 (output-based architecture, serialize_output, prior_output).

Fail-loud: ANY sub-anchor miss triggers sys.exit(1) with stderr ERROR — refuses
to ship a partially-patched middleware.py. Idempotent: re-run prints ALREADY PATCHED.
"""

import os
import sys

_PATCH_TARGET_OVERRIDE = os.environ.get("_PATCH_TARGET_OVERRIDE", "")
MIDDLEWARE_PATH = _PATCH_TARGET_OVERRIDE or "/app/backend/open_webui/utils/middleware.py"

PATCH_MARKER = "TOOL_LOOP_ERRORS_UNIFIED"   # legacy marker — retained
NEW_PATCH_MARKER = "FIX_TOOL_LOOP_ERRORS"   # v0.9.1.0 marker (appears in injected comments)

_BUDGET_MSG = (
    "Model temporarily unavailable. "
    "Request limit may be exceeded. "
    "Try again later or choose another model."
)
_TRANSPORT_MSG = (
    "Connection error while receiving model response. "
    "Resend message to continue."
)
_ERROR_LABEL = "Error"

# ============================================================
# Mod 1: Tool loop — full error handling
# ============================================================
SEARCH_TOOL_LOOP = """\
                    try:
                        new_form_data = {
                            **form_data,
                            'model': model_id,
                            'stream': True,
                            'metadata': metadata,
                        }

                        if ENABLE_RESPONSES_API_STATEFUL and last_response_id:
                            system_message = get_system_message(form_data['messages'])
                            new_form_data['messages'] = (
                                [system_message] if system_message else []
                            ) + convert_output_to_messages(output, raw=True)
                            new_form_data['previous_response_id'] = last_response_id
                        else:
                            tool_messages = convert_output_to_messages(output, raw=True)

                            # Chat Completions providers don't support multimodal
                            # tool messages.  Extract images into a user message.
                            image_urls = []
                            for message in tool_messages:
                                if message.get('role') == 'tool' and isinstance(message.get('content'), list):
                                    text_parts = []
                                    for part in message['content']:
                                        if part.get('type') == 'input_text':
                                            text_parts.append(part.get('text', ''))
                                        elif part.get('type') == 'input_image':
                                            image_urls.append(part.get('image_url', ''))
                                    message['content'] = ''.join(text_parts)

                            new_form_data['messages'] = [
                                *form_data['messages'],
                                *tool_messages,
                            ]

                            if image_urls:
                                new_form_data['messages'].append(
                                    {
                                        'role': 'user',
                                        'content': [
                                            {
                                                'type': 'text',
                                                'text': 'Here are the images from the tool results above. Please analyze them.',
                                            },
                                            *[{'type': 'image_url', 'image_url': {'url': url}} for url in image_urls],
                                        ],
                                    }
                                )

                        res = await generate_chat_completion(
                            request,
                            new_form_data,
                            user,
                            bypass_system_prompt=True,
                        )

                        if isinstance(res, StreamingResponse):
                            # Save accumulated output and start fresh.
                            # Responses API output_index values are relative
                            # to the current response — a clean output list
                            # keeps indices aligned. The display prefix
                            # ensures the UI shows tool history during
                            # streaming.
                            prior_output = list(output)
                            # Trim the trailing empty placeholder message
                            # so it doesn't persist as a ghost item once
                            # the new stream produces real content.
                            if (
                                prior_output
                                and prior_output[-1].get('type') == 'message'
                                and prior_output[-1].get('status') == 'in_progress'
                            ):
                                msg_parts = prior_output[-1].get('content', [])
                                if not msg_parts or (len(msg_parts) == 1 and not msg_parts[0].get('text', '').strip()):
                                    prior_output.pop()
                            output = []
                            await stream_body_handler(res, new_form_data)
                            output[:0] = prior_output
                            prior_output = []
                        else:
                            break
                    except Exception as e:
                        log.debug(e)
                        break

                if DETECT_CODE_INTERPRETER:"""

REPLACE_TOOL_LOOP = (
    "                    _saved_output = json.loads(json.dumps(output))  # TOOL_LOOP_ERRORS_UNIFIED: save for restore on error\n"
    "                    try:\n"
    "                        new_form_data = {\n"
    "                            **form_data,\n"
    "                            'model': model_id,\n"
    "                            'stream': True,\n"
    "                            'metadata': metadata,\n"
    "                        }\n"
    "\n"
    "                        if ENABLE_RESPONSES_API_STATEFUL and last_response_id:\n"
    "                            system_message = get_system_message(form_data['messages'])\n"
    "                            new_form_data['messages'] = (\n"
    "                                [system_message] if system_message else []\n"
    "                            ) + convert_output_to_messages(output, raw=True)\n"
    "                            new_form_data['previous_response_id'] = last_response_id\n"
    "                        else:\n"
    "                            tool_messages = convert_output_to_messages(output, raw=True)\n"
    "\n"
    "                            # Chat Completions providers don't support multimodal\n"
    "                            # tool messages.  Extract images into a user message.\n"
    "                            image_urls = []\n"
    "                            for message in tool_messages:\n"
    "                                if message.get('role') == 'tool' and isinstance(message.get('content'), list):\n"
    "                                    text_parts = []\n"
    "                                    for part in message['content']:\n"
    "                                        if part.get('type') == 'input_text':\n"
    "                                            text_parts.append(part.get('text', ''))\n"
    "                                        elif part.get('type') == 'input_image':\n"
    "                                            image_urls.append(part.get('image_url', ''))\n"
    "                                    message['content'] = ''.join(text_parts)\n"
    "\n"
    "                            new_form_data['messages'] = [\n"
    "                                *form_data['messages'],\n"
    "                                *tool_messages,\n"
    "                            ]\n"
    "\n"
    "                            if image_urls:\n"
    "                                new_form_data['messages'].append(\n"
    "                                    {\n"
    "                                        'role': 'user',\n"
    "                                        'content': [\n"
    "                                            {\n"
    "                                                'type': 'text',\n"
    "                                                'text': 'Here are the images from the tool results above. Please analyze them.',\n"
    "                                            },\n"
    "                                            *[{'type': 'image_url', 'image_url': {'url': url}} for url in image_urls],\n"
    "                                        ],\n"
    "                                    }\n"
    "                                )\n"
    "\n"
    "                        res = await generate_chat_completion(\n"
    "                            request,\n"
    "                            new_form_data,\n"
    "                            user,\n"
    "                            bypass_system_prompt=True,\n"
    "                        )\n"
    "\n"
    "                        if isinstance(res, StreamingResponse):\n"
    "                            # Save accumulated output and start fresh.\n"
    "                            # Responses API output_index values are relative\n"
    "                            # to the current response -- a clean output list\n"
    "                            # keeps indices aligned. The display prefix\n"
    "                            # ensures the UI shows tool history during\n"
    "                            # streaming.\n"
    "                            prior_output = list(output)\n"
    "                            # Trim the trailing empty placeholder message\n"
    "                            # so it doesn't persist as a ghost item once\n"
    "                            # the new stream produces real content.\n"
    "                            if (\n"
    "                                prior_output\n"
    "                                and prior_output[-1].get('type') == 'message'\n"
    "                                and prior_output[-1].get('status') == 'in_progress'\n"
    "                            ):\n"
    "                                msg_parts = prior_output[-1].get('content', [])\n"
    "                                if not msg_parts or (len(msg_parts) == 1 and not msg_parts[0].get('text', '').strip()):\n"
    "                                    prior_output.pop()\n"
    "                            output = []\n"
    "                            await stream_body_handler(res, new_form_data)\n"
    "                            output[:0] = prior_output\n"
    "                            prior_output = []\n"
    "                        else:\n"
    "                            # TOOL_LOOP_ERRORS_UNIFIED: handle non-streaming error (ContextWindowExceeded, rate limit, etc)\n"
    "                            _err_detail = None\n"
    "                            try:\n"
    "                                if hasattr(res, 'body') and isinstance(res.body, bytes):\n"
    "                                    _resp_data = json.loads(res.body.decode('utf-8', 'replace'))\n"
    "                                    if 'error' in _resp_data:\n"
    "                                        _err_obj = _resp_data['error']\n"
    "                                        _err_detail = _err_obj.get('message') or _err_obj.get('detail') or str(_err_obj) if isinstance(_err_obj, dict) else str(_err_obj)\n"
    "                            except Exception:\n"
    "                                _err_detail = f'Non-streaming error response: {type(res).__name__}'\n"
    "                            if _err_detail:\n"
    "                                log.error('NON_STREAM_ERROR: chat=%s iter=%d error=%s',\n"
    "                                    metadata.get('chat_id', '')[:8], tool_call_retries, _err_detail)\n"
    "                                output[:] = _saved_output\n"
    "                                if 'Model not found' in _err_detail:\n"
    "                                    _err_detail = '" + _BUDGET_MSG + "'\n"
    "                                # Keep only message items (text the user already saw)\n"
    "                                _msg_items = [item for item in _saved_output if item.get('type') == 'message']\n"
    "                                _msg_items.append({'type': 'message', 'id': '', 'status': 'completed', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': f'\\n\\n---\\n**" + _ERROR_LABEL + ":** {_err_detail[:1000]}'}]})\n"
    "                                output[:] = _msg_items\n"
    "                                try:\n"
    "                                    await event_emitter({'type': 'chat:message:error', 'data': {'error': {'content': _err_detail}}})\n"
    "                                    await event_emitter({'type': 'chat:completion', 'data': {'content': serialize_output(output), 'output': output}})\n"
    "                                except Exception:\n"
    "                                    pass\n"
    "                            break\n"
    "                    except Exception as e:\n"
    "                        # TOOL_LOOP_ERRORS_UNIFIED: restore clean output + show error; FIX_TOOL_LOOP_ERRORS\n"
    "                        import traceback as _tb\n"
    "                        _msg_items = [item for item in _saved_output if item.get('type') == 'message']\n"
    "                        _err_mod = getattr(type(e), '__module__', '') or ''\n"
    "                        _is_transport = 'aiohttp' in _err_mod or isinstance(e, (ConnectionError, TimeoutError, OSError))\n"
    "                        if _is_transport:\n"
    "                            log.warning('TRANSPORT_ERROR: chat=%s iter=%d error=%s',\n"
    "                                metadata.get('chat_id', '')[:8], tool_call_retries, e)\n"
    "                            _ui_err = '" + _TRANSPORT_MSG + "'\n"
    "                        else:\n"
    "                            log.error('TOOL_LOOP_ERROR: chat=%s iter=%d error=%s\\n%s',\n"
    "                                metadata.get('chat_id', '')[:8], tool_call_retries, e, _tb.format_exc())\n"
    "                            _ui_err = str(e)[:1000]\n"
    "                            if 'Model not found' in _ui_err:\n"
    "                                _ui_err = '" + _BUDGET_MSG + "'\n"
    "                        try:\n"
    "                            _msg_items.append({'type': 'message', 'id': '', 'status': 'completed', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': f'\\n\\n---\\n**" + _ERROR_LABEL + ":** {_ui_err}'}]})\n"
    "                            output[:] = _msg_items\n"
    "                            await event_emitter({'type': 'chat:message:error', 'data': {'error': {'content': _ui_err}}})\n"
    "                            await event_emitter({'type': 'chat:completion', 'data': {'content': serialize_output(output), 'output': output}})\n"
    "                        except Exception:\n"
    "                            pass\n"
    "                        break\n"
    "\n"
    "                if DETECT_CODE_INTERPRETER:"
)

# ============================================================
# Mod 2: Code interpreter catch -> log.error + UI error display
# v0.9.1: `title = await Chats.get_chat_title_by_id(...)` — async-ified
# ============================================================
SEARCH_CODE_INTERP = """\
                        except Exception as e:
                            log.debug(e)
                            break

                # Mark all in-progress items as completed
                for item in output:
                    if item.get('status') == 'in_progress':
                        item['status'] = 'completed'

                title = await Chats.get_chat_title_by_id(metadata['chat_id'])"""

REPLACE_CODE_INTERP = (
    "                        except Exception as e:\n"
    "                            import traceback as _tb  # TOOL_LOOP_ERRORS_UNIFIED; FIX_TOOL_LOOP_ERRORS\n"
    "                            log.error('CODE_INTERP_ERROR: chat=%s iter=%d error=%s\\n%s',\n"
    "                                metadata.get('chat_id', '')[:8], retries, e, _tb.format_exc())\n"
    "                            try:\n"
    "                                output.append({'type': 'message', 'id': '', 'status': 'completed', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': f'\\n\\n---\\n**" + _ERROR_LABEL + ":** {str(e)[:1000]}'}]})\n"
    "                                await event_emitter({'type': 'chat:completion', 'data': {'content': serialize_output(output), 'output': output}})\n"
    "                            except Exception:\n"
    "                                pass\n"
    "                            break\n"
    "\n"
    "                # Mark all in-progress items as completed\n"
    "                for item in output:\n"
    "                    if item.get('status') == 'in_progress':\n"
    "                        item['status'] = 'completed'\n"
    "\n"
    "                title = await Chats.get_chat_title_by_id(metadata['chat_id'])"
)

# ============================================================
# Mod 3: SSE parse catch -> log.error with context
# ============================================================
SEARCH_SSE = """\
                        except Exception as e:
                            done = 'data: [DONE]' in line
                            if done:
                                pass
                            else:
                                log.debug(f'Error: {e}')
                                continue"""

REPLACE_SSE = """\
                        except Exception as e:
                            done = 'data: [DONE]' in line
                            if done:
                                pass
                            else:
                                log.error('SSE_PARSE_ERROR: chat=%s line=%.200s error=%s',  # TOOL_LOOP_ERRORS_UNIFIED; FIX_TOOL_LOOP_ERRORS
                                    metadata.get('chat_id', '')[:8], str(line)[:200], e)
                                continue"""

# ============================================================
# Mod 4: Done emit try/except + background_tasks_handler wrapper
# v0.9.1: two new lines inserted between `await background_tasks_handler(ctx)`
# and `except asyncio.CancelledError:` — `ctx['assistant_message'] = {...}` +
# `await outlet_filter_handler(ctx)`. Both must be preserved inside the wrap.
# ============================================================
SEARCH_DONE_BG = """\
                await event_emitter(
                    {
                        'type': 'chat:completion',
                        'data': data,
                    }
                )

                await background_tasks_handler(ctx)
                ctx['assistant_message'] = {
                    'content': serialize_output(output),
                    'output': output,
                    **({'usage': usage} if usage else {}),
                }
                await outlet_filter_handler(ctx)
            except asyncio.CancelledError:"""

REPLACE_DONE_BG = """\
                try:  # TOOL_LOOP_ERRORS_UNIFIED: wrap done emit; FIX_TOOL_LOOP_ERRORS
                    await event_emitter(
                        {
                            'type': 'chat:completion',
                            'data': data,
                        }
                    )
                except Exception as _done_err:
                    log.error('DONE_EMIT_ERROR: chat=%s error=%s',
                        metadata.get('chat_id', '')[:8], _done_err)

                try:
                    await background_tasks_handler(ctx)
                    ctx['assistant_message'] = {
                        'content': serialize_output(output),
                        'output': output,
                        **({'usage': usage} if usage else {}),
                    }
                    await outlet_filter_handler(ctx)
                except Exception as _bg_err:
                    log.error('BACKGROUND_TASK_ERROR: chat=%s error=%s',  # TOOL_LOOP_ERRORS_UNIFIED
                        metadata.get('chat_id', '')[:8], _bg_err)
            except asyncio.CancelledError:"""

# ============================================================
# Mod 5: TOOL_LOOP_ITER lifecycle logging
# ============================================================
SEARCH_ITER = """\
                while len(tool_calls) > 0 and tool_call_retries < CHAT_RESPONSE_MAX_TOOL_CALL_RETRIES:
                    tool_call_retries += 1"""

REPLACE_ITER = """\
                while len(tool_calls) > 0 and tool_call_retries < CHAT_RESPONSE_MAX_TOOL_CALL_RETRIES:
                    tool_call_retries += 1
                    log.debug('TOOL_LOOP_ITER: chat=%s iter=%d pending_tc=%d',  # TOOL_LOOP_ERRORS_UNIFIED; FIX_TOOL_LOOP_ERRORS
                        metadata.get('chat_id', '')[:8], tool_call_retries, len(tool_calls))"""


def apply_patch():
    if not os.path.exists(MIDDLEWARE_PATH):
        print(
            f"ERROR: fix_tool_loop_errors target file {MIDDLEWARE_PATH} not found. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(MIDDLEWARE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if PATCH_MARKER in content or NEW_PATCH_MARKER in content:
        print(f"ALREADY PATCHED: {MIDDLEWARE_PATH} contains {PATCH_MARKER}")
        return True

    # v0.9.1 -> v0.9.2 backward-compat shim: v0.9.2 upstream inserted a new
    # `'metadata': metadata,` key into the first `new_form_data = {` block. The
    # SEARCH_TOOL_LOOP anchor targets the v0.9.2 shape; for v0.9.1 input we
    # inject the missing key in-memory so the single SEARCH matches both
    # upstream versions. No-op on v0.9.2 (V091_SHIM does not match there).
    V091_SHIM = "                            'stream': True,\n                        }\n\n                        if ENABLE_RESPONSES_API_STATEFUL"
    V092_SHIM = "                            'stream': True,\n                            'metadata': metadata,\n                        }\n\n                        if ENABLE_RESPONSES_API_STATEFUL"
    if V091_SHIM in content and V092_SHIM not in content:
        content = content.replace(V091_SHIM, V092_SHIM, 1)

    # Mod 1/5: tool_loop
    if SEARCH_TOOL_LOOP not in content:
        print(
            f"ERROR: fix_tool_loop_errors anchor 1/5 (tool_loop) not found in {MIDDLEWARE_PATH} "
            "— upstream may have refactored the tool-retry try/except. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)
    content = content.replace(SEARCH_TOOL_LOOP, REPLACE_TOOL_LOOP, 1)
    print("  [1/5] Tool loop: save/restore + transport + non-stream + Model not found + chat:message:error")

    # Mod 2/5: code_interp (v0.9.1: await-ified Chats.get_chat_title_by_id)
    if SEARCH_CODE_INTERP not in content:
        print(
            f"ERROR: fix_tool_loop_errors anchor 2/5 (code_interp) not found in {MIDDLEWARE_PATH} "
            "— upstream may have refactored the code-interpreter except block or the "
            "await Chats.get_chat_title_by_id call. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)
    content = content.replace(SEARCH_CODE_INTERP, REPLACE_CODE_INTERP, 1)
    print("  [2/5] Code interpreter: log.error + UI error display")

    # Mod 3/5: sse
    if SEARCH_SSE not in content:
        print(
            f"ERROR: fix_tool_loop_errors anchor 3/5 (sse) not found in {MIDDLEWARE_PATH} "
            "— upstream may have refactored the SSE parse except block. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)
    content = content.replace(SEARCH_SSE, REPLACE_SSE, 1)
    print("  [3/5] SSE parse: log.error with context")

    # Mod 4/5: done_bg
    if SEARCH_DONE_BG not in content:
        print(
            f"ERROR: fix_tool_loop_errors anchor 4/5 (done_bg) not found in {MIDDLEWARE_PATH} "
            "— upstream may have refactored the background_tasks_handler block "
            "(v0.9.1 inserted assistant_message + outlet_filter_handler). "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)
    content = content.replace(SEARCH_DONE_BG, REPLACE_DONE_BG, 1)
    print("  [4/5] Done emit wrapped + background_tasks_handler wrapped")

    # Mod 5/5: iter
    if SEARCH_ITER not in content:
        print(
            f"ERROR: fix_tool_loop_errors anchor 5/5 (iter) not found in {MIDDLEWARE_PATH} "
            "— upstream may have refactored the tool-retry while-loop start. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)
    content = content.replace(SEARCH_ITER, REPLACE_ITER, 1)
    print("  [5/5] TOOL_LOOP_ITER lifecycle logging")

    with open(MIDDLEWARE_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("PATCHED: fix_tool_loop_errors applied successfully.")
    print("  Log markers: TOOL_LOOP_ERROR, TRANSPORT_ERROR, NON_STREAM_ERROR,")
    print("               CODE_INTERP_ERROR, SSE_PARSE_ERROR, DONE_EMIT_ERROR,")
    print("               BACKGROUND_TASK_ERROR, TOOL_LOOP_ITER")
    return True


if __name__ == "__main__":
    print("Applying unified tool loop errors patch to middleware.py...")
    success = apply_patch()
    sys.exit(0 if success else 1)
