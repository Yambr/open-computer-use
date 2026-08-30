#!/bin/bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
# Test: the baked OpenWebUI system prompt and the shipped skill set agree.
#
# openwebui/system_prompt.txt is the static prompt init.sh bakes into the
# DEFAULT_MODEL_PARAMS.system record. It tells the model to `view`
# /mnt/skills/public/<name>/SKILL.md before doing a task. The guest image
# mounts skills/public/<name>/ at /mnt/skills/public/<name>/. If the prompt
# names a skill the repo does not carry, the model follows a dead path
# (view a missing SKILL.md) -- a silent parity regression. This guards both
# directions plus the owner exclusions (sub_agent, browser tool).
#
# Static (no image, no network): reads the prompt file and the skills/public
# tree only. Runs in the same CI step as test-project-structure.sh.
#
# Usage: ./tests/test-system-prompt-skills-contract.sh [project-root]
# Exit code: 0 = contract holds, 1 = drift found

set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
PROMPT="$ROOT/openwebui/system_prompt.txt"
SKILLS_DIR="$ROOT/skills/public"
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

# Skills the owner excluded from the assembled next/v1 app. They may exist in
# skills/public (the PoC ships them) but MUST NOT be advertised in the prompt
# nor declared as a tool.
EXCLUDED_SKILLS="sub-agent"
# Tools that MUST NOT appear in the <computer_use> declaration.
EXCLUDED_TOOLS="sub_agent computer"

echo "=== Testing: system prompt <-> skills contract ==="
echo ""

# 0. Preconditions.
echo "[1/4] Preconditions"
if [ -f "$PROMPT" ]; then
    pass "openwebui/system_prompt.txt exists"
else
    fail "openwebui/system_prompt.txt missing -- nothing to check"
    echo -e "\nFAILURES:${FAILURES}"
    exit 1
fi
if [ -d "$SKILLS_DIR" ]; then
    pass "skills/public/ exists"
else
    fail "skills/public/ missing -- nothing to check against"
    echo -e "\nFAILURES:${FAILURES}"
    exit 1
fi

# 1. Every skill the prompt points at resolves to a real SKILL.md in the repo.
echo ""
echo "[2/4] Prompt-referenced skills exist in skills/public/"
PROMPT_SKILLS=$(grep -oE "/mnt/skills/public/[a-z0-9-]+/SKILL\.md" "$PROMPT" \
    | sed -E 's#/mnt/skills/public/([a-z0-9-]+)/SKILL\.md#\1#' | sort -u)
if [ -z "$PROMPT_SKILLS" ]; then
    fail "prompt references ZERO /mnt/skills/public/*/SKILL.md paths (block missing?)"
else
    while IFS= read -r skill; do
        [ -z "$skill" ] && continue
        if [ -f "$SKILLS_DIR/$skill/SKILL.md" ]; then
            pass "prompt skill '$skill' -> skills/public/$skill/SKILL.md"
        else
            fail "prompt names '$skill' but skills/public/$skill/SKILL.md is absent (dead view path)"
        fi
    done <<< "$PROMPT_SKILLS"
fi

# 2. Owner-excluded skills are NOT advertised in the prompt.
echo ""
echo "[3/4] Owner-excluded skills stay unadvertised"
for skill in $EXCLUDED_SKILLS; do
    if grep -q "/mnt/skills/public/$skill/SKILL\.md" "$PROMPT"; then
        fail "excluded skill '$skill' is advertised in the prompt (D7 regression)"
    else
        pass "excluded skill '$skill' not advertised"
    fi
done

# 3. Owner-excluded tools are NOT declared in the <computer_use> block.
echo ""
echo "[4/4] Owner-excluded tools stay undeclared"
# Extract the <computer_use> section; if absent, that itself is a failure.
if grep -q "<computer_use>" "$PROMPT"; then
    CU_BLOCK=$(awk '/<computer_use>/{f=1} f{print} /<\/computer_use>/{f=0}' "$PROMPT")
    for tool in $EXCLUDED_TOOLS; do
        # Match the tool as a declared name, e.g. name="sub_agent" or <sub_agent>.
        if printf '%s' "$CU_BLOCK" | grep -qE "\"$tool\"|<$tool[ >]|>$tool</"; then
            fail "excluded tool '$tool' declared in <computer_use> (regression)"
        else
            pass "excluded tool '$tool' not declared"
        fi
    done
else
    fail "<computer_use> tool declaration block missing from prompt"
fi

echo ""
echo "=== Results: $PASSED passed, $FAILED failed ==="
if [ "$FAILED" -gt 0 ]; then
    echo -e "FAILURES:${FAILURES}"
    exit 1
fi
exit 0
