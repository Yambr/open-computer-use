#!/bin/bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
#
# Phase 2 D-16: enforces no-hardcoded-model-names invariant for sub-agent skill files.
# Greps for forbidden tokens; lines wrapped in <!-- canonical-example -->...<!-- /canonical-example -->
# markers (or otherwise containing "canonical-example") are excluded — those are
# narrative examples that legitimately need to name a model (e.g., claude's `sonnet` baseline).
# Lines that mention "list-subagent-models" are also excluded (the script name itself
# contains "models" but does not encode a hardcoded model id).

set -uo pipefail

PASSED=0; FAILED=0; FAILURES=""

pass() { PASSED=$((PASSED + 1)); echo "  PASS: $1"; }
fail() { FAILED=$((FAILED + 1)); FAILURES="${FAILURES}\n  - $1"; echo "  FAIL: $1"; }

FORBIDDEN_PATTERN='sonnet|opus|haiku|gpt-5-codex|claude-sonnet-4-6|qwen-3-coder|claude-opus|claude-haiku'
FILES=(
    "skills/public/sub-agent/SKILL.md"
    "skills/public/sub-agent/references/usage.md"
)

# Resolve repo root: the script may be invoked from any directory.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Skill audit: no hardcoded model names ==="
for f in "${FILES[@]}"; do
    fpath="$REPO_ROOT/$f"
    if [ ! -f "$fpath" ]; then
        fail "$f does not exist"
        continue
    fi
    # Lines containing forbidden tokens, EXCLUDING marker-tagged lines
    # and lines mentioning list-subagent-models.
    hits=$(grep -nE "$FORBIDDEN_PATTERN" "$fpath" \
            | grep -v 'canonical-example' \
            | grep -v 'list-subagent-models' \
            || true)
    if [ -z "$hits" ]; then
        pass "$f has no unmarked hardcoded model names"
    else
        fail "$f contains unmarked hardcoded model names:"
        echo "$hits" | sed 's/^/      /'
    fi
done

echo ""
echo "==============================="
echo "  PASSED: $PASSED  FAILED: $FAILED"
if [ "$FAILED" -gt 0 ]; then
    echo ""
    echo "  Failures:"
    echo -e "$FAILURES"
    echo "  RESULT: FAIL"
    exit 1
else
    echo "  RESULT: ALL TESTS PASSED"
    exit 0
fi
