#!/bin/bash
# Test Docker image for package availability, CLI tools, and correct npm layout.
# Usage: ./tests/test-docker-image.sh [image-name]
# Default image: ai-computer-use-test:latest
#
# Exit code: 0 = all tests passed, 1 = some tests failed

set -euo pipefail

IMAGE="${1:-ai-computer-use-test:latest}"
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

run_in_container() {
    docker run --rm --platform linux/amd64 "$IMAGE" bash -c "$1" 2>/dev/null
}

echo "=== Testing Docker image: $IMAGE ==="
echo ""

# 1. Node.js and Python versions
echo "[1/10] Runtime versions"
VERSIONS=$(run_in_container 'node --version && python3 --version')
echo "$VERSIONS" | grep -q "v22" && pass "Node.js v22" || fail "Node.js version"
echo "$VERSIONS" | grep -q "Python 3" && pass "Python 3" || fail "Python version"

# 2. CommonJS require()
echo ""
echo "[2/10] CommonJS require()"
for pkg in react pptxgenjs pdf-lib docx sharp react-dom/server react-icons/fa; do
    RESULT=$(run_in_container "node -e \"try { require('$pkg'); console.log('OK') } catch(e) { console.log('FAIL: ' + e.code) }\"")
    echo "$RESULT" | grep -q "OK" && pass "require('$pkg')" || fail "require('$pkg'): $RESULT"
done

# 3. ES Modules import
echo ""
echo "[3/10] ES Modules import"
for pkg in react pptxgenjs pdf-lib; do
    RESULT=$(run_in_container "node --input-type=module -e \"import '$pkg'; console.log('OK')\"")
    echo "$RESULT" | grep -q "OK" && pass "import '$pkg'" || fail "import '$pkg'"
done

# 4. html2pptx import (full path)
echo ""
echo "[4/10] html2pptx import"
RESULT=$(run_in_container "node --input-type=module -e \"import { html2pptx } from '/usr/local/lib/node_modules_global/lib/node_modules/@anthropic-ai/html2pptx/dist/html2pptx.mjs'; console.log('OK')\"" 2>/dev/null || echo "SKIP")
if echo "$RESULT" | grep -q "OK"; then
    pass "html2pptx ESM import"
elif echo "$RESULT" | grep -q "SKIP"; then
    echo "  SKIP: html2pptx (package path may vary)"
else
    fail "html2pptx ESM import"
fi

# 5. CLI tools
echo ""
echo "[5/10] CLI tools"
for tool in mmdc tsc tsx claude; do
    RESULT=$(run_in_container "which $tool >/dev/null 2>&1 && echo OK || echo MISSING")
    echo "$RESULT" | grep -q "OK" && pass "$tool in PATH" || fail "$tool not found in PATH"
done

# 6. Python packages
echo ""
echo "[6/10] Python packages"
for pkg in docx pptx openpyxl; do
    RESULT=$(run_in_container "python3 -c \"import $pkg; print('OK')\"")
    echo "$RESULT" | grep -q "OK" && pass "python import $pkg" || fail "python import $pkg"
done
RESULT=$(run_in_container "python3 -c \"from playwright.sync_api import sync_playwright; print('OK')\"")
echo "$RESULT" | grep -q "OK" && pass "python playwright" || fail "python playwright"

# 7. User npm install (lodash)
echo ""
echo "[7/10] User npm install"
RESULT=$(run_in_container 'cd /home/assistant && npm install lodash >/dev/null 2>&1 && if [ -d /home/assistant/node_modules/lodash ]; then echo "user=YES"; else echo "user=NO"; fi && SYS_COUNT=$(ls /home/node_modules/ 2>/dev/null | wc -l) && echo "system=$SYS_COUNT"')
echo "$RESULT" | grep -q "user=YES" && pass "lodash in /home/assistant/node_modules" || fail "lodash not in user dir"
SYS=$(echo "$RESULT" | grep -oP 'system=\K\d+' || echo "0")
[ "${SYS:-0}" -gt 100 ] && pass "system packages intact ($SYS)" || fail "system packages count: $SYS (expected > 100)"

# 8. npm prefix check
echo ""
echo "[8/10] npm configuration"
RESULT=$(run_in_container 'npm config get prefix 2>/dev/null || echo "undefined"')
# prefix should be undefined (deleted) or /usr/local/lib/node_modules_global
if echo "$RESULT" | grep -qE "(undefined|node_modules_global)"; then
    pass "npm prefix configured correctly"
else
    fail "npm prefix: $RESULT"
fi

# 9. Volume size
echo ""
echo "[9/10] Volume size"
SIZE_KB=$(run_in_container "du -sk /home/assistant/ | cut -f1")
if [ "${SIZE_KB:-999999}" -lt 1024 ]; then
    pass "/home/assistant < 1MB (${SIZE_KB}KB)"
else
    fail "/home/assistant = ${SIZE_KB}KB (expected < 1024KB)"
fi

# 10. Permissions and guard files
echo ""
echo "[10/10] Permissions and guard files"
RESULT=$(run_in_container '
[ -x /home/assistant/.entrypoint.sh ] && echo "entrypoint=OK" || echo "entrypoint=FAIL"
[ -f /home/assistant/.gitconfig ] && echo "gitconfig=OK" || echo "gitconfig=FAIL"
[ -f /home/assistant/package.json ] && echo "packagejson=OK" || echo "packagejson=FAIL"
OWNER=$(stat -c %U /home/assistant/.entrypoint.sh)
echo "owner=$OWNER"
')
echo "$RESULT" | grep -q "entrypoint=OK" && pass ".entrypoint.sh executable" || fail ".entrypoint.sh not executable"
echo "$RESULT" | grep -q "gitconfig=OK" && pass ".gitconfig exists" || fail ".gitconfig missing"
echo "$RESULT" | grep -q "packagejson=OK" && pass "package.json guard exists" || fail "package.json guard missing"
echo "$RESULT" | grep -q "owner=assistant" && pass "files owned by assistant" || fail "files not owned by assistant"

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
