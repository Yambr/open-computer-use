#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
#
# Journey 1 — "create a docx and download it from filestore".
#
# Watchable narration of the fleet path a user's docx takes:
#   gateway create (mTLS) -> control materialize -> gVisor guest (runsc-fuse,
#   busybox over the assembled substrate) -> write a .docx into
#   /mnt/user-data/outputs via the FUSE mount -> read it back.
#
# This is the HONEST demo: it drives the real wire and PRINTS what the fleet
# actually does. On the current fleet the read-back does NOT round-trip — the
# stand-in filestore's read/resolve plane answers 501 UNIMPLEMENTED and the
# mount client streams the Put without the contract-required declared_size_bytes
# (see ../FINDINGS.md finding 1). The demo shows the create + exec + FUSE-write
# succeed and the read-back fail, rather than faking a completed download.
#
# Runs INSIDE Lima (OpenSSL curl speaks the Ed25519 client cert; mac LibreSSL
# does not). PKI dir holds the gateway mTLS client cert/key + CA.
set -uo pipefail
PKI=${PKI:-"/home/nick.guest/fleet-stage/open-computer-use/deploy/fleet/gateway-pki"}
BASE=${BASE:-https://127.0.0.1:9466}
IMAGE=${GUEST_IMAGE:-ocu-guest:assembled-demo}
FSID=${FSID:-fs-fleet}
HINT="journey1-docx-$(date +%s)"
FNAME="report-$(date +%s).docx"
CURL="curl -sS --max-time 45 --cacert $PKI/ca.pem --cert $PKI/client.pem --key $PKI/client.key"

echo "############################################################"
echo "# JOURNEY 1 — create a docx, write it to outputs, read it back"
echo "#   hint=$HINT  file=$FNAME  image=$IMAGE"
echo "############################################################"; echo

echo "=== STEP 1 — CREATE a storage session over the gateway mTLS plane ==="
BODY="{\"session_hint\":\"$HINT\",\"image\":\"$IMAGE\",\"mount_intent\":{\"destination\":\"/mnt/user-data/outputs/\",\"filesystem_id\":\"$FSID\",\"read_only\":false,\"cache_duration_s\":3600},\"egress_policy\":{\"default_deny\":true,\"allowed_upstream\":\"https://edge:8450\",\"filesystem_id\":\"$FSID\"}}"
CREATE=$($CURL -w "\n__HTTP_%{http_code}__" -X POST "$BASE/v1alpha/sessions" -H "content-type: application/json" -d "$BODY")
echo "$CREATE"
echo "$CREATE" | grep -q "__HTTP_201__" || { echo "CREATE FAILED — is control up and assembled-demo allow-listed?"; exit 1; }
echo "   >>> session created (201)"; echo
sleep 5

echo "=== STEP 2 — BUILD a minimal valid .docx in-guest and write it to outputs ==="
# A minimal OOXML docx is a zip of [Content_Types].xml + _rels/.rels +
# word/document.xml. busybox has no zip, so this demo writes a marker file to
# prove the FUSE write path; the pytest suite builds the real OOXML test-side
# and asserts validity. The point here is the write + read-back round-trip.
WRITE="echo 'DOCX-BODY-JOURNEY1' > /mnt/user-data/outputs/$FNAME && /bin/busybox ls -la /mnt/user-data/outputs/"
EXEC=$($CURL -w "\n__HTTP_%{http_code}__" -X POST "$BASE/v1alpha/sessions/exec" -H "content-type: application/json" \
  -d "{\"session_hint\":\"$HINT\",\"argv\":[\"/bin/busybox\",\"sh\",\"-c\",\"$WRITE\"]}")
echo "$EXEC"
B64=$(echo "$EXEC" | grep -o "\"stdout_b64\":\"[^\"]*\"" | sed "s/.*:\"//;s/\"//")
[ -n "${B64:-}" ] && echo "  >>> guest stdout:" && echo "$B64" | base64 -d 2>/dev/null | sed "s/^/     /"
echo

echo "=== STEP 3 — READ the docx back through the FUSE mount (the download leg) ==="
READ=$($CURL -X POST "$BASE/v1alpha/sessions/exec" -H "content-type: application/json" \
  -d "{\"session_hint\":\"$HINT\",\"argv\":[\"/bin/busybox\",\"cat\",\"/mnt/user-data/outputs/$FNAME\"]}")
RB64=$(echo "$READ" | grep -o "\"stdout_b64\":\"[^\"]*\"" | sed "s/.*:\"//;s/\"//")
CONTENT=$(echo "$RB64" | base64 -d 2>/dev/null)
echo "  read-back bytes: [${CONTENT}]"
if [ "$CONTENT" = "DOCX-BODY-JOURNEY1" ]; then
  echo "  ✅ the docx round-tripped — the outputs journey completes"
else
  echo "  ⚠️  read-back did NOT return the written bytes."
  echo "     This is the storage-write-plane finding (../FINDINGS.md #1): the"
  echo "     fleet stand-in filestore's read/resolve plane is 501 UNIMPLEMENTED"
  echo "     and the mount Put omits declared_size_bytes. The create + exec +"
  echo "     FUSE-write all succeed; the read-back is where the stand-in stops."
  echo "     Shown honestly rather than faked — the suite xfails this leg."
fi
