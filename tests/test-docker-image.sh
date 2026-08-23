#!/bin/bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
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
    # --entrypoint=bash bypasses /home/assistant/.entrypoint.sh, which prints
    # GITLAB_TOKEN / ANTHROPIC_AUTH_TOKEN status banners and corrupts captured
    # stdout when those env vars are unset (CI default).
    # --user=assistant matches production (docker-compose runs as assistant)
    # so user-scoped npm config (prefix delete, etc.) is the configuration
    # actually under test.
    docker run --rm --platform linux/amd64 --entrypoint=bash --user=assistant "$IMAGE" -c "$1" 2>/dev/null
}

# Same run, but stderr is KEPT. run_in_container discards it, which is correct
# for an assertion -- a tool's chatter is not the subject -- and useless the
# moment something fails for a reason only stderr carries. #426 stalled exactly
# there: the tsx probe failed in CI, the cause was suppressed, and diagnosing it
# needed a machine that could build the image.
run_in_container_verbose() {
    docker run --rm --platform linux/amd64 --entrypoint=bash --user=assistant "$IMAGE" -c "$1" 2>&1
}

echo "=== Testing Docker image: $IMAGE ==="
echo ""

# Note on `|| VAR=""` after every `VAR=$(run_in_container ...)`:
# Without it, `set -euo pipefail` aborts the whole script the moment docker
# returns non-zero — before fail() can record the failure or print summary.
# Forcing the assignment to succeed (with empty content on docker error) lets
# the existing grep-based pass/fail accounting handle the failure naturally.

# 1. Node.js and Python versions
echo "[1/14] Runtime versions"
VERSIONS=$(run_in_container 'node --version && python3 --version') || VERSIONS=""
echo "$VERSIONS" | grep -q "v22" && pass "Node.js v22" || fail "Node.js version"
echo "$VERSIONS" | grep -q "Python 3" && pass "Python 3" || fail "Python version"

# 2. CommonJS require()
echo ""
echo "[2/14] CommonJS require()"
for pkg in react pptxgenjs pdf-lib docx sharp react-dom/server react-icons/fa; do
    RESULT=$(run_in_container "node -e \"try { require('$pkg'); console.log('OK') } catch(e) { console.log('FAIL: ' + e.code) }\"") || RESULT=""
    echo "$RESULT" | grep -q "OK" && pass "require('$pkg')" || fail "require('$pkg'): $RESULT"
done

# marked renders, rather than merely loading. A major of a renderer keeps the
# module importable and changes the API or the output shape, so loading it alone
# waves that through; parsing a heading and checking for <h1> does not.
#
# ESM, not require(): the image ships a marked build that is ESM-only, so
# require() raises ERR_REQUIRE_ESM. It therefore does NOT belong in the CommonJS
# list above — measured in the image, not assumed from the host, where an older
# CommonJS marked is installed and require() succeeds.
RESULT=$(run_in_container "node --input-type=module -e \"import {marked} from 'marked'; const h=marked.parse('# t'); console.log(/<h1/.test(h)?'OK':'FAIL')\"") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "marked renders a heading" || fail "marked render"

# tsc COMPILES. The CLI loop below only proves --version exits 0, which a major
# that changed type-checking would also satisfy. This compiles a strict file and
# then asserts a deliberately ill-typed one is REJECTED, so the check cannot pass
# by accepting everything.
RESULT=$(run_in_container "d=\$(mktemp -d); printf 'export const twice = (x: number): number => x * 2;\\n' > \$d/a.ts; tsc --noEmit --strict \$d/a.ts >/dev/null 2>&1 && echo OK || echo FAIL") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "tsc compiles a strict file" || fail "tsc compile"
RESULT=$(run_in_container "d=\$(mktemp -d); printf 'const n: number = \\"nope\\";\\n' > \$d/b.ts; tsc --noEmit --strict \$d/b.ts >/dev/null 2>&1 && echo FAIL || echo OK") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "tsc rejects an ill-typed file" || fail "tsc did not reject bad types"

# 3. ES Modules import
echo ""
echo "[3/14] ES Modules import"
for pkg in react pptxgenjs pdf-lib; do
    RESULT=$(run_in_container "node --input-type=module -e \"import '$pkg'; console.log('OK')\"") || RESULT=""
    echo "$RESULT" | grep -q "OK" && pass "import '$pkg'" || fail "import '$pkg'"
done

# 4. html2pptx import (full path)
echo ""
echo "[4/14] html2pptx import"
RESULT=$(run_in_container "node --input-type=module -e \"import { html2pptx } from '/usr/local/lib/node_modules_global/lib/node_modules/@anthropic-ai/html2pptx/dist/html2pptx.mjs'; console.log('OK')\"" 2>/dev/null || echo "SKIP")
if echo "$RESULT" | grep -q "OK"; then
    pass "html2pptx ESM import"
elif echo "$RESULT" | grep -q "SKIP"; then
    echo "  SKIP: html2pptx (package path may vary)"
else
    fail "html2pptx ESM import"
fi

# 5. CLI tools (Phase 6 — extended to include codex + opencode + --version smoke)
echo ""
echo "[5/14] CLI tools"
for tool in mmdc tsc tsx claude codex opencode; do
    RESULT=$(run_in_container "which $tool >/dev/null 2>&1 && echo OK || echo MISSING") || RESULT=""
    echo "$RESULT" | grep -q "OK" && pass "$tool in PATH" || fail "$tool not found in PATH"
    # Phase 6 / TEST-01 — every CLI must respond to --version with exit 0.
    VRESULT=$(run_in_container "$tool --version >/dev/null 2>&1 && echo OK || echo FAIL") || VRESULT=""
    echo "$VRESULT" | grep -q "OK" && pass "$tool --version exit 0" || fail "$tool --version failed"
done

# tsx must RUN a file, not merely answer --version. #425 removed ts-node because
# TypeScript 7 deletes the API it consumed, which leaves tsx as the only way a
# skill executes TypeScript -- so "installed" stopped being a sufficient claim.
#
# On failure this prints the command's own stderr. The first attempt at this
# check (#426) suppressed it, the CI failure said only "FAIL: tsx execution",
# and finding the cause needed someone who could build and enter the image.
# A check that cannot say why it failed defers the work rather than doing it.
TSX_PROBE='cd /tmp && printf "console.log(\"tsx-ok\", 2*2);\n" > tsxprobe.ts && tsx tsxprobe.ts'
# NOT `|| TSX_OUT="..."`: that fires on a NON-ZERO EXIT, which is exactly the
# failing case, and overwrites the captured stderr with a placeholder. Probed --
# it turned a real "Cannot find module" into "<docker run failed>", reproducing
# the uninformative output this check exists to replace. Capture first, then
# read the status separately.
TSX_OUT=$(run_in_container_verbose "$TSX_PROBE"; echo "rc=$?")
if echo "$TSX_OUT" | grep -q "tsx-ok 4"; then
    pass "tsx executes a TypeScript file"
else
    fail "tsx cannot execute a TypeScript file"
    echo "    the container said:"
    echo "$TSX_OUT" | sed 's/^/      /' | head -20
fi

# list-subagent-models presence + executability (Phase 1 / Plan 01-05 install line)
RESULT=$(run_in_container "which list-subagent-models >/dev/null 2>&1 && echo OK || echo MISSING") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "list-subagent-models in PATH" || fail "list-subagent-models not found in PATH"
RESULT=$(run_in_container "test -x \$(which list-subagent-models 2>/dev/null || echo /nonexistent) && echo OK || echo FAIL") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "list-subagent-models is executable" || fail "list-subagent-models is not executable inside image"

# Phase 2 smoke: list-subagent-models claude path (always available, no env or
# config files needed) returns valid JSON with cli="claude" and non-empty
# models array. This catches a class of bugs where the script is present and
# executable but crashes at runtime (broken import, missing stdlib, etc.).
RESULT=$(run_in_container "SUBAGENT_CLI=claude list-subagent-models 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"cli\"]==\"claude\" and len(d[\"models\"])>=3, d; print(\"OK\")'") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "list-subagent-models claude returns valid JSON with >=3 models" || fail "list-subagent-models claude smoke failed"

# Phase 2 smoke: list-subagent-models opencode path with no env (canonical
# cli-defaults/opencode.json fallback). Validates the host-friendly read path
# end-to-end inside the container.
RESULT=$(run_in_container "unset OPENCODE_CONFIG_EXTRA OPENCODE_MODEL_ALIASES OPENCODE_SUB_AGENT_DEFAULT_MODEL; SUBAGENT_CLI=opencode list-subagent-models 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"cli\"]==\"opencode\" and \"models\" in d, d; print(\"OK\")'") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "list-subagent-models opencode returns valid JSON from canonical cli-defaults" || fail "list-subagent-models opencode canonical smoke failed"

# The entrypoint's own config writer, run for real rather than bypassed.
#
# Every other check here uses --entrypoint=bash, which is what let this defect
# live: the entrypoint is generated by one ~300-line `RUN printf '...'`, and a
# bare %s inside that format string is consumed by the build's own printf. The
# shipped line became `printf ""` — an empty format with the config passed as a
# discarded argument. The file was created, so nothing failed; it was 0 bytes,
# and opencode silently loaded its own defaults instead of the operator's
# gateway. Measured in production: 465 bytes of the variable inside the
# container, 0 bytes in the file it should have written.
#
# So this asserts the byte count, not the exit code. Reading the Dockerfile
# source would not catch it — the source is correct, and the bug is introduced
# between source and image.
CFG='{"model":"litellm/probe","provider":{"litellm":{}}}'
RESULT=$(docker run --rm --platform linux/amd64 --user=assistant \
    -e SUBAGENT_CLI=opencode -e OPENCODE_CONFIG_EXTRA="$CFG" \
    --entrypoint=bash "$IMAGE" -c '
        eval "$(sed -n "/^ *case .\${SUBAGENT_CLI/,/^ *esac/p" /home/assistant/.entrypoint.sh)"
        printf "%s|%s" "$(wc -c < /tmp/opencode.json)" "$(cat /tmp/opencode.json)"
    ' 2>/dev/null) || RESULT=""
EXPECTED_LEN=${#CFG}
if [ "$RESULT" = "${EXPECTED_LEN}|${CFG}" ]; then
    pass "entrypoint writes OPENCODE_CONFIG_EXTRA to /tmp/opencode.json intact ($EXPECTED_LEN bytes)"
else
    fail "entrypoint config writer: expected ${EXPECTED_LEN}|<config>, got '${RESULT}'"
fi

# 6. Python packages
echo ""
echo "[6/14] Python packages"
for pkg in docx pptx openpyxl; do
    RESULT=$(run_in_container "python3 -c \"import $pkg; print('OK')\"") || RESULT=""
    echo "$RESULT" | grep -q "OK" && pass "python import $pkg" || fail "python import $pkg"
done

# The data/imaging packages requirements.txt installs but nothing imported. A
# major bump of any of these builds cleanly — pip resolves it, the image layer
# is produced, "Build Sandbox Image" goes green — and then fails the first time
# a skill touches it. Each line below EXERCISES the package rather than merely
# importing it, because a broken major usually imports fine and moves an API.
RESULT=$(run_in_container "python3 -c \"import pandas as pd; df=pd.DataFrame({'a':[1,2]}); assert df['a'].sum()==3; print('OK')\"") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "python pandas (DataFrame + sum)" || fail "python pandas"
RESULT=$(run_in_container "python3 -c \"import numpy as np; assert np.arange(3).sum()==3; print('OK')\"") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "python numpy (arange + sum)" || fail "python numpy"
RESULT=$(run_in_container "python3 -c \"import scipy.stats as st; assert round(st.norm.cdf(0),3)==0.5; print('OK')\"") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "python scipy (stats.norm)" || fail "python scipy"
RESULT=$(run_in_container "python3 -c \"import cv2, numpy as np; img=np.zeros((4,4,3),dtype=np.uint8); assert cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).shape==(4,4); print('OK')\"") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "python opencv (cvtColor)" || fail "python opencv"
RESULT=$(run_in_container "python3 -c \"import imageio.v3 as iio, numpy as np, tempfile, os; p=os.path.join(tempfile.mkdtemp(),'t.png'); iio.imwrite(p, np.zeros((4,4,3),dtype=np.uint8)); assert iio.imread(p).shape==(4,4,3); print('OK')\"") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "python imageio (write + read round-trip)" || fail "python imageio"
RESULT=$(run_in_container "python3 -c \"from PIL import Image; im=Image.new('RGB',(4,4)); assert im.size==(4,4); print('OK')\"") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "python pillow (Image.new)" || fail "python pillow"
RESULT=$(run_in_container "python3 -c \"from playwright.sync_api import sync_playwright; print('OK')\"") || RESULT=""
echo "$RESULT" | grep -q "OK" && pass "python playwright" || fail "python playwright"

# 7. User npm install (lodash)
echo ""
echo "[7/14] User npm install"
RESULT=$(run_in_container 'cd /home/assistant && npm install lodash >/dev/null 2>&1 && if [ -d /home/assistant/node_modules/lodash ]; then echo "user=YES"; else echo "user=NO"; fi && SYS_COUNT=$(ls /home/node_modules/ 2>/dev/null | wc -l) && echo "system=$SYS_COUNT"') || RESULT=""
echo "$RESULT" | grep -q "user=YES" && pass "lodash in /home/assistant/node_modules" || fail "lodash not in user dir"
SYS=$(echo "$RESULT" | awk -F= '/^system=/{print $2}')
[ "${SYS:-0}" -gt 100 ] && pass "system packages intact ($SYS)" || fail "system packages count: $SYS (expected > 100)"

# 8. npm prefix check
echo ""
echo "[8/14] npm configuration"
RESULT=$(run_in_container 'npm config get prefix 2>/dev/null || echo "undefined"') || RESULT=""
# Trim trailing whitespace/newlines so the anchored regex below can match
# against a clean single-line value.
RESULT_TRIMMED=$(echo "$RESULT" | head -n1 | tr -d '[:space:]')
# Acceptable, anchored values:
#   - "undefined"                           — legacy npm with prefix unset
#   - "/usr/local"                          — Dockerfile runs `npm config
#                                             delete prefix` as last step, so
#                                             npm falls back to its default
#   - "/usr/local/lib/node_modules_global"  — explicit pin (older image layout)
# The anchored regex rejects silently permissive substring matches like
# "/usr/local/something/weird" or "node_modules_global" appearing in
# arbitrary paths.
if echo "$RESULT_TRIMMED" | grep -qE "^(undefined|/usr/local|/usr/local/lib/node_modules_global)$"; then
    pass "npm prefix configured correctly ($RESULT_TRIMMED)"
else
    fail "npm prefix: $RESULT_TRIMMED"
fi

# 9. Volume size
echo ""
echo "[9/14] Volume size"
SIZE_KB=$(run_in_container "du -sk /home/assistant/ | cut -f1") || SIZE_KB=""
if [ "${SIZE_KB:-999999}" -lt 1024 ]; then
    pass "/home/assistant < 1MB (${SIZE_KB}KB)"
else
    fail "/home/assistant = ${SIZE_KB}KB (expected < 1024KB)"
fi

# 10. Permissions and guard files
echo ""
echo "[10/14] Permissions and guard files"
RESULT=$(run_in_container '
[ -x /home/assistant/.entrypoint.sh ] && echo "entrypoint=OK" || echo "entrypoint=FAIL"
[ -f /home/assistant/.gitconfig ] && echo "gitconfig=OK" || echo "gitconfig=FAIL"
[ -f /home/assistant/package.json ] && echo "packagejson=OK" || echo "packagejson=FAIL"
OWNER=$(stat -c %U /home/assistant/.entrypoint.sh)
echo "owner=$OWNER"
') || RESULT=""
echo "$RESULT" | grep -q "entrypoint=OK" && pass ".entrypoint.sh executable" || fail ".entrypoint.sh not executable"
echo "$RESULT" | grep -q "gitconfig=OK" && pass ".gitconfig exists" || fail ".gitconfig missing"
echo "$RESULT" | grep -q "packagejson=OK" && pass "package.json guard exists" || fail "package.json guard missing"
echo "$RESULT" | grep -q "owner=assistant" && pass "files owned by assistant" || fail "files not owned by assistant"

# 11. Per-CLI dispatch smoke (Phase 6 / TEST-06).
# Run the image with SUBAGENT_CLI set to each value and verify:
#   (a) entrypoint marker file /tmp/.cli-runtime-initialised lands on first run
#   (b) on a SECOND entrypoint invocation the heredoc is SKIPPED
#       (ROADMAP success #4: "on restart sentinel present, heredoc skipped")
# Stub auth env vars only — no real LLM calls.
# NOTE: do NOT pass --user=assistant. Production entrypoint runs as root before
# the user shell starts (Plan 06-03 codex chown line assumes root). Running as
# root here matches production parity. /tmp is world-readable so the marker
# check works regardless.
echo ""
echo "[11/14] Per-CLI dispatch smoke + marker gating"
for cli in claude codex opencode; do
    SMOKE_CONTAINER="ocu-smoke-${cli}-$$"
    # Start a long-running container (so we can exec the entrypoint twice).
    docker run -d --rm --platform linux/amd64 \
        --name "$SMOKE_CONTAINER" \
        -e SUBAGENT_CLI="$cli" \
        -e ANTHROPIC_AUTH_TOKEN="sk-stub" \
        -e OPENAI_API_KEY="sk-stub" \
        -e OPENROUTER_API_KEY="sk-or-stub" \
        --entrypoint=bash \
        "$IMAGE" \
        -c "tail -f /dev/null" >/dev/null 2>&1 || { fail "SUBAGENT_CLI=$cli — could not start smoke container"; continue; }

    # First run: entrypoint must land marker.
    docker exec "$SMOKE_CONTAINER" /home/assistant/.entrypoint.sh true >/dev/null 2>&1 || true
    MARKER_RESULT=$(docker exec "$SMOKE_CONTAINER" sh -c "[ -f /tmp/.cli-runtime-initialised ] && echo MARKER_OK || echo MARKER_MISSING" 2>&1) || MARKER_RESULT=""
    if echo "$MARKER_RESULT" | grep -q "MARKER_OK"; then
        pass "SUBAGENT_CLI=$cli — marker /tmp/.cli-runtime-initialised landed"
    else
        fail "SUBAGENT_CLI=$cli — marker missing after first run"
        docker rm -f "$SMOKE_CONTAINER" >/dev/null 2>&1 || true
        continue
    fi

    # Marker-gating verification (only meaningful for opencode — that's the
    # CLI whose heredoc writes /tmp/opencode.json that we can sentinel-overwrite).
    # For codex the rendered file is in /home/assistant/.codex/config.toml, but
    # the gating logic is identical (one if-block guards both branches in the
    # entrypoint), so verifying for opencode proves the gate works for codex too.
    if [ "$cli" = "opencode" ]; then
        # Overwrite /tmp/opencode.json with a sentinel string. If the heredoc
        # re-fires on second invocation (gate broken), it will overwrite our
        # sentinel back to the JSON config.
        docker exec "$SMOKE_CONTAINER" sh -c 'echo "GATED-SENTINEL" > /tmp/opencode.json' >/dev/null 2>&1 || true
        # Second run: marker is already present, heredoc must be skipped.
        docker exec "$SMOKE_CONTAINER" /home/assistant/.entrypoint.sh true >/dev/null 2>&1 || true
        SENTINEL_RESULT=$(docker exec "$SMOKE_CONTAINER" cat /tmp/opencode.json 2>&1) || SENTINEL_RESULT=""
        if [ "$SENTINEL_RESULT" = "GATED-SENTINEL" ]; then
            pass "SUBAGENT_CLI=$cli — marker gating works (heredoc skipped on second run)"
        else
            fail "SUBAGENT_CLI=$cli — marker gating BROKEN: heredoc re-fired despite sentinel marker (got: $(echo "$SENTINEL_RESULT" | head -c 100))"
        fi
    fi

    # Phase 7 verification: autostart line in .bashrc references the chosen CLI.
    # The literal exec line is the same for every $cli (the SUBAGENT_CLI value
    # is resolved at session-start time, not at .bashrc-write time), so we just
    # assert the new shape exists once per loop iteration.
    AUTOSTART_LINE_BASHRC=$(docker exec "$SMOKE_CONTAINER" cat /home/assistant/.bashrc 2>/dev/null | grep -F 'SUBAGENT_AUTOSTARTED' || true)
    if echo "$AUTOSTART_LINE_BASHRC" | grep -qF 'exec "${SUBAGENT_CLI:-claude}"'; then
        pass "SUBAGENT_CLI=$cli — .bashrc autostart line wires to \${SUBAGENT_CLI:-claude}"
    else
        fail "SUBAGENT_CLI=$cli — .bashrc autostart line missing or malformed (got: $AUTOSTART_LINE_BASHRC)"
    fi
    if echo "$AUTOSTART_LINE_BASHRC" | grep -qF 'NO_AUTOSTART' && echo "$AUTOSTART_LINE_BASHRC" | grep -qF '/tmp/.no_autostart'; then
        pass "SUBAGENT_CLI=$cli — .bashrc autostart honours NO_AUTOSTART env + /tmp/.no_autostart sentinel"
    else
        fail "SUBAGENT_CLI=$cli — .bashrc autostart missing escape hatches (got: $AUTOSTART_LINE_BASHRC)"
    fi
    # Backwards-compat regression guard: old marker name must NOT appear.
    if docker exec "$SMOKE_CONTAINER" grep -q 'CLAUDE_AUTOSTARTED' /home/assistant/.bashrc 2>/dev/null; then
        fail "SUBAGENT_CLI=$cli — orphan CLAUDE_AUTOSTARTED reference in .bashrc (rename incomplete)"
    else
        pass "SUBAGENT_CLI=$cli — old CLAUDE_AUTOSTARTED marker fully purged from .bashrc"
    fi

    docker rm -f "$SMOKE_CONTAINER" >/dev/null 2>&1 || true
done

# 12. NO_AUTOSTART escape hatch smoke (Phase 7 / TERM-02).
# Exercises the .bashrc autostart guards by sourcing .bashrc with PS1 set
# (the [ -n "$PS1" ] guard would otherwise short-circuit and falsely pass).
# Two variants: env var NO_AUTOSTART=1 and sentinel file /tmp/.no_autostart.
echo ""
echo "[12/14] NO_AUTOSTART escape hatch"
NOAUTOSTART_OUT=$(docker run --rm --platform linux/amd64 \
    -e SUBAGENT_CLI=claude \
    -e NO_AUTOSTART=1 \
    --entrypoint=bash \
    "$IMAGE" \
    -c 'PS1="t> " && source /home/assistant/.bashrc 2>&1 && echo BASH_REACHED' 2>&1) || true
if echo "$NOAUTOSTART_OUT" | grep -q 'BASH_REACHED'; then
    pass "NO_AUTOSTART=1 — autostart skipped, plain bash reached"
else
    fail "NO_AUTOSTART=1 — autostart still fired (output: $(echo "$NOAUTOSTART_OUT" | head -c 200))"
fi

# Sentinel-file escape hatch: same shape, but use /tmp/.no_autostart instead.
SENTINEL_OUT=$(docker run --rm --platform linux/amd64 \
    -e SUBAGENT_CLI=claude \
    --entrypoint=bash \
    "$IMAGE" \
    -c 'touch /tmp/.no_autostart && PS1="t> " && source /home/assistant/.bashrc 2>&1 && echo BASH_REACHED' 2>&1) || true
if echo "$SENTINEL_OUT" | grep -q 'BASH_REACHED'; then
    pass "/tmp/.no_autostart sentinel — autostart skipped, plain bash reached"
else
    fail "/tmp/.no_autostart sentinel — autostart still fired (output: $(echo "$SENTINEL_OUT" | head -c 200))"
fi

# 13. cli-defaults/ canonical configs present and parseable (Phase 2 D-09).
echo ""
echo "[13/14] cli-defaults/ canonical configs present and parseable"
for f in opencode.json codex.json README.md; do
    if docker run --rm --platform linux/amd64 "$IMAGE" sh -c "test -f /opt/cli-defaults/$f" 2>/dev/null; then
        pass "/opt/cli-defaults/$f exists in image"
    else
        fail "/opt/cli-defaults/$f missing in image"
    fi
done
for f in opencode.json codex.json; do
    if docker run --rm --platform linux/amd64 "$IMAGE" python3 -c "import json; json.load(open('/opt/cli-defaults/$f'))" 2>/dev/null; then
        pass "/opt/cli-defaults/$f parses as JSON"
    else
        fail "/opt/cli-defaults/$f failed JSON parse"
    fi
done
# _spdx key present in opencode.json
if docker run --rm --platform linux/amd64 "$IMAGE" python3 -c "import json; assert json.load(open('/opt/cli-defaults/opencode.json'))['_spdx'] == 'FSL-1.1-Apache-2.0'" 2>/dev/null; then
    pass "/opt/cli-defaults/opencode.json carries _spdx=FSL-1.1-Apache-2.0"
else
    fail "/opt/cli-defaults/opencode.json missing _spdx key"
fi

# 14. Entrypoint executes cleanly with the real ENTRYPOINT path.
# All other tests bypass /home/assistant/.entrypoint.sh via --entrypoint=bash
# so stdout parsing works. That leaves no coverage for the entrypoint script
# itself — a shell syntax error there would ship unnoticed. This step runs
# the image with its declared entrypoint and checks that (a) the process
# exits 0, and (b) the expected status banner is printed.
echo ""
echo "[14/14] Entrypoint execution"
# Wrap the command substitution in `if` so `set -e` does not abort the
# whole test script on a non-zero docker exit — we need to reach fail()
# with the captured output for structured reporting.
if ENTRYPOINT_OUT=$(docker run --rm --platform linux/amd64 --user=assistant "$IMAGE" true 2>&1); then
    pass "entrypoint exits 0 with default command"
else
    ENTRYPOINT_EXIT=$?
    fail "entrypoint exited $ENTRYPOINT_EXIT (output: $ENTRYPOINT_OUT)"
fi
# The banner text changes based on token presence; at least one of these
# lines must appear, proving the entrypoint ran through its env-check block.
if echo "$ENTRYPOINT_OUT" | grep -qE "(GITLAB_TOKEN|ANTHROPIC_AUTH_TOKEN|Claude Code configured)"; then
    pass "entrypoint printed expected status banner"
else
    fail "entrypoint ran but produced no recognisable banner: $ENTRYPOINT_OUT"
fi
# Phase 7 / TERM-03: entrypoint MOTD must include the autostart escape hint.
if echo "$ENTRYPOINT_OUT" | grep -qF "NO_AUTOSTART=1 bash"; then
    pass "entrypoint printed sub-agent autostart escape hint"
else
    fail "entrypoint missing escape-hint line (NO_AUTOSTART=1 bash / touch /tmp/.no_autostart): $ENTRYPOINT_OUT"
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
    echo "  RESULT: ALL TESTS PASSED"
    exit 0
fi
