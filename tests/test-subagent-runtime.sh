#!/bin/bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
#
# Umbrella runner for all sub-agent runtime tests (Phase 1 — Plans 01-03..01-06,
# Phase 2 — Plan 02-02 removes the deprecation step, Plan 02-06 adds audit step).
#
# Invokes in sequence:
#   1. pytest tests/test-subagent-cli-surface.py          (per-CLI docstring assertions)
#   2. pytest tests/test-opencode-error-mapping.py        (opencode error event mapping)
#   3. pytest tests/test_subagent_docstring.py            (docstring helper unit tests)
#   4. pytest tests/test-default-model-resolution.py      (D-08/D-09 resolution order)
#   5. bash  tests/test-list-subagent-models.sh           (script invocation per CLI)
#   6. bash  tests/test-skill-no-hardcoded-models.sh      (D-16 skill audit)
#
# Exit code: 0 = all sub-tests passed, 1 = one or more failed.
# Usage: bash tests/test-subagent-runtime.sh

set -uo pipefail

TEST_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$TEST_DIR/.." && pwd)"

PASSED=0
FAILED=0
FAILURES=""

pass() {
    PASSED=$((PASSED + 1))
    echo "  PASS: $1"
}

fail() {
    FAILED=$((FAILED + 1))
    FAILURES="${FAILURES}\n  - $1"
    echo "  FAIL: $1"
}

run_pytest() {
    local label="$1"
    local testfile="$2"
    set +e
    python3 -m pytest "$testfile" -x --tb=short -q 2>&1
    local rc=$?
    set -e
    if [ "$rc" -eq 0 ]; then
        pass "$label"
    else
        fail "$label (pytest exit $rc)"
    fi
}

run_bash() {
    local label="$1"
    local script="$2"
    set +e
    bash "$script" 2>&1
    local rc=$?
    set -e
    if [ "$rc" -eq 0 ]; then
        pass "$label"
    else
        fail "$label (exit $rc)"
    fi
}

echo "=== Sub-agent runtime tests ==="
echo ""

echo "[1/6] Per-CLI docstring surface (test-subagent-cli-surface.py)"
run_pytest "test-subagent-cli-surface.py" "$TEST_DIR/test-subagent-cli-surface.py"

echo ""
echo "[2/6] opencode error event mapping (test-opencode-error-mapping.py)"
run_pytest "test-opencode-error-mapping.py" "$TEST_DIR/test-opencode-error-mapping.py"

echo ""
echo "[3/6] Sub-agent docstring helper unit tests (test_subagent_docstring.py)"
run_pytest "test_subagent_docstring.py" "$TEST_DIR/test_subagent_docstring.py"

echo ""
echo "[4/6] Default model resolution order (test-default-model-resolution.py)"
run_pytest "test-default-model-resolution.py" "$TEST_DIR/test-default-model-resolution.py"

echo ""
echo "[5/6] list-subagent-models script invocation (test-list-subagent-models.sh)"
run_bash "test-list-subagent-models.sh" "$TEST_DIR/test-list-subagent-models.sh"

echo ""
echo "[6/6] Skill no-hardcoded-models audit (test-skill-no-hardcoded-models.sh)"
run_bash "test-skill-no-hardcoded-models.sh" "$TEST_DIR/test-skill-no-hardcoded-models.sh"

# Summary
echo ""
echo "==============================="
echo "  PASSED: $PASSED"
echo "  FAILED: $FAILED"
if [ "$FAILED" -gt 0 ]; then
    echo ""
    echo "  Failures:"
    echo -e "$FAILURES"
    echo ""
    echo "  RESULT: FAIL"
    exit 1
else
    echo ""
    echo "  RESULT: ALL TESTS PASSED"
    exit 0
fi
