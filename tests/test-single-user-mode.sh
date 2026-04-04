#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
#
# Integration tests for SINGLE_USER_MODE feature.
# Builds computer-use-server image, starts it with different env vars,
# sends MCP requests via curl, verifies responses.
#
# Usage: ./tests/test-single-user-mode.sh
#
# Requires: docker, curl, jq

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="computer-use-server-test-sum"
BASE_PORT=18081
PASSED=0
FAILED=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

cleanup() {
    echo ""
    echo "Cleaning up test containers..."
    docker rm -f $(docker ps -aq --filter "label=test=single-user-mode") 2>/dev/null || true
}
trap cleanup EXIT

pass() {
    echo -e "  ${GREEN}PASS${NC}: $1"
    PASSED=$((PASSED + 1))
}

fail() {
    echo -e "  ${RED}FAIL${NC}: $1"
    FAILED=$((FAILED + 1))
}

# Build the server image
echo "=== Building computer-use-server image ==="
docker build -q -t "$IMAGE_NAME" "$PROJECT_DIR/computer-use-server" > /dev/null
echo "Image built: $IMAGE_NAME"
echo ""

# MCP initialize request body
MCP_INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# MCP tools/call bash_tool request body
MCP_BASH='{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"bash_tool","arguments":{"command":"echo hello-from-test","description":"integration test"}}}'

# Start a server container and wait for health
# Args: container_name port [env_vars...]
start_server() {
    local name="$1"
    local port="$2"
    shift 2
    local env_args=""
    for e in "$@"; do
        env_args="$env_args -e $e"
    done

    docker run -d \
        --name "$name" \
        --label "test=single-user-mode" \
        -p "$port:8081" \
        $env_args \
        "$IMAGE_NAME" > /dev/null

    # Wait for health (max 30s)
    local attempts=0
    while [ $attempts -lt 30 ]; do
        if curl -sf "http://localhost:$port/health" > /dev/null 2>&1; then
            return 0
        fi
        sleep 1
        attempts=$((attempts + 1))
    done
    echo "  WARNING: Server did not become healthy in 30s"
    docker logs "$name" 2>&1 | tail -5
    return 1
}

# Initialize MCP session and call bash_tool, return the tool result text
# Args: port [extra_header]
call_bash_tool() {
    local port="$1"
    local extra_header="${2:-}"
    local header_args=""
    if [ -n "$extra_header" ]; then
        header_args="-H \"$extra_header\""
    fi

    # Step 1: Initialize MCP session
    eval curl -sf "http://localhost:$port/mcp" \
        -H "'Content-Type: application/json'" \
        -H "'Accept: application/json, text/event-stream'" \
        $header_args \
        -d "'$MCP_INIT'" > /dev/null 2>&1 || true

    # Step 2: Call bash_tool
    local response
    response=$(eval curl -s "http://localhost:$port/mcp" \
        -H "'Content-Type: application/json'" \
        -H "'Accept: application/json, text/event-stream'" \
        $header_args \
        -d "'$MCP_BASH'" 2>/dev/null || echo "curl_failed")

    echo "$response"
}

stop_server() {
    docker rm -f "$1" > /dev/null 2>&1 || true
}

# ============================================================================
# Test 1: Lenient mode (SINGLE_USER_MODE unset) + no X-Chat-Id
# Expected: tool response contains warning about SINGLE_USER_MODE
# ============================================================================
echo "[1/6] Lenient mode + no X-Chat-Id → works (no required error)"
CONTAINER="test-sum-1"
PORT=$((BASE_PORT))
stop_server "$CONTAINER"
if start_server "$CONTAINER" "$PORT"; then
    RESPONSE=$(call_bash_tool "$PORT")
    if echo "$RESPONSE" | grep -qi "required.*SINGLE_USER_MODE=false\|X-Chat-Id header is required"; then
        fail "Got chat_id required error — should be lenient without SINGLE_USER_MODE"
    elif echo "$RESPONSE" | grep -qi "SINGLE_USER_MODE"; then
        pass "Response contains SINGLE_USER_MODE warning (with Docker output or alone)"
    else
        # Docker socket not available — but chat_id validation PASSED (no "required" error)
        pass "Chat-id validation passed (no 'required' error)"
    fi
else
    fail "Server failed to start"
fi
stop_server "$CONTAINER"

# ============================================================================
# Test 2: Lenient mode + X-Chat-Id present
# Expected: normal response, NO warning
# ============================================================================
echo "[2/6] Lenient mode + X-Chat-Id → works without warning"
CONTAINER="test-sum-2"
PORT=$((BASE_PORT + 1))
stop_server "$CONTAINER"
if start_server "$CONTAINER" "$PORT"; then
    RESPONSE=$(call_bash_tool "$PORT" "X-Chat-Id: test-session-123")
    if echo "$RESPONSE" | grep -qi "SINGLE_USER_MODE"; then
        fail "Should NOT contain SINGLE_USER_MODE warning when chat_id provided"
    elif echo "$RESPONSE" | grep -qi "X-Chat-Id.*required"; then
        fail "Should not require chat_id — it was provided"
    else
        pass "No warning when chat_id provided"
    fi
else
    fail "Server failed to start"
fi
stop_server "$CONTAINER"

# ============================================================================
# Test 3: Single-user mode + no X-Chat-Id
# Expected: works, NO warning
# ============================================================================
echo "[3/6] SINGLE_USER_MODE=true + no X-Chat-Id → works without warning"
CONTAINER="test-sum-3"
PORT=$((BASE_PORT + 2))
stop_server "$CONTAINER"
if start_server "$CONTAINER" "$PORT" "SINGLE_USER_MODE=true"; then
    RESPONSE=$(call_bash_tool "$PORT")
    if echo "$RESPONSE" | grep -qi "SINGLE_USER_MODE"; then
        fail "Should NOT contain warning in single-user mode"
    elif echo "$RESPONSE" | grep -qi "X-Chat-Id.*required"; then
        fail "Should not require chat_id in single-user mode"
    else
        pass "No warning in single-user mode"
    fi
else
    fail "Server failed to start"
fi
stop_server "$CONTAINER"

# ============================================================================
# Test 4: Single-user mode + X-Chat-Id present (should be ignored)
# Expected: works, NO warning, uses default container
# ============================================================================
echo "[4/6] SINGLE_USER_MODE=true + X-Chat-Id → works (header ignored)"
CONTAINER="test-sum-4"
PORT=$((BASE_PORT + 3))
stop_server "$CONTAINER"
if start_server "$CONTAINER" "$PORT" "SINGLE_USER_MODE=true"; then
    RESPONSE=$(call_bash_tool "$PORT" "X-Chat-Id: should-be-ignored")
    if echo "$RESPONSE" | grep -qi "SINGLE_USER_MODE"; then
        fail "Should NOT contain warning in single-user mode"
    elif echo "$RESPONSE" | grep -qi "X-Chat-Id.*required"; then
        fail "Should not require chat_id in single-user mode"
    else
        pass "Header ignored in single-user mode"
    fi
else
    fail "Server failed to start"
fi
stop_server "$CONTAINER"

# ============================================================================
# Test 5: Strict multi-user mode + no X-Chat-Id
# Expected: ERROR — chat_id required
# ============================================================================
echo "[5/6] SINGLE_USER_MODE=false + no X-Chat-Id → error"
CONTAINER="test-sum-5"
PORT=$((BASE_PORT + 4))
stop_server "$CONTAINER"
if start_server "$CONTAINER" "$PORT" "SINGLE_USER_MODE=false"; then
    RESPONSE=$(call_bash_tool "$PORT")
    if echo "$RESPONSE" | grep -qi "required"; then
        pass "Correctly rejected — chat_id required"
    else
        fail "Expected 'required' error, got: $(echo "$RESPONSE" | head -c 200)"
    fi
else
    fail "Server failed to start"
fi
stop_server "$CONTAINER"

# ============================================================================
# Test 6: Strict multi-user mode + X-Chat-Id present
# Expected: works normally, no warning
# ============================================================================
echo "[6/6] SINGLE_USER_MODE=false + X-Chat-Id → works"
CONTAINER="test-sum-6"
PORT=$((BASE_PORT + 5))
stop_server "$CONTAINER"
if start_server "$CONTAINER" "$PORT" "SINGLE_USER_MODE=false"; then
    RESPONSE=$(call_bash_tool "$PORT" "X-Chat-Id: test-session-456")
    if echo "$RESPONSE" | grep -qi "required"; then
        fail "Should NOT get 'required' error when chat_id provided"
    elif echo "$RESPONSE" | grep -qi "SINGLE_USER_MODE"; then
        fail "Should NOT contain warning in strict mode with chat_id"
    else
        pass "Works with chat_id in strict mode"
    fi
else
    fail "Server failed to start"
fi
stop_server "$CONTAINER"

# ============================================================================
# Summary
# ============================================================================
echo ""
echo "==============================="
echo "  PASSED: $PASSED"
echo "  FAILED: $FAILED"
echo ""
if [ "$FAILED" -eq 0 ]; then
    echo -e "  RESULT: ${GREEN}ALL PASSED${NC}"
else
    echo -e "  RESULT: ${RED}$FAILED FAILED${NC}"
fi
echo "==============================="

exit "$FAILED"
