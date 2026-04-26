#!/bin/bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
# TEST-05: openwebui/init.sh must byte-equal the v0.9.2.0 baseline.
#
# Milestone v0.9.2.1 explicitly forbids modifying init.sh — saved-memory hard
# rule (feedback_init_sh_marker.md) and Pitfall 10 in PITFALLS.md. The init
# script is marker-gated: env->Valve is a one-shot bootstrap, NOT a sync that
# rewrites Valves on every restart (which would annoy operators by clobbering
# their UI tweaks). Any byte change here is a regression.
#
# If a future milestone genuinely needs to edit init.sh, bump the EXPECTED
# constant in this script in the same commit.

set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
INIT_SH="$ROOT/openwebui/init.sh"

EXPECTED="31ce03b67804ed11c5a5e42be8364c0adfedd356d1e9aed9ce87e8318c9c27a7"

if [ ! -f "$INIT_SH" ]; then
    echo "FAIL: $INIT_SH does not exist."
    exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL=$(sha256sum "$INIT_SH" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
    ACTUAL=$(shasum -a 256 "$INIT_SH" | awk '{print $1}')
else
    echo "FAIL: neither sha256sum nor shasum is available on this system."
    exit 1
fi

if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "FAIL: openwebui/init.sh has been modified."
    echo "  Expected sha256: $EXPECTED (v0.9.2.0 baseline)"
    echo "  Actual sha256:   $ACTUAL"
    echo "  Milestone v0.9.2.1 forbids modifying init.sh — see PITFALLS Pitfall 10"
    echo "  and saved memory feedback_init_sh_marker.md. The file must stay"
    echo "  byte-identical to the v0.9.2.0 baseline because init.sh is"
    echo "  marker-gated: env->Valve is a one-shot bootstrap, not a sync."
    echo "  If this edit is intentional in a later milestone, bump EXPECTED in"
    echo "  tests/test_init_sh_unchanged.sh in the same commit."
    exit 1
fi

echo "PASS: openwebui/init.sh matches v0.9.2.0 baseline (sha256 $EXPECTED)."
