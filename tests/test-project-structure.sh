#!/bin/bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
# Test: Project structure matches open-computer-use layout.
# Verifies correct directory structure after migration.
# Usage: ./tests/test-project-structure.sh [project-root]
# Exit code: 0 = correct structure, 1 = issues found

set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
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

echo "=== Testing: Project structure in $ROOT ==="
echo ""

# 1. computer-use-server/ exists (renamed from file-server)
echo "[1/12] computer-use-server/"
if [ -d "$ROOT/computer-use-server" ]; then
    pass "computer-use-server/ directory exists"
else
    fail "computer-use-server/ directory missing"
fi

# 2. computer-use-server has key files
echo ""
echo "[2/12] computer-use-server key files"
for f in Dockerfile app.py mcp_tools.py docker_manager.py requirements.txt; do
    if [ -f "$ROOT/computer-use-server/$f" ]; then
        pass "computer-use-server/$f"
    else
        fail "computer-use-server/$f missing"
    fi
done

# 3. openwebui/ directory structure
echo ""
echo "[3/12] openwebui/ directory"
if [ -d "$ROOT/openwebui" ]; then
    pass "openwebui/ directory exists"
else
    fail "openwebui/ directory missing"
fi

# 4. openwebui/tools/
echo ""
echo "[4/12] openwebui/tools/"
if [ -f "$ROOT/openwebui/tools/computer_use_tools.py" ]; then
    pass "openwebui/tools/computer_use_tools.py"
else
    fail "openwebui/tools/computer_use_tools.py missing"
fi

# 5. openwebui/functions/
echo ""
echo "[5/12] openwebui/functions/"
if [ -f "$ROOT/openwebui/functions/computer_link_filter.py" ]; then
    pass "openwebui/functions/computer_link_filter.py"
else
    fail "openwebui/functions/computer_link_filter.py missing"
fi

# 6. openwebui/patches/
echo ""
echo "[6/12] openwebui/patches/"
if [ -d "$ROOT/openwebui/patches" ]; then
    PATCH_COUNT=$(ls "$ROOT/openwebui/patches"/fix_*.py 2>/dev/null | wc -l)
    if [ "$PATCH_COUNT" -ge 1 ]; then
        pass "openwebui/patches/ has $PATCH_COUNT patches"
    else
        fail "openwebui/patches/ has no patches"
    fi
else
    fail "openwebui/patches/ directory missing"
fi

# 7. openwebui/Dockerfile (for patching base Open WebUI)
echo ""
echo "[7/12] openwebui/Dockerfile"
if [ -f "$ROOT/openwebui/Dockerfile" ]; then
    if grep -q "open-webui" "$ROOT/openwebui/Dockerfile"; then
        pass "openwebui/Dockerfile references open-webui base image"
    else
        fail "openwebui/Dockerfile doesn't reference open-webui base image"
    fi
else
    fail "openwebui/Dockerfile missing"
fi

# 8. Old directories should NOT exist
echo ""
echo "[8/12] Old directories removed"
for d in file-server openwebui-tools openwebui-functions; do
    if [ -d "$ROOT/$d" ]; then
        fail "Old directory $d/ still exists (should be migrated)"
    else
        pass "$d/ removed"
    fi
done

# 9. docker-compose.yml has required services
echo ""
echo "[9/12] docker-compose.yml services"
if [ -f "$ROOT/docker-compose.yml" ]; then
    for svc in computer-use-server workspace; do
        if grep -q "$svc" "$ROOT/docker-compose.yml"; then
            pass "docker-compose has $svc service"
        else
            fail "docker-compose missing $svc service"
        fi
    done
else
    fail "docker-compose.yml missing"
fi

# 10. .env.example exists and has key vars
echo ""
echo "[10/12] .env.example"
if [ -f "$ROOT/.env.example" ]; then
    for var in OPENAI_API_KEY POSTGRES_PASSWORD MCP_API_KEY DOCKER_IMAGE; do
        if grep -q "$var" "$ROOT/.env.example"; then
            pass ".env.example has $var"
        else
            fail ".env.example missing $var"
        fi
    done
else
    fail ".env.example missing"
fi

# 11. Root Dockerfile exists
echo ""
echo "[11/12] Root Dockerfile (sandbox image)"
if [ -f "$ROOT/Dockerfile" ]; then
    pass "Root Dockerfile exists"
else
    fail "Root Dockerfile missing"
fi

# 12. No werf.yaml (not needed for GitHub)
echo ""
echo "[12/13] No werf.yaml"
if [ -f "$ROOT/werf.yaml" ]; then
    fail "werf.yaml should not exist in community version"
else
    pass "No werf.yaml"
fi

# 13. Sub-agent runtime tests (Phase 1)
echo ""
echo "[13/13] Sub-agent runtime tests (Phase 1)"
if bash "$(dirname "$0")/test-subagent-runtime.sh" >/tmp/subagent-runtime.log 2>&1; then
    pass "test-subagent-runtime.sh exits 0"
else
    fail "test-subagent-runtime.sh exits non-zero — see /tmp/subagent-runtime.log"
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
    echo "  RESULT: STRUCTURE OK"
    exit 0
fi
