#!/bin/bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
#
# Test computer-use-server/bin/list-subagent-models.
#
# Phase 2 behavior (default host-friendly mode):
#   - claude: static alias list, always exits 0
#   - opencode/codex: reads cli-defaults/<cli>.json (or *_CONFIG_EXTRA env);
#     does NOT shell out to the CLI binary by default
#
# --inside-container flag (Phase 1 behavior preserved):
#   - opencode/codex absent from PATH -> exit 2 + structured stderr JSON
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
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLI_DEFAULTS_DIR="$REPO_ROOT/computer-use-server/cli-defaults"

echo "=== Testing: list-subagent-models script ==="
echo ""

# ---------------------------------------------------------------------------
# 1. Script presence and permissions
# ---------------------------------------------------------------------------
echo "[1] Script presence and permissions"
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

# ---------------------------------------------------------------------------
# 2. --help flag
# ---------------------------------------------------------------------------
echo ""
echo "[2] --help flag"
if python3 "$SCRIPT" --help 2>&1 | grep -q '\-\-inside-container'; then
    pass "--help shows --inside-container flag"
else
    fail "--help does not mention --inside-container"
fi

# ---------------------------------------------------------------------------
# 3. invalid SUBAGENT_CLI
# ---------------------------------------------------------------------------
echo ""
echo "[3] Invalid SUBAGENT_CLI"
set +e
SUBAGENT_CLI=bogus python3 "$SCRIPT" >/tmp/lsm.stdout 2>/tmp/lsm.stderr
rc=$?
set -e
if [ "$rc" -eq 2 ]; then
    pass "invalid SUBAGENT_CLI exits 2"
else
    fail "invalid SUBAGENT_CLI: expected exit 2 but got $rc"
fi
if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stderr'))
assert 'hint' in d, 'hint key missing'
sys.exit(0)
" 2>/dev/null; then
    pass "invalid SUBAGENT_CLI: structured stderr JSON with hint"
else
    fail "invalid SUBAGENT_CLI: stderr not valid structured JSON (got: $(cat /tmp/lsm.stderr | head -c 200))"
fi

# ---------------------------------------------------------------------------
# 4. claude — always succeeds with static alias list (unchanged from Phase 1)
# ---------------------------------------------------------------------------
echo ""
echo "[4] claude — static aliases"
set +e
SUBAGENT_CLI=claude python3 "$SCRIPT" >/tmp/lsm.stdout 2>/tmp/lsm.stderr
rc=$?
set -e
if [ "$rc" -eq 0 ]; then
    pass "claude: exit code 0"
else
    fail "claude: expected exit 0 but got $rc (stderr: $(cat /tmp/lsm.stderr | head -c 200))"
fi
if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stdout'))
assert d.get('cli') == 'claude', f'cli={d.get(\"cli\")!r}'
assert isinstance(d.get('models'), list) and len(d['models']) > 0, 'models not non-empty list'
assert d.get('default_model') == 'sonnet', f'default_model={d.get(\"default_model\")!r}'
assert d.get('source') == 'alias_map', f'source={d.get(\"source\")!r}'
assert isinstance(d.get('aliases'), dict), 'aliases must be a dict'
sys.exit(0)
" 2>/dev/null; then
    pass "claude: valid JSON with cli=claude, non-empty models, source=alias_map, aliases={}"
else
    STDOUT_PREVIEW=$(head -c 300 /tmp/lsm.stdout 2>/dev/null || echo "(empty)")
    fail "claude: stdout JSON validation failed (got: $STDOUT_PREVIEW)"
fi

# ---------------------------------------------------------------------------
# 5. Host-mode tests using tmpdir with canonical cli-defaults files
# ---------------------------------------------------------------------------
echo ""
echo "[5] Host-mode: opencode reads canonical cli-defaults file"
TMPDIR_HOSTS=$(mktemp -d)
trap 'rm -rf "$TMPDIR_HOSTS"' EXIT

cp "$CLI_DEFAULTS_DIR/opencode.json" "$TMPDIR_HOSTS/"
cp "$CLI_DEFAULTS_DIR/codex.json"    "$TMPDIR_HOSTS/"

set +e
SUBAGENT_CLI=opencode LIST_SUBAGENT_CLI_DEFAULTS_DIR="$TMPDIR_HOSTS" python3 "$SCRIPT" >/tmp/lsm.stdout 2>/tmp/lsm.stderr
rc=$?
set -e
if [ "$rc" -eq 0 ]; then
    pass "opencode host-mode: exit code 0"
else
    fail "opencode host-mode: expected exit 0 but got $rc (stderr: $(cat /tmp/lsm.stderr | head -c 300))"
fi
if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stdout'))
assert d.get('cli') == 'opencode', f'cli={d.get(\"cli\")!r}'
assert d.get('default_model') == 'anthropic/claude-sonnet-4-6', f'default_model={d.get(\"default_model\")!r}'
assert isinstance(d.get('aliases'), dict), 'aliases not a dict'
assert isinstance(d.get('models'), list), 'models not a list'
sys.exit(0)
" 2>/dev/null; then
    pass "opencode host-mode: valid JSON with correct default_model and aliases key"
else
    STDOUT_PREVIEW=$(head -c 300 /tmp/lsm.stdout 2>/dev/null || echo "(empty)")
    fail "opencode host-mode: stdout JSON validation failed (got: $STDOUT_PREVIEW)"
fi

# ---------------------------------------------------------------------------
# 6. opencode OPENCODE_CONFIG_EXTRA env override wins
# ---------------------------------------------------------------------------
echo ""
echo "[6] opencode OPENCODE_CONFIG_EXTRA env override"
set +e
SUBAGENT_CLI=opencode OPENCODE_CONFIG_EXTRA='{"model":"x/y","provider":{"x":{}}}' LIST_SUBAGENT_CLI_DEFAULTS_DIR="$TMPDIR_HOSTS" python3 "$SCRIPT" >/tmp/lsm.stdout 2>/tmp/lsm.stderr
rc=$?
set -e
if [ "$rc" -eq 0 ]; then
    pass "opencode OPENCODE_CONFIG_EXTRA: exit code 0"
else
    fail "opencode OPENCODE_CONFIG_EXTRA: expected exit 0 but got $rc"
fi
if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stdout'))
assert d.get('default_model') == 'x/y', f'default_model={d.get(\"default_model\")!r}'
assert d.get('source') == 'OPENCODE_CONFIG_EXTRA env', f'source={d.get(\"source\")!r}'
sys.exit(0)
" 2>/dev/null; then
    pass "opencode OPENCODE_CONFIG_EXTRA: default_model=x/y, source=OPENCODE_CONFIG_EXTRA env"
else
    STDOUT_PREVIEW=$(head -c 300 /tmp/lsm.stdout 2>/dev/null || echo "(empty)")
    fail "opencode OPENCODE_CONFIG_EXTRA: validation failed (got: $STDOUT_PREVIEW)"
fi

# ---------------------------------------------------------------------------
# 7. opencode malformed OPENCODE_CONFIG_EXTRA exits non-zero with structured error
# ---------------------------------------------------------------------------
echo ""
echo "[7] opencode malformed OPENCODE_CONFIG_EXTRA"
set +e
SUBAGENT_CLI=opencode OPENCODE_CONFIG_EXTRA='not-json' python3 "$SCRIPT" >/tmp/lsm.stdout 2>/tmp/lsm.stderr
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
    pass "opencode malformed env: exit non-zero (got $rc)"
else
    fail "opencode malformed env: expected non-zero exit but got 0"
fi
if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stderr'))
assert 'OPENCODE_CONFIG_EXTRA is not valid JSON' in d.get('error',''), f'error={d.get(\"error\")!r}'
assert 'hint' in d, 'hint key missing'
sys.exit(0)
" 2>/dev/null; then
    pass "opencode malformed env: structured stderr with correct error message"
else
    STDERR_PREVIEW=$(head -c 300 /tmp/lsm.stderr 2>/dev/null || echo "(empty)")
    fail "opencode malformed env: stderr validation failed (got: $STDERR_PREVIEW)"
fi

# ---------------------------------------------------------------------------
# 8. OPENCODE_MODEL_ALIASES surfaced in aliases output
# ---------------------------------------------------------------------------
echo ""
echo "[8] OPENCODE_MODEL_ALIASES surfaced in aliases"
set +e
SUBAGENT_CLI=opencode OPENCODE_MODEL_ALIASES='{"fast":"openrouter/qwen/qwen-3-coder"}' LIST_SUBAGENT_CLI_DEFAULTS_DIR="$TMPDIR_HOSTS" python3 "$SCRIPT" >/tmp/lsm.stdout 2>/tmp/lsm.stderr
rc=$?
set -e
if [ "$rc" -eq 0 ]; then
    pass "OPENCODE_MODEL_ALIASES: exit code 0"
else
    fail "OPENCODE_MODEL_ALIASES: expected exit 0 but got $rc"
fi
if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stdout'))
assert d.get('aliases') == {'fast': 'openrouter/qwen/qwen-3-coder'}, f'aliases={d.get(\"aliases\")!r}'
sys.exit(0)
" 2>/dev/null; then
    pass "OPENCODE_MODEL_ALIASES: aliases dict correct in output"
else
    STDOUT_PREVIEW=$(head -c 300 /tmp/lsm.stdout 2>/dev/null || echo "(empty)")
    fail "OPENCODE_MODEL_ALIASES: validation failed (got: $STDOUT_PREVIEW)"
fi

# ---------------------------------------------------------------------------
# 9. codex host-mode reads canonical file (empty providers → empty models)
# ---------------------------------------------------------------------------
echo ""
echo "[9] codex host-mode reads canonical file"
set +e
SUBAGENT_CLI=codex LIST_SUBAGENT_CLI_DEFAULTS_DIR="$TMPDIR_HOSTS" python3 "$SCRIPT" >/tmp/lsm.stdout 2>/tmp/lsm.stderr
rc=$?
set -e
if [ "$rc" -eq 0 ]; then
    pass "codex host-mode: exit code 0"
else
    fail "codex host-mode: expected exit 0 but got $rc (stderr: $(cat /tmp/lsm.stderr | head -c 300))"
fi
if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stdout'))
assert d.get('cli') == 'codex', f'cli={d.get(\"cli\")!r}'
assert isinstance(d.get('models'), list), 'models not a list'
# canonical codex.json has null default_model and empty providers
dm = d.get('default_model')
assert dm is None or isinstance(dm, str), f'default_model type unexpected: {dm!r}'
sys.exit(0)
" 2>/dev/null; then
    pass "codex host-mode: valid JSON with cli=codex"
else
    STDOUT_PREVIEW=$(head -c 300 /tmp/lsm.stdout 2>/dev/null || echo "(empty)")
    fail "codex host-mode: stdout JSON validation failed (got: $STDOUT_PREVIEW)"
fi

# ---------------------------------------------------------------------------
# 10. codex CODEX_CONFIG_EXTRA TOML override
# ---------------------------------------------------------------------------
echo ""
echo "[10] codex CODEX_CONFIG_EXTRA TOML override"
set +e
SUBAGENT_CLI=codex CODEX_CONFIG_EXTRA='model = "gpt-5"' python3 "$SCRIPT" >/tmp/lsm.stdout 2>/tmp/lsm.stderr
rc=$?
set -e
if [ "$rc" -eq 0 ]; then
    pass "codex CODEX_CONFIG_EXTRA TOML: exit code 0"
else
    fail "codex CODEX_CONFIG_EXTRA TOML: expected exit 0 but got $rc (stderr: $(cat /tmp/lsm.stderr | head -c 300))"
fi
if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stdout'))
assert d.get('default_model') == 'gpt-5', f'default_model={d.get(\"default_model\")!r}'
assert d.get('source') == 'CODEX_CONFIG_EXTRA env', f'source={d.get(\"source\")!r}'
sys.exit(0)
" 2>/dev/null; then
    pass "codex CODEX_CONFIG_EXTRA TOML: default_model=gpt-5, source=CODEX_CONFIG_EXTRA env"
else
    STDOUT_PREVIEW=$(head -c 300 /tmp/lsm.stdout 2>/dev/null || echo "(empty)")
    fail "codex CODEX_CONFIG_EXTRA TOML: validation failed (got: $STDOUT_PREVIEW)"
fi

# ---------------------------------------------------------------------------
# 11. --inside-container flag: opencode absent from PATH → exit 2 + structured error
# ---------------------------------------------------------------------------
echo ""
echo "[11] --inside-container: opencode absent from PATH"
if ! command -v opencode >/dev/null 2>&1; then
    set +e
    SUBAGENT_CLI=opencode python3 "$SCRIPT" --inside-container >/tmp/lsm.stdout 2>/tmp/lsm.stderr
    rc=$?
    set -e
    if [ "$rc" -eq 2 ]; then
        pass "--inside-container opencode absent: exit code 2"
    else
        fail "--inside-container opencode absent: expected exit 2 but got $rc"
    fi
    if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stderr'))
assert d.get('cli') == 'opencode', f'cli={d.get(\"cli\")!r}'
assert 'hint' in d, 'hint key missing'
sys.exit(0)
" 2>/dev/null; then
        pass "--inside-container opencode absent: structured stderr JSON with cli+hint"
    else
        STDERR_PREVIEW=$(head -c 300 /tmp/lsm.stderr 2>/dev/null || echo "(empty)")
        fail "--inside-container opencode absent: stderr validation failed (got: $STDERR_PREVIEW)"
    fi
else
    pass "--inside-container opencode absent: SKIP (opencode found on PATH)"
fi

# ---------------------------------------------------------------------------
# 12. --inside-container flag: codex absent from PATH → exit 2 + structured error
# ---------------------------------------------------------------------------
echo ""
echo "[12] --inside-container: codex absent from PATH"
if ! command -v codex >/dev/null 2>&1; then
    set +e
    SUBAGENT_CLI=codex python3 "$SCRIPT" --inside-container >/tmp/lsm.stdout 2>/tmp/lsm.stderr
    rc=$?
    set -e
    if [ "$rc" -eq 2 ]; then
        pass "--inside-container codex absent: exit code 2"
    else
        fail "--inside-container codex absent: expected exit 2 but got $rc"
    fi
    if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stderr'))
assert d.get('cli') == 'codex', f'cli={d.get(\"cli\")!r}'
assert 'hint' in d, 'hint key missing'
sys.exit(0)
" 2>/dev/null; then
        pass "--inside-container codex absent: structured stderr JSON with cli+hint"
    else
        STDERR_PREVIEW=$(head -c 300 /tmp/lsm.stderr 2>/dev/null || echo "(empty)")
        fail "--inside-container codex absent: stderr validation failed (got: $STDERR_PREVIEW)"
    fi
else
    pass "--inside-container codex absent: SKIP (codex found on PATH)"
fi

# ---------------------------------------------------------------------------
# 13. opencode / codex host-mode: missing cli-defaults file → exit 3 + structured error
# ---------------------------------------------------------------------------
echo ""
echo "[13] opencode host-mode: missing cli-defaults file → exit 3"
EMPTY_TMPDIR=$(mktemp -d)
trap 'rm -rf "$EMPTY_TMPDIR"' EXIT
set +e
SUBAGENT_CLI=opencode LIST_SUBAGENT_CLI_DEFAULTS_DIR="$EMPTY_TMPDIR" python3 "$SCRIPT" >/tmp/lsm.stdout 2>/tmp/lsm.stderr
rc=$?
set -e
# Only applies if repo-local fallback also doesn't exist for this invocation;
# repo-local path will be tried last. If the repo itself has the file, this
# test skips gracefully.
if [ "$rc" -eq 3 ]; then
    pass "opencode missing file: exit code 3"
    if python3 -c "
import json, sys
d = json.load(open('/tmp/lsm.stderr'))
assert 'hint' in d, 'hint key missing'
sys.exit(0)
" 2>/dev/null; then
        pass "opencode missing file: structured stderr JSON"
    else
        STDERR_PREVIEW=$(head -c 300 /tmp/lsm.stderr 2>/dev/null || echo "(empty)")
        fail "opencode missing file: stderr JSON invalid (got: $STDERR_PREVIEW)"
    fi
elif [ "$rc" -eq 0 ]; then
    pass "opencode missing file: SKIP (repo-local fallback found; expected in dev environment)"
else
    fail "opencode missing file: unexpected exit code $rc"
fi
rm -rf "$EMPTY_TMPDIR"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
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
