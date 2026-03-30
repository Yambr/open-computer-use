#!/bin/sh
# Quick cleanup — runs every 2 hours
# Removes stopped sandbox containers and dangling images.
# Fast and safe — doesn't touch running containers or volumes.

set -eu

log() { echo "[cleanup-quick] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

log "Removing stopped chat containers..."
REMOVED=$(docker ps -a --filter "label=managed-by=mcp-computer-use-orchestrator" \
    --filter "status=exited" --filter "status=dead" \
    --format '{{.ID}}' | xargs -r docker rm 2>/dev/null | wc -l)
log "Removed $REMOVED stopped containers"

log "Pruning dangling images..."
docker image prune -f > /dev/null 2>&1

log "Quick cleanup done."
