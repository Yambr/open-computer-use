#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
#
# Pre-flight check for .env before `docker compose up`. Catches the common
# silent-fail misconfigurations (PUBLIC_BASE_URL default, half-enabled feature
# groups, weak passwords) at invocation time rather than in production.
#
# Usage:   ./scripts/check-config.sh [path/to/.env]
# Exit 0 on clean config or only WARNs; exit 1 if any ERR is reported.

set -uo pipefail

ENV_FILE="${1:-.env}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: env file not found: $ENV_FILE" >&2
    echo "  Hint: cp .env.example .env && edit it" >&2
    exit 1
fi

# Load .env into the current shell. `set -a` auto-exports; `|| true` around
# source protects against malformed lines triggering `set -u` aborts. We DO
# want `set -u` off temporarily because .env.example keeps many vars unset.
set +u
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

errors=0
warns=0
oks=0

section() {
    printf '\n== %s ==\n' "$1"
}

ok()   { printf '  [OK]   %s\n' "$1"; oks=$((oks + 1)); }
warn() { printf '  [WARN] %s\n' "$1"; warns=$((warns + 1)); }
err()  { printf '  [ERR]  %s\n' "$1"; errors=$((errors + 1)); }

echo "Config check for open-computer-use"
echo "=================================="
echo "Env file: $ENV_FILE"

# ----- REQUIRED -----
section "REQUIRED"

pbu="${PUBLIC_BASE_URL:-}"
# Strip a single trailing slash so `http://computer-use-server:8081/` still
# matches the internal default check below.
pbu="${pbu%/}"
if [[ -z "$pbu" ]]; then
    err "PUBLIC_BASE_URL is unset (browser-reachable URL of the Computer Use server)"
elif [[ "$pbu" == "http://computer-use-server:8081" ]]; then
    err "PUBLIC_BASE_URL is still the internal-DNS default — browser can't reach it"
else
    ok "PUBLIC_BASE_URL = $pbu"
fi

ap="${ADMIN_PASSWORD:-}"
case "$ap" in
    ""|admin|change-me)
        warn "ADMIN_PASSWORD is weak/default ('$ap') — fine for local dev only" ;;
    *)
        ok "ADMIN_PASSWORD is set" ;;
esac

wsk="${WEBUI_SECRET_KEY:-}"
case "$wsk" in
    ""|change-me)
        warn "WEBUI_SECRET_KEY is unset or placeholder — sessions won't survive restart" ;;
    *)
        ok "WEBUI_SECRET_KEY is set" ;;
esac

pg="${POSTGRES_PASSWORD:-openwebui}"
if [[ "$pg" == "openwebui" ]]; then
    warn "POSTGRES_PASSWORD is still the default ('openwebui') — change for production"
else
    ok "POSTGRES_PASSWORD is set"
fi

if [[ -z "${MCP_API_KEY:-}" ]]; then
    warn "MCP_API_KEY is empty — /mcp endpoints have no auth (fine for local dev)"
else
    ok "MCP_API_KEY is set"
fi

oak="${OPENAI_API_KEY:-}"
if [[ -z "$oak" || "$oak" == "sk-..." ]]; then
    warn "OPENAI_API_KEY is empty/placeholder — the chat completion will not work"
else
    ok "OPENAI_API_KEY is set"
fi

# ----- OPTIONAL FEATURE GROUPS (all-or-nothing) -----
section "OPTIONAL FEATURE GROUPS"

# Vision: VISION_API_KEY + VISION_API_URL + VISION_MODEL
vak="${VISION_API_KEY:-}"
vau="${VISION_API_URL:-}"
vmo="${VISION_MODEL:-}"
vision_set=0
for v in "$vak" "$vau" "$vmo"; do
    if [[ -n "$v" ]]; then vision_set=$((vision_set + 1)); fi
done
case "$vision_set" in
    0) ok "Vision: not configured (skipping group)" ;;
    3) ok "Vision: all three set" ;;
    *) err "Vision: partial config (only $vision_set/3 set) — set all three or none" ;;
esac

# MCP Tokens Wrapper: MCP_TOKENS_URL + MCP_TOKENS_API_KEY
mtu="${MCP_TOKENS_URL:-}"
mtk="${MCP_TOKENS_API_KEY:-}"
if [[ -z "$mtu" && -z "$mtk" ]]; then
    ok "MCP Tokens: not configured (skipping group)"
elif [[ -n "$mtu" && -n "$mtk" ]]; then
    ok "MCP Tokens: both configured"
else
    err "MCP Tokens: partial config — set BOTH MCP_TOKENS_URL and MCP_TOKENS_API_KEY or neither"
fi

# Anthropic sub-agent presence (single toggle, no pairing required)
if [[ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
    ok "Claude Code sub-agent: enabled"
fi

# ----- SUMMARY -----
section "SUMMARY"
printf 'OK: %d  WARN: %d  ERR: %d\n' "$oks" "$warns" "$errors"

if [[ "$errors" -gt 0 ]]; then
    echo
    echo "Fix the [ERR] items above before running 'docker compose up'."
    exit 1
fi

exit 0
