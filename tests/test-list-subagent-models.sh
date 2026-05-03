#!/bin/bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
#
# Test computer-use-server/bin/list-subagent-models invocation for each
# SUBAGENT_CLI value.
#
# When the CLI is NOT on the host $PATH:
#   - Expects exit code 2
#   - Expects structured JSON on stderr containing "cli" and "hint" keys
#
# When the CLI IS on the host $PATH:
#   - Expects exit code 0
#   - Expects valid JSON on stdout with "cli" and non-empty "models" array
#
# Usage: bash tests/test-list-subagent-models.sh
# Exit code: 0 = all assertions passed, 1 = some failed

set -euo pipefail

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

SCRIPT="$(dirname "$0")/../computer-use-server/bin/list-subagent-models"

echo "=== Testing: list-subagent-models script ==="
echo ""

# 1. Script exists and is executable
echo "[1/4] Script presence and permissions"
if [ -f "$SCRIPT" ]; then
    pass "list-subagent-models script exists"
else
    fail "list-subagent-models script not found at $SCRIPT"
    echo ""
    echo "==============================="
    echo "  PASSED: $PASSED"
    echo "  FAILED: $FAILED"
    echo "  RESULT: FAIL (script missing)"
    exit 1
fi

if [ -x "$SCRIPT" ]; then
    pass "list-subagent-models is executable"
else
    fail "list-subagent-models is not executable"
fi

# 2-4. Per-CLI invocation tests
for cli in claude opencode codex; do
    echo ""
    echo "[CLI: $cli]"

    set +e
    SUBAGENT_CLI="$cli" "$SCRIPT" >/tmp/lsm.stdout 2>/tmp/lsm.stderr
    rc=$?
    set -e

    if command -v "$cli" >/dev/null 2>&1; then
        # CLI is present on host PATH — expect success
        if [ "$rc" -eq 0 ]; then
            pass "$cli: exit code 0 (CLI present)"
        else
            fail "$cli: expected exit 0 but got $rc (CLI is on PATH)"
        fi
        # Validate stdout JSON contains "cli" and non-empty "models"
        if python3 -c "
import json, sys
try:
    d = json.load(open('/tmp/lsm.stdout'))
    assert d.get('cli') == '$cli', f'cli field mismatch: {d.get(\"cli\")!r}'
    assert isinstance(d.get('models'), list), 'models is not a list'
    assert len(d['models']) > 0, 'models list is empty'
    sys.exit(0)
except Exception as e:
    print(f'Validation error: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; then
            pass "$cli: stdout is valid JSON with cli='$cli' and non-empty models"
        else
            STDOUT_PREVIEW=$(head -c 200 /tmp/lsm.stdout 2>/dev/null || echo "(empty)")
            fail "$cli: stdout JSON validation failed (got: $STDOUT_PREVIEW)"
        fi
    else
        # CLI is NOT on host PATH — expect exit 2 + structured JSON on stderr
        if [ "$rc" -eq 2 ]; then
            pass "$cli: exit code 2 (CLI absent — expected)"
        else
            fail "$cli: expected exit 2 but got $rc (CLI not on PATH)"
        fi
        # Validate stderr JSON contains "cli" and "hint" keys
        if python3 -c "
import json, sys
try:
    d = json.load(open('/tmp/lsm.stderr'))
    assert d.get('cli') == '$cli', f'cli field mismatch: {d.get(\"cli\")!r}'
    assert 'hint' in d, 'hint key missing from error JSON'
    sys.exit(0)
except Exception as e:
    print(f'Validation error: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; then
            pass "$cli: stderr is valid JSON with cli='$cli' and 'hint' key"
        else
            STDERR_PREVIEW=$(head -c 200 /tmp/lsm.stderr 2>/dev/null || echo "(empty)")
            fail "$cli: stderr JSON validation failed (got: $STDERR_PREVIEW)"
        fi
    fi
done

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
