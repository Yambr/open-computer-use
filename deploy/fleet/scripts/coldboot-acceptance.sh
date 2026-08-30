#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
#
# Cold-boot acceptance for the ocu-donegate fleet: prove the stack rebuilds
# and boots from destroyed volumes with ZERO manual steps.
#
# The keystone is destruction-then-reconstruction, so it MUST run the
# destructive half. The failure it guards against is running that half before
# proving the reconstruction can succeed -- a `down -v` that wipes the only
# stand while a multi-GB base image is unfetchable over a flaky uplink strands
# the whole fleet with no warm fallback. Hence step 0: every image the compose
# graph needs is either present locally or its build FROM-chain is, and any
# large remote-only base is `docker save`d to disk BEFORE teardown. Only then
# does `down -v` run.
#
# Usage:
#   coldboot-acceptance.sh preflight   # step 0 only: prove reconstruction, save bases
#   coldboot-acceptance.sh full        # preflight -> down -v -> up -> health -> ladder
#   coldboot-acceptance.sh ladder      # acceptance ladder against an already-up stack
#
# Env:
#   COMPOSE_FILE (default deploy/fleet/docker-compose.fleet.yml)
#   PROJECT      (default ocu-donegate)
#   SAVE_DIR     (default ./image-cache) where large bases get docker-saved
#   MIN_HEALTHY  (default 12) healthy-container threshold for the boot wait

set -uo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-deploy/fleet/docker-compose.fleet.yml}"
PROJECT="${PROJECT:-ocu-donegate}"
SAVE_DIR="${SAVE_DIR:-./image-cache}"
MIN_HEALTHY="${MIN_HEALTHY:-12}"
LARGE_BASE_BYTES=$((1024 * 1024 * 1024)) # 1GB: bases at/above this get saved

dc() { docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"; }

# --- step 0: prove reconstruction BEFORE any destruction --------------------
preflight() {
  echo "=== step 0: image-inventory preflight (prove reconstruction) ==="
  local missing=0
  # Every image the running graph references (built tags + pinned bases).
  local images
  images="$(dc config --images 2>/dev/null | sort -u)"
  if [ -z "$images" ]; then
    echo "PREFLIGHT-FAIL: compose config --images returned nothing" >&2
    return 1
  fi

  mkdir -p "$SAVE_DIR"
  local img present size
  while IFS= read -r img; do
    [ -z "$img" ] && continue
    if docker image inspect "$img" >/dev/null 2>&1; then
      present="local"
      size="$(docker image inspect "$img" --format '{{.Size}}' 2>/dev/null)"
      # A large remote-only base is the single point of failure on teardown:
      # save it so a lost tag survives `down -v` and a flaky uplink.
      if [ "${size:-0}" -ge "$LARGE_BASE_BYTES" ]; then
        local safe tarball
        safe="$(printf '%s' "$img" | tr '/:@' '___')"
        tarball="$SAVE_DIR/$safe.tar"
        if [ ! -s "$tarball" ]; then
          echo "  saving large base $img -> $tarball ($(( size / 1024 / 1024 ))MB)"
          docker save "$img" -o "$tarball" || {
            echo "PREFLIGHT-FAIL: could not save $img" >&2
            missing=1
          }
        else
          echo "  large base $img already saved ($tarball)"
        fi
      fi
      echo "  OK   $present  $img"
    else
      echo "  MISS $img (not local; must be pullable or its FROM-chain local before teardown)"
      missing=1
    fi
  done <<<"$images"

  if [ "$missing" -ne 0 ]; then
    echo "PREFLIGHT-FAIL: one or more images are neither local nor saved. Refusing teardown." >&2
    echo "  Pull/build/save the MISS lines above, then re-run. NEVER down -v the only stand first." >&2
    return 1
  fi
  echo "PREFLIGHT-OK: every image is local; large bases saved to $SAVE_DIR."
}

wait_healthy() {
  echo "=== waiting for >= $MIN_HEALTHY healthy containers ==="
  local i h
  for i in $(seq 1 60); do
    h="$(docker ps --format '{{.Status}}' | grep -c '(healthy)')"
    [ "$h" -ge "$MIN_HEALTHY" ] && break
    sleep 10
  done
  h="$(docker ps --format '{{.Status}}' | grep -c '(healthy)')"
  docker ps --format '{{.Names}}\t{{.Status}}' | sort
  echo "healthy=$h"
  [ "$h" -ge "$MIN_HEALTHY" ]
}

ladder() {
  echo "=== acceptance ladder ==="
  echo "-- model-config re-bake (init.sh, zero manual steps) --"
  docker logs "${PROJECT}-open-webui-1" 2>&1 | grep -iE 'system.prompt|catalog|seed|bake' | tail -6 || true
  echo "-- guest exec + storage (run the I/J journeys for the wire) --"
  echo "   pytest deploy/tests/journeys -k fleet   # against this cold-booted stack"
}

case "${1:-full}" in
  preflight) preflight ;;
  ladder)    ladder ;;
  full)
    preflight || exit 1
    echo "=== down -v (reconstruction proven; safe to destroy) ==="
    dc down -v
    echo "=== up -d --no-build ==="
    dc up -d --no-build
    wait_healthy && ladder
    ;;
  *) echo "usage: $0 {preflight|full|ladder}" >&2; exit 2 ;;
esac
