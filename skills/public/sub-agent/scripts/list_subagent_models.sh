#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Open Computer Use Contributors
#
# Thin wrapper around the canonical list-subagent-models Python tool.
# Mirrors skills/public/gitlab-explorer/scripts/check_gitlab_auth.sh pattern.
# Does NOT implement model enumeration — single source of truth is the Python tool.
# Per D-04 / D-15 (01-CONTEXT.md): exec the canonical tool, no parallel implementations.
#
# Usage: bash /mnt/skills/public/sub-agent/scripts/list_subagent_models.sh

set -euo pipefail

if ! command -v list-subagent-models >/dev/null 2>&1; then
    echo "list-subagent-models is not on \$PATH inside this sandbox." >&2
    echo "Expected installation: /usr/local/bin/list-subagent-models (see Dockerfile)." >&2
    exit 127
fi

echo "==> Discovering sub-agent models for SUBAGENT_CLI=${SUBAGENT_CLI:-claude} ..." >&2

exec list-subagent-models "$@"
