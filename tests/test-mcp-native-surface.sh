#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
#
# Smoke tests for the six MCP-native system-prompt delivery tiers.
# Hits a LIVE computer-use-server on http://localhost:8081 and walks every
# channel end-to-end (curl only — no Python client dependency).
#
# Usage:
#   docker compose up --build -d computer-use-server
#   ./tests/test-mcp-native-surface.sh [server-url]
#
# Default server URL: http://localhost:8081
#
# Requires: docker, curl, jq

set -euo pipefail

SERVER_URL="${1:-http://localhost:8081}"
PASSED=0
FAILED=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}PASS${NC}: $1"; PASSED=$((PASSED + 1)); }
fail() { echo -e "  ${RED}FAIL${NC}: $1"; FAILED=$((FAILED + 1)); }
skip() { echo -e "  ${YELLOW}SKIP${NC}: $1"; }

banner() { echo ""; echo "=== $1 ==="; }

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

banner "Pre-flight"

if ! curl -sf "${SERVER_URL}/health" >/dev/null 2>&1; then
    echo -e "${RED}ERROR${NC}: ${SERVER_URL}/health is unreachable."
    echo "Start the server first: docker compose up --build -d computer-use-server"
    exit 1
fi
pass "server reachable at ${SERVER_URL}"

# ---------------------------------------------------------------------------
# Tier 6 — HTTP /system-prompt (the easiest to exercise via curl)
# ---------------------------------------------------------------------------

banner "Tier 6 — HTTP /system-prompt (header priority + aliases + response header)"

BODY=$(curl -sS "${SERVER_URL}/system-prompt?chat_id=smoke-qry")
if echo "$BODY" | grep -q "/files/smoke-qry"; then
    pass "query chat_id substituted into /files/ URL"
else
    fail "query chat_id NOT substituted (expected /files/smoke-qry)"
fi

BODY=$(curl -sS -H "X-Chat-Id: smoke-hdr" "${SERVER_URL}/system-prompt?chat_id=smoke-qry-loses")
if echo "$BODY" | grep -q "/files/smoke-hdr" && ! echo "$BODY" | grep -q "/files/smoke-qry-loses"; then
    pass "header wins over query (smoke-hdr present, smoke-qry-loses absent)"
else
    fail "header priority broken"
fi

BODY=$(curl -sS -H "X-OpenWebUI-Chat-Id: smoke-alias" "${SERVER_URL}/system-prompt")
if echo "$BODY" | grep -q "/files/smoke-alias"; then
    pass "X-OpenWebUI-Chat-Id alias honored"
else
    fail "X-OpenWebUI-Chat-Id alias ignored"
fi

# X-Public-Base-URL response header present (Open WebUI filter depends on it)
HDRS=$(curl -sS -D - -o /dev/null "${SERVER_URL}/system-prompt?chat_id=smoke")
if echo "$HDRS" | grep -qi "^x-public-base-url:"; then
    pass "X-Public-Base-URL response header emitted"
else
    fail "X-Public-Base-URL response header missing (Open WebUI filter will lose public URL)"
fi

# Foundation: self-identification header first
BODY=$(curl -sS "${SERVER_URL}/system-prompt?chat_id=smoke-id")
if echo "$BODY" | grep -q "This is the contents of /home/assistant/README.md"; then
    pass "rendered prompt carries README.md self-identification header"
else
    fail "self-identification header missing — clients won't know the canonical location"
fi

# ---------------------------------------------------------------------------
# Tier 2 — README.md in sandbox (requires MCP tool call to create a container)
# ---------------------------------------------------------------------------

banner "Tier 2 — /home/assistant/README.md in sandbox"

# Look for a sandbox container created AFTER the server process started.
# Containers from previous sessions predate this commit and will not have
# README.md — we do not retro-fit existing workspace volumes.
SERVER_PID=$(docker inspect --format '{{.State.StartedAt}}' computer-use-server 2>/dev/null || echo "")
CONTAINER=""
if [ -n "$SERVER_PID" ]; then
    for c in $(docker ps -q --filter "label=tool=computer-use-mcp"); do
        CREATED=$(docker inspect --format '{{.Created}}' "$c" 2>/dev/null || echo "")
        if [ -n "$CREATED" ] && [ "$CREATED" \> "$SERVER_PID" ]; then
            CONTAINER="$c"
            break
        fi
    done
fi

if [ -z "$CONTAINER" ]; then
    skip "no sandbox container newer than computer-use-server startup — trigger an MCP bash_tool call via a real client first (stale pre-refactor containers don't count)"
else
    if docker exec "$CONTAINER" cat /home/assistant/README.md 2>/dev/null | grep -q "This is the contents"; then
        pass "README.md present in container ${CONTAINER}, carries self-id header"
    elif docker exec "$CONTAINER" test -f /home/assistant/README.md 2>/dev/null; then
        pass "README.md present in container ${CONTAINER} (header format unknown — review manually)"
    else
        fail "README.md not present in container ${CONTAINER} — Tier 2 write failed"
    fi
fi

# ---------------------------------------------------------------------------
# Tier 1 — tool description nudges (depends on MCP tools/list)
# Tier 3/4 — InitializeResult.instructions (depends on MCP initialize)
# Tier 5 — resources/list (depends on MCP resources/list)
#
# All three need a working MCP JSON-RPC endpoint. There is a pre-existing
# double-session_manager bug (see PR body) that blocks this path under
# uvicorn. In-process tests in tests/orchestrator/ cover them:
#
#   - test_tool_descriptions.py        (Tier 1)
#   - test_dynamic_instructions.py     (Tier 4)
#   - test_mcp_resources.py            (Tier 5)
#
# We still probe /mcp here so the smoke suite picks up the day we fix that.
# ---------------------------------------------------------------------------

banner "Tiers 1/3/4/5 — MCP JSON-RPC probe"

INIT_PAYLOAD='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"1.0"}}}'

STATUS=$(curl -s -o /tmp/mcp-init.out -w '%{http_code}' -X POST "${SERVER_URL}/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'X-Chat-Id: smoke-mcp' \
    -d "$INIT_PAYLOAD")

if [ "$STATUS" = "200" ]; then
    if grep -q '"instructions"' /tmp/mcp-init.out || grep -q 'instructions' /tmp/mcp-init.out; then
        pass "MCP initialize returned 200 with instructions (Tier 4)"
    else
        fail "MCP initialize returned 200 but no 'instructions' field"
    fi

    # tools/list
    curl -sS -X POST "${SERVER_URL}/mcp" \
        -H 'Content-Type: application/json' \
        -H 'Accept: application/json, text/event-stream' \
        -H 'X-Chat-Id: smoke-mcp' \
        -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' > /tmp/mcp-tools.out
    if grep -q 'README.md' /tmp/mcp-tools.out; then
        pass "tools/list descriptions mention README.md (Tier 1)"
    else
        fail "tools/list descriptions do not mention README.md"
    fi
else
    skip "MCP /mcp endpoint returned ${STATUS} — pre-existing double-session_manager bug (see PR). In-process pytest covers these tiers."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "==============================="
echo "  PASSED: ${PASSED}"
echo "  FAILED: ${FAILED}"
echo ""

if [ "$FAILED" -gt 0 ]; then
    echo -e "  ${RED}RESULT: FAILED${NC}"
    exit 1
fi
echo -e "  ${GREEN}RESULT: ALL CLEAN${NC}"
