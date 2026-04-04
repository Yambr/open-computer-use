#!/bin/bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
# Test: No internal/corporate references remain in the codebase.
# Uses patterns from tests/corporate-patterns.txt
# Usage: ./tests/test-no-corporate.sh [project-root]
# Exit code: 0 = clean, 1 = references found

set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
SCRIPT_NAME="$(basename "$0")"
PATTERNS_FILE="$(dirname "$0")/corporate-patterns.txt"
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

FILE_INCLUDES="--include=*.py --include=*.js --include=*.ts --include=*.sh --include=*.yml --include=*.yaml --include=*.md --include=*.json --include=*.html --include=Dockerfile*"
EXCLUDES="--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=__pycache__ --exclude-dir=.claude --exclude=$SCRIPT_NAME --exclude=corporate-patterns.txt"

echo "=== Testing: No corporate references in $ROOT ==="
echo ""

# Read patterns from file (one grep pattern per line, lines starting with # are comments)
if [ ! -f "$PATTERNS_FILE" ]; then
    echo "ERROR: $PATTERNS_FILE not found"
    exit 1
fi

TEST_NUM=0
TOTAL=$(grep -v '^#' "$PATTERNS_FILE" | grep -v '^$' | wc -l | tr -d ' ')

while IFS='|' read -r pattern description; do
    # Skip comments and empty lines
    [[ "$pattern" =~ ^#.*$ ]] && continue
    [[ -z "$pattern" ]] && continue

    TEST_NUM=$((TEST_NUM + 1))
    description="${description:-$pattern}"
    echo "[$TEST_NUM/$TOTAL] $description"

    HITS=$(grep -r $FILE_INCLUDES \
        -l "$pattern" "$ROOT" \
        $EXCLUDES 2>/dev/null || true)
    if [ -z "$HITS" ]; then
        pass "Clean"
    else
        fail "$description found in: $(echo "$HITS" | tr '\n' ' ')"
    fi
    echo ""
done < "$PATTERNS_FILE"

# Additional file-based checks
echo "[+1] No proprietary fonts"
if ls "$ROOT"/fonts/Styrene* 2>/dev/null | head -1 > /dev/null 2>&1; then
    fail "Proprietary font files still present in fonts/"
else
    pass "No proprietary fonts"
fi

echo ""
echo "[+2] No proprietary branding assets"
if find "$ROOT/skills" -type d -name "assets" 2>/dev/null | xargs -I{} find {} -mindepth 1 -maxdepth 1 -type d 2>/dev/null | grep -q .; then
    DIRS=$(find "$ROOT/skills" -type d -name "assets" 2>/dev/null | xargs -I{} find {} -mindepth 1 -maxdepth 1 -type d 2>/dev/null)
    fail "Brand asset directories found: $DIRS"
else
    pass "No branding asset directories"
fi

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
    echo "  RESULT: ALL CLEAN"
    exit 0
fi
