#!/bin/sh
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
# Full cleanup — runs daily at 3:00 AM
# Stops old containers, removes stopped ones, cleans volumes and stale data.
#
# IMPORTANT: Only touches owui-chat-* containers, never infrastructure services.
# Volumes are kept for N days after LAST USE (checked via .last_active marker).
#
# Environment variables:
#   CONTAINER_MAX_AGE_HOURS  - Stop running containers older than this (default: 24)
#   VOLUME_MAX_AGE_DAYS      - Remove unused volumes older than this (default: 7)
#   DATA_MAX_AGE_DAYS        - Remove stale data dirs older than this (default: 7)
#   DATA_DIR                 - Host path for chat data (default: /tmp/computer-use-data)
#   DRY_RUN                  - If "true", only log what would be done (default: false)

set -eu

CONTAINER_MAX_AGE_HOURS="${CONTAINER_MAX_AGE_HOURS:-24}"
VOLUME_MAX_AGE_DAYS="${VOLUME_MAX_AGE_DAYS:-7}"
DATA_MAX_AGE_DAYS="${DATA_MAX_AGE_DAYS:-7}"
DATA_DIR="${DATA_DIR:-/tmp/computer-use-data}"
DRY_RUN="${DRY_RUN:-false}"

log() { echo "[cleanup] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

run_or_dry() {
    if [ "$DRY_RUN" = "true" ]; then
        log "DRY RUN: $*"
    else
        "$@"
    fi
}

echo "=== Full cleanup started at $(date -u) ==="

# -------------------------------------------------------------------
# 1. Stop old running chat containers (>N hours)
# -------------------------------------------------------------------
log "Stopping chat containers older than ${CONTAINER_MAX_AGE_HOURS}h..."
docker ps --filter "label=managed-by=mcp-computer-use-orchestrator" \
    --format '{{.ID}} {{.Names}} {{.Status}}' | while read -r id name status; do
    # Match "Up X days" or "Up N hours" where N > threshold
    if echo "$status" | grep -qE "Up [0-9]+ (day|week|month)"; then
        log "  Stopping $name ($status)"
        run_or_dry docker stop "$id"
    elif echo "$status" | grep -qE "Up ([2-9][0-9]|[0-9]{3,}) hours"; then
        HOURS=$(echo "$status" | grep -oE '[0-9]+ hours' | grep -oE '[0-9]+')
        if [ "${HOURS:-0}" -ge "$CONTAINER_MAX_AGE_HOURS" ]; then
            log "  Stopping $name (up ${HOURS}h)"
            run_or_dry docker stop "$id"
        fi
    fi
done

# -------------------------------------------------------------------
# 2. Remove all stopped chat containers
# -------------------------------------------------------------------
log "Removing stopped chat containers..."
docker ps -a --filter "label=managed-by=mcp-computer-use-orchestrator" \
    --filter "status=exited" --filter "status=dead" \
    --format '{{.ID}} {{.Names}}' | while read -r id name; do
    log "  Removing $name"
    run_or_dry docker rm -v "$id"
done

# -------------------------------------------------------------------
# 3. Remove chat volumes unused for N days
# Uses .last_active marker inside volume (touched by entrypoint on start).
# Falls back to volume CreatedAt if no marker exists.
# -------------------------------------------------------------------
log "Checking chat volumes (max age: ${VOLUME_MAX_AGE_DAYS}d)..."
CUTOFF=$(date -u -d "-${VOLUME_MAX_AGE_DAYS} days" +%s 2>/dev/null || \
         date -u -v-${VOLUME_MAX_AGE_DAYS}d +%s 2>/dev/null || echo 0)
REMOVED=0

for vol in $(docker volume ls -q 2>/dev/null | grep "chat-.*-workspace" || true); do
    # Skip if volume is used by a running container
    USED=$(docker ps -q --filter "volume=$vol" 2>/dev/null)
    if [ -n "$USED" ]; then
        continue
    fi

    # Check .last_active marker inside volume
    LAST_ACTIVE=$(docker run --rm -v "$vol:/vol:ro" alpine stat -c %Y /vol/.last_active 2>/dev/null || echo "")

    if [ -z "$LAST_ACTIVE" ]; then
        # No marker — fallback to volume CreatedAt
        CREATED=$(docker volume inspect --format "{{.CreatedAt}}" "$vol" 2>/dev/null | cut -d"." -f1 | cut -d"+" -f1)
        if [ -n "$CREATED" ]; then
            LAST_ACTIVE=$(date -u -d "$CREATED" +%s 2>/dev/null || echo "")
        fi
    fi

    if [ -n "$LAST_ACTIVE" ] && [ "$LAST_ACTIVE" -lt "$CUTOFF" ]; then
        log "  Removing $vol (last active: $(date -u -d @$LAST_ACTIVE +%Y-%m-%d 2>/dev/null || echo 'unknown'))"
        run_or_dry docker volume rm "$vol" && REMOVED=$((REMOVED + 1))
    fi
done
log "Removed $REMOVED old volumes"

# -------------------------------------------------------------------
# 4. Remove stale data directories
# -------------------------------------------------------------------
if [ -d "$DATA_DIR" ]; then
    log "Checking stale data dirs in $DATA_DIR (max age: ${DATA_MAX_AGE_DAYS}d)..."
    find "$DATA_DIR" -maxdepth 1 -mindepth 1 -type d -mtime "+${DATA_MAX_AGE_DAYS}" | while read -r dir; do
        CHAT_ID=$(basename "$dir")
        CONTAINER_NAME="owui-chat-${CHAT_ID}"
        if ! docker ps -a --filter "name=^/${CONTAINER_NAME}$" --format '{{.ID}}' | grep -q .; then
            log "  Removing stale data: $dir"
            run_or_dry rm -rf "$dir"
        fi
    done
fi

# -------------------------------------------------------------------
# 5. Docker system cleanup
# -------------------------------------------------------------------
log "Pruning unused images and build cache..."
run_or_dry docker image prune -f
run_or_dry docker builder prune -f --keep-storage=2GB

echo "=== Disk usage after cleanup ==="
df -h / 2>/dev/null || true

echo "=== Full cleanup finished at $(date -u) ==="
