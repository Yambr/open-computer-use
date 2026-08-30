#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
#
# Journey 2 — "upload a file, edit it in the guest, download the result".
#
# Watchable narration of the fleet path a user's file takes:
#   upload lands on the read-only uploads mount -> guest reads it -> guest
#   transforms it and writes to the read-write outputs mount -> read the result
#   back.
#
# Honest demo (see ../FINDINGS.md): the uploads mount is readonly:true (dir 0555
# / file 0444) and the outputs mount readonly:false (dir 0755 / file 0644); this
# shows the guest reading inputs and writing outputs through the real FUSE mount.
# The read-back leg hits the same stand-in storage-write-plane limit as journey
# 1, shown rather than faked.
#
# Runs INSIDE Lima (Ed25519 client cert). The uploads-surface WRITE half is the
# north Files-API in the full stack; this demo drives the in-guest read/write
# split that a user's edit-in-place produces.
set -uo pipefail
PKI=${PKI:-"/home/nick.guest/fleet-stage/open-computer-use/deploy/fleet/gateway-pki"}
BASE=${BASE:-https://127.0.0.1:9466}
IMAGE=${GUEST_IMAGE:-ocu-guest:assembled-demo}
FSID=${FSID:-fs-fleet}
HINT="journey2-edit-$(date +%s)"
CURL="curl -sS --max-time 45 --cacert $PKI/ca.pem --cert $PKI/client.pem --key $PKI/client.key"

echo "############################################################"
echo "# JOURNEY 2 — upload -> edit-in-guest -> download the result"
echo "#   hint=$HINT  image=$IMAGE"
echo "############################################################"; echo

echo "=== STEP 1 — CREATE a storage session (uploads :ro + outputs :rw) ==="
BODY="{\"session_hint\":\"$HINT\",\"image\":\"$IMAGE\",\"mount_intent\":{\"destination\":\"/mnt/user-data/outputs/\",\"filesystem_id\":\"$FSID\",\"read_only\":false,\"cache_duration_s\":3600},\"egress_policy\":{\"default_deny\":true,\"allowed_upstream\":\"https://edge:8450\",\"filesystem_id\":\"$FSID\"}}"
CREATE=$($CURL -w "\n__HTTP_%{http_code}__" -X POST "$BASE/v1alpha/sessions" -H "content-type: application/json" -d "$BODY")
echo "$CREATE" | grep -q "__HTTP_201__" || { echo "CREATE FAILED"; exit 1; }
echo "   >>> session created (201)"; echo
sleep 5

echo "=== STEP 2 — the guest READS the uploads surface (:ro, dir 0555) ==="
# The uploads mount is the read-only user-input surface. A write there must be
# refused (EROFS) — the read/write posture split is the invariant.
RO=$($CURL -X POST "$BASE/v1alpha/sessions/exec" -H "content-type: application/json" \
  -d "{\"session_hint\":\"$HINT\",\"argv\":[\"/bin/busybox\",\"sh\",\"-c\",\"/bin/busybox ls -la /mnt/user-data/uploads/ 2>&1; echo rc=\$?\"]}")
echo "$RO" | grep -o "\"stdout_b64\":\"[^\"]*\"" | sed "s/.*:\"//;s/\"//" | base64 -d 2>/dev/null | sed "s/^/     /"
echo

echo "=== STEP 3 — the guest EDITS: transform to uppercase, write to outputs (:rw) ==="
EDIT="printf 'edited by the guest\\n' | /bin/busybox tr a-z A-Z > /mnt/user-data/outputs/edited.txt && /bin/busybox cat /mnt/user-data/outputs/edited.txt"
E=$($CURL -X POST "$BASE/v1alpha/sessions/exec" -H "content-type: application/json" \
  -d "{\"session_hint\":\"$HINT\",\"argv\":[\"/bin/busybox\",\"sh\",\"-c\",\"$EDIT\"]}")
echo "$E" | grep -o "\"stdout_b64\":\"[^\"]*\"" | sed "s/.*:\"//;s/\"//" | base64 -d 2>/dev/null | sed "s/^/     /"
echo

echo "=== STEP 4 — DOWNLOAD the result (read outputs back through FUSE) ==="
R=$($CURL -X POST "$BASE/v1alpha/sessions/exec" -H "content-type: application/json" \
  -d "{\"session_hint\":\"$HINT\",\"argv\":[\"/bin/busybox\",\"cat\",\"/mnt/user-data/outputs/edited.txt\"]}")
CONTENT=$(echo "$R" | grep -o "\"stdout_b64\":\"[^\"]*\"" | sed "s/.*:\"//;s/\"//" | base64 -d 2>/dev/null)
echo "  read-back: [${CONTENT}]"
if [ "$CONTENT" = "EDITED BY THE GUEST" ]; then
  echo "  ✅ the edited result round-tripped — the edit journey completes"
else
  echo "  ⚠️  read-back did NOT return the edited bytes — the storage-write-plane"
  echo "     finding (../FINDINGS.md #1). The read/write posture split and the"
  echo "     in-guest transform run; the read-back is where the stand-in stops."
fi
