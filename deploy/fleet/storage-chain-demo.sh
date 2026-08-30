#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
#
# Firsthand end-to-end proof of the storage chain against a running fleet:
#   gateway create (mTLS) -> control materialize -> gVisor guest (runsc-fuse,
#   guest agent PID1 + co-located rclone mount boot-child) -> FUSE write into
#   /mnt/user-data/outputs -> egress edge (validate/exchange/inject) -> filestore
#   -> MinIO S3 object. Prints each hop and asserts the object landed.
#
# Requires the demo guest image (a static busybox layered over the assembled
# substrate so a write goes through the real FUSE mount from inside the guest;
# the canonical substrate is distroless and carries no coreutils — production
# task rootfs images carry their own tooling per the ADR-0020 provisioning
# ladder). Build it first:
#   docker build --build-arg ASSEMBLED_IMAGE=ocu-guest:assembled-p2scrub \
#     --build-arg BUSYBOX_IMAGE=busybox:1.36-musl \
#     -f deploy/guest-image/Dockerfile.demo -t ocu-guest:assembled-demo \
#     deploy/guest-image
#
# PKI dir holds the gateway mTLS client cert/key + CA (one client cert = one
# host-attested caller). Override PKI/BASE for a different checkout or endpoint.
set -uo pipefail
PKI=${PKI:-"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/gateway-pki"}
BASE=https://127.0.0.1:9466
HINT="storage-live-$(date +%s)"
FNAME="live-proof-$(date +%s).txt"
GUEST_IMAGE="ocu-guest:assembled-demo"
CURL="curl -sS --max-time 40 --cacert $PKI/ca.pem --cert $PKI/client.pem --key $PKI/client.key"

echo "############################################################"
echo "# FULL STORAGE CHAIN — firsthand, live fleet"
echo "#   hint=$HINT  file=$FNAME  image=$GUEST_IMAGE"
echo "############################################################"; echo
echo "=== STEP 1 — CREATE storage session (image + mount_intent + egress_policy) ==="
BODY="{\"session_hint\":\"$HINT\",\"image\":\"$GUEST_IMAGE\",\"mount_intent\":{\"destination\":\"/mnt/user-data/outputs/\",\"filesystem_id\":\"fs-fleet\",\"read_only\":false,\"cache_duration_s\":3600},\"egress_policy\":{\"default_deny\":true,\"allowed_upstream\":\"https://edge:8450\",\"filesystem_id\":\"fs-fleet\"}}"
CREATE=$($CURL -w "\n__HTTP_%{http_code}__" -X POST "$BASE/v1alpha/sessions" -H "content-type: application/json" -d "$BODY")
echo "$CREATE"
KEY=$(echo "$CREATE" | grep -o "\"key\":\"[^\"]*\"" | head -1 | sed "s/.*:\"//;s/\"//")
[ -z "$KEY" ] && { echo "CREATE FAILED"; exit 1; }
echo "   >>> key=$KEY"; echo
echo "=== STEP 2 — gVisor guest UP + boot-child FUSE mount ready ==="
sleep 5
CNAME="ocu-sess-$KEY"
docker ps --filter "name=$CNAME" --format "  {{.Names}} | {{.Status}}"
echo "  runtime=$(docker inspect "$CNAME" --format "{{.HostConfig.Runtime}}")  net=$(docker inspect "$CNAME" --format "{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}}{{end}}")"; echo
echo "=== STEP 3 — WRITE a file through the FUSE mount (busybox in-guest, open/write) ==="
EXECBODY="{\"session_hint\":\"$HINT\",\"argv\":[\"/bin/busybox\",\"sh\",\"-c\",\"echo live-fleet-proof-through-FUSE > /mnt/user-data/outputs/$FNAME && /bin/busybox ls -la /mnt/user-data/outputs/\"]}"
EXEC=$($CURL -w "\n__HTTP_%{http_code}__" -X POST "$BASE/v1alpha/sessions/exec" -H "content-type: application/json" -d "$EXECBODY")
echo "$EXEC"
B64=$(echo "$EXEC" | grep -o "\"stdout_b64\":\"[^\"]*\"" | sed "s/.*:\"//;s/\"//")
[ -n "${B64:-}" ] && echo "  >>> guest stdout:" && echo "$B64" | base64 -d 2>/dev/null | sed "s/^/     /"
echo
echo "=== STEP 4 — object LANDED in MinIO (S3 backend) ==="
sleep 3
docker exec ocu-fleet-minio-1 sh -c "ls -la /data/ocu-fleet/fs-fleet/" | sed "s/^/    /"
docker exec ocu-fleet-minio-1 sh -c "test -d /data/ocu-fleet/fs-fleet/$FNAME" \
  && echo "  ✅ /data/ocu-fleet/fs-fleet/$FNAME EXISTS — FULL CHAIN PROVEN LIVE" \
  || echo "  ❌ $FNAME NOT in MinIO"
