#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
#
# Live smoke test for the /mcp JSON-RPC endpoint.
#
# Catches the failure mode where the server boots, /health returns 200, but
# POST /mcp returns 500 because session_manager.run() never entered the
# context manager (e.g. lifespan swallowed an ImportError, or workers misbehave).
#
# Usage:
#   ./tests/test-mcp-endpoint-live.sh                          # default http://localhost:8081
#   ./tests/test-mcp-endpoint-live.sh http://localhost:8081
#   docker exec open-computer-use-open-webui-1 bash -c "$(cat tests/test-mcp-endpoint-live.sh)"

set -u

SERVER_URL="${1:-http://localhost:8081}"
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"1.0"}}}'

echo "Probing ${SERVER_URL}/mcp ..."
HDRS=$(mktemp)
BODY=$(mktemp)
trap 'rm -f "$HDRS" "$BODY"' EXIT

STATUS=$(curl -sS -D "$HDRS" -o "$BODY" -w '%{http_code}' -X POST "${SERVER_URL}/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'X-Chat-Id: smoke-live' \
  -d "$INIT" || echo "curl-failed")

if [ "$STATUS" != "200" ]; then
  echo "FAIL: POST /mcp returned $STATUS (expected 200)"
  echo "--- response body ---"
  head -c 2000 "$BODY"; echo
  echo "--- response headers ---"
  cat "$HDRS"
  echo ""
  echo "Hint: if the body says 'Internal Server Error' with no traceback,"
  echo "      the lifespan likely never entered session_manager.run()."
  echo "      Check that mcp_resources.py and uploads.py are present in the image:"
  echo "        docker exec computer-use-server ls /app/ | grep -E 'mcp_resources|uploads'"
  exit 1
fi

# Streamable-HTTP returns either JSON or SSE. Both contain "instructions".
if ! grep -q '"instructions"' "$BODY"; then
  echo "FAIL: 200 OK but no 'instructions' field in body — Tier 4 broken"
  head -c 1000 "$BODY"; echo
  exit 1
fi

# Session id should be present in headers — needed for follow-up tools/list calls.
if ! grep -qi '^mcp-session-id:' "$HDRS"; then
  echo "WARN: no Mcp-Session-Id response header (follow-up calls will allocate fresh session)"
fi

echo "PASS: POST /mcp -> 200 with instructions field"
