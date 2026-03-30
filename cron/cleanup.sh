#!/bin/sh
# Cleanup old sandbox containers, orphaned volumes, and stale data.
# Runs periodically via crond in the cron container.
#
# Environment variables:
#   CONTAINER_MAX_AGE_HOURS  - Remove stopped containers older than this (default: 24)
#   VOLUME_MAX_AGE_HOURS     - Remove orphaned volumes older than this (default: 48)
#   DATA_MAX_AGE_DAYS        - Remove stale data dirs older than this (default: 7)
#   DATA_DIR                 - Host path for chat data (default: /tmp/computer-use-data)
#   DRY_RUN                  - If "true", only log what would be done (default: false)

set -eu

CONTAINER_MAX_AGE_HOURS="${CONTAINER_MAX_AGE_HOURS:-24}"
VOLUME_MAX_AGE_HOURS="${VOLUME_MAX_AGE_HOURS:-48}"
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

# -------------------------------------------------------------------
# 1. Remove stopped sandbox containers older than N hours
# -------------------------------------------------------------------
log "Checking stopped containers (max age: ${CONTAINER_MAX_AGE_HOURS}h)..."

CUTOFF=$(date -u -d "-${CONTAINER_MAX_AGE_HOURS} hours" +%s 2>/dev/null || \
         date -u -v-${CONTAINER_MAX_AGE_HOURS}H +%s 2>/dev/null || echo 0)

docker ps -a --filter "label=managed-by=mcp-computer-use-orchestrator" \
    --filter "status=exited" --filter "status=dead" \
    --format '{{.ID}} {{.Names}} {{.CreatedAt}}' | while read -r id name created; do
    # Parse container creation time
    CREATED_TS=$(date -u -d "$created" +%s 2>/dev/null || echo 0)
    if [ "$CREATED_TS" -gt 0 ] && [ "$CREATED_TS" -lt "$CUTOFF" ]; then
        log "Removing stopped container: $name (created: $created)"
        run_or_dry docker rm -v "$id"
    fi
done

# -------------------------------------------------------------------
# 2. Remove orphaned workspace volumes (no matching container)
# -------------------------------------------------------------------
log "Checking orphaned volumes (max age: ${VOLUME_MAX_AGE_HOURS}h)..."

docker volume ls --filter "name=chat-" --format '{{.Name}}' | while read -r vol; do
    # Extract chat_id from volume name: chat-{uuid}-workspace
    CHAT_ID=$(echo "$vol" | sed 's/^chat-//; s/-workspace$//')
    CONTAINER_NAME="owui-chat-${CHAT_ID}"

    # Check if container exists (running or stopped)
    if ! docker ps -a --filter "name=^/${CONTAINER_NAME}$" --format '{{.ID}}' | grep -q .; then
        log "Removing orphaned volume: $vol (no container: $CONTAINER_NAME)"
        run_or_dry docker volume rm "$vol"
    fi
done

# -------------------------------------------------------------------
# 3. Remove stale data directories
# -------------------------------------------------------------------
if [ -d "$DATA_DIR" ]; then
    log "Checking stale data dirs in $DATA_DIR (max age: ${DATA_MAX_AGE_DAYS}d)..."
    find "$DATA_DIR" -maxdepth 1 -mindepth 1 -type d -mtime "+${DATA_MAX_AGE_DAYS}" | while read -r dir; do
        CHAT_ID=$(basename "$dir")
        CONTAINER_NAME="owui-chat-${CHAT_ID}"
        # Only remove if no container exists
        if ! docker ps -a --filter "name=^/${CONTAINER_NAME}$" --format '{{.ID}}' | grep -q .; then
            log "Removing stale data dir: $dir"
            run_or_dry rm -rf "$dir"
        fi
    done
fi

# -------------------------------------------------------------------
# 4. Docker system cleanup (dangling images, build cache)
# -------------------------------------------------------------------
log "Pruning dangling images and build cache..."
run_or_dry docker image prune -f
run_or_dry docker builder prune -f --keep-storage=2GB

log "Cleanup complete."
