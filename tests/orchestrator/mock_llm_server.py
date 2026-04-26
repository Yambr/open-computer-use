# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Mock LLM HTTP server for adapter-level real-CLI smoke tests (Phase 9.1).

Stands in for api.anthropic.com / api.openai.com so we can invoke the real
`claude`, `codex`, and `opencode` binaries without an external network or a
real LLM key. Speaks three wire protocols on a single port:

  POST /v1/messages          Anthropic Messages API (SSE)         -> claude
  POST /v1/responses         OpenAI Responses API (SSE)           -> codex
  POST /v1/chat/completions  OpenAI Chat Completions API (SSE)    -> opencode

All endpoints return a fixed deterministic completion ("Hello from mock LLM.")
so the test assertions can compare exact strings. Token counts are stubbed
constants. The server is single-threaded and synchronous on purpose — it
only needs to handle one CLI run at a time.

Standalone entry point so it can be launched as a subprocess or inside a
Docker container without dragging in pytest:

    python3 mock_llm_server.py --host 0.0.0.0 --port 18080

Stdlib only. No third-party deps so the test fixture stays portable.
"""

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


# Fixed completion text every endpoint returns. Tests assert this exact
# substring shows up in the adapter's parsed SubAgentResult.text.
MOCK_COMPLETION_TEXT = "Hello from mock LLM."

# Stubbed token usage. Tests can assert these come through where the
# adapter surfaces them.
MOCK_INPUT_TOKENS = 12
MOCK_OUTPUT_TOKENS = 7


def _read_request_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("content-length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _write_sse(handler: BaseHTTPRequestHandler, events: list[tuple[str, dict]]) -> None:
    """Stream a list of (event_name, json_data) tuples as SSE.

    Format per the SSE spec / Anthropic + OpenAI conventions:
        event: <name>
        data: <json>
        \n
    """
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.end_headers()
    for name, payload in events:
        chunk = f"event: {name}\ndata: {json.dumps(payload)}\n\n"
        handler.wfile.write(chunk.encode("utf-8"))
        handler.wfile.flush()
    handler.close_connection = True


def _write_json(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    raw = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _anthropic_messages_sse() -> list[tuple[str, dict]]:
    """Build a minimal valid Anthropic Messages SSE stream.

    Mirrors docs.anthropic.com/en/api/messages-streaming event sequence:
      message_start -> content_block_start -> content_block_delta(text) ->
      content_block_stop -> message_delta(stop_reason) -> message_stop
    """
    msg_id = "msg_mock_0001"
    return [
        ("message_start", {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "model": "claude-mock",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": MOCK_INPUT_TOKENS,
                    "output_tokens": 0,
                },
            },
        }),
        ("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }),
        ("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": MOCK_COMPLETION_TEXT},
        }),
        ("content_block_stop", {
            "type": "content_block_stop",
            "index": 0,
        }),
        ("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": MOCK_OUTPUT_TOKENS},
        }),
        ("message_stop", {"type": "message_stop"}),
    ]


def _openai_responses_sse() -> list[tuple[str, dict]]:
    """Build a minimal valid OpenAI Responses API SSE stream.

    Mirrors platform.openai.com/docs/api-reference/responses-streaming events:
      response.created -> response.output_item.added(message) ->
      response.content_part.added(output_text) ->
      response.output_text.delta -> response.output_text.done ->
      response.content_part.done -> response.output_item.done ->
      response.completed (with usage)
    """
    resp_id = "resp_mock_0001"
    item_id = "msg_mock_item_0001"
    base_message = {
        "id": item_id,
        "type": "message",
        "role": "assistant",
        "status": "in_progress",
        "content": [],
    }
    return [
        ("response.created", {
            "type": "response.created",
            "response": {"id": resp_id, "status": "in_progress", "model": "codex-mock"},
        }),
        ("response.output_item.added", {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": base_message,
        }),
        ("response.content_part.added", {
            "type": "response.content_part.added",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": ""},
        }),
        ("response.output_text.delta", {
            "type": "response.output_text.delta",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "delta": MOCK_COMPLETION_TEXT,
        }),
        ("response.output_text.done", {
            "type": "response.output_text.done",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "text": MOCK_COMPLETION_TEXT,
        }),
        ("response.content_part.done", {
            "type": "response.content_part.done",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": MOCK_COMPLETION_TEXT},
        }),
        ("response.output_item.done", {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                **base_message,
                "status": "completed",
                "content": [{"type": "output_text", "text": MOCK_COMPLETION_TEXT}],
            },
        }),
        ("response.completed", {
            "type": "response.completed",
            "response": {
                "id": resp_id,
                "status": "completed",
                "model": "codex-mock",
                "output": [{
                    **base_message,
                    "status": "completed",
                    "content": [{"type": "output_text", "text": MOCK_COMPLETION_TEXT}],
                }],
                "usage": {
                    "input_tokens": MOCK_INPUT_TOKENS,
                    "output_tokens": MOCK_OUTPUT_TOKENS,
                    "total_tokens": MOCK_INPUT_TOKENS + MOCK_OUTPUT_TOKENS,
                },
            },
        }),
    ]


class MockLLMHandler(BaseHTTPRequestHandler):
    """Route POST requests to the matching protocol stub."""

    # HTTP/1.1 so `Connection: close` is honored by clients (curl, OpenAI SDK).
    protocol_version = "HTTP/1.1"

    # Keep stdout clean during tests; logs go to stderr only on errors.
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        # /healthz so the runner script can poll readiness.
        path = urlparse(self.path).path
        if path in ("/healthz", "/health"):
            _write_json(self, 200, {"status": "ok"})
            return
        _write_json(self, 404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            _read_request_json(self)  # drain body; content not inspected
        except Exception:
            pass

        if path == "/v1/messages":
            _write_sse(self, _anthropic_messages_sse())
            return

        if path == "/v1/responses":
            _write_sse(self, _openai_responses_sse())
            return

        if path == "/v1/chat/completions":
            self._write_chat_completion_stream()
            return

        if path == "/v1/models":
            _write_json(self, 200, {
                "object": "list",
                "data": [
                    {"id": "gpt-5-codex", "object": "model"},
                    {"id": "qwen/qwen-3-coder", "object": "model"},
                ],
            })
            return

        _write_json(self, 404, {"error": f"unhandled path: {path}"})

    def _write_chat_completion_stream(self):
        """OpenAI chat-completions SSE: bare `data: <json>` chunks + [DONE]."""
        chunks = [
            {
                "id": "chatcmpl-mock-0001",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "mock-chat",
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": ""},
                    "finish_reason": None,
                }],
            },
            {
                "id": "chatcmpl-mock-0001",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "mock-chat",
                "choices": [{
                    "index": 0,
                    "delta": {"content": MOCK_COMPLETION_TEXT},
                    "finish_reason": None,
                }],
            },
            {
                "id": "chatcmpl-mock-0001",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "mock-chat",
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": MOCK_INPUT_TOKENS,
                    "completion_tokens": MOCK_OUTPUT_TOKENS,
                    "total_tokens": MOCK_INPUT_TOKENS + MOCK_OUTPUT_TOKENS,
                },
            },
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


def serve(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), MockLLMHandler)
    print(f"mock-llm: listening on http://{host}:{port}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock LLM HTTP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
