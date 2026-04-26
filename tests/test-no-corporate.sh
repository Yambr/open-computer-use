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

while IFS=$'\t' read -r pattern description; do
    # Skip comments and empty lines.
    # CR PR#76 finding #5: separator changed from '|' to TAB. The previous
    # IFS='|' split on the first literal '|' in the line, which silently
    # truncated grep alternations like 'foo\|bar' to just 'foo\' (a malformed
    # BRE that grep error-swallowed). TAB never appears inside a grep BRE,
    # so alternations are preserved untouched.
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

# Git-history guards: only run when ROOT is a git work tree (skip silently on
# sparse checkouts / tarballs). Both checks scope to the PR range
# (origin/main..HEAD) so they don't flag already-merged history on main.
echo ""
echo "[+3] No cyrillic characters in PR commit messages"
if git -C "$ROOT" rev-parse --git-dir > /dev/null 2>&1; then
    if git -C "$ROOT" rev-parse --verify --quiet origin/main > /dev/null 2>&1; then
        # CR PR#76 finding #7: force UTF-8 locale so awk's [А-Яа-яЁё]
        # character class works under C/POSIX locales (minimal CI containers).
        CYR_HITS=$(git -C "$ROOT" log origin/main..HEAD --pretty=format:'%H%n%B%n===END===' 2>/dev/null | \
            LC_ALL=C.UTF-8 awk -v RS='===END===\n' '
                /[А-Яа-яЁё]/ {
                    split($0, lines, "\n");
                    sha = lines[1];
                    subj = "";
                    for (i = 2; i <= length(lines); i++) {
                        if (lines[i] != "") { subj = lines[i]; break }
                    }
                    if (sha != "") { print substr(sha, 1, 12) "  " subj }
                }
            ' || true)
        if [ -z "$CYR_HITS" ]; then
            pass "No cyrillic in PR commit messages"
        else
            fail "Cyrillic found in commit messages: $CYR_HITS"
        fi
    else
        pass "Skipped (no origin/main ref — detached checkout)"
    fi
else
    pass "Skipped (not a git work tree)"
fi

echo ""
echo "[+4] No private-fork details in PR commit messages"
if git -C "$ROOT" rev-parse --git-dir > /dev/null 2>&1; then
    if git -C "$ROOT" rev-parse --verify --quiet origin/main > /dev/null 2>&1; then
        PRIVATE_RE='files-claude|files_claude|ngyambroskin|openwebui-computer-use-community-1'
        PRIV_HITS=$(git -C "$ROOT" log origin/main..HEAD --pretty=format:'%H%n%B%n===END===' 2>/dev/null | \
            awk -v re="$PRIVATE_RE" -v RS='===END===\n' '
                $0 ~ re {
                    split($0, lines, "\n");
                    sha = lines[1];
                    subj = "";
                    for (i = 2; i <= length(lines); i++) {
                        if (lines[i] != "") { subj = lines[i]; break }
                    }
                    if (sha != "") { print substr(sha, 1, 12) "  " subj }
                }
            ' || true)
        if [ -z "$PRIV_HITS" ]; then
            pass "No private-fork details in PR commit messages"
        else
            fail "Private-fork reference in commit messages: $PRIV_HITS"
        fi
    else
        pass "Skipped (no origin/main ref — detached checkout)"
    fi
else
    pass "Skipped (not a git work tree)"
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
