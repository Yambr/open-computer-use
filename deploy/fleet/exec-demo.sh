#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
# Live-chain close: create + exec over the gateway mTLS plane with ONE client cert.
# Runs INSIDE Lima (OpenSSL curl speaks Ed25519 client certs; mac LibreSSL does not).
# Path B (Fable-verdict): same cert -> same SAN -> same owner -> DeriveKey lands the
# sibling row created seconds earlier. exec echo hi -> stdout from the live gVisor guest.
set -uo pipefail
PKI=/home/nick.guest/fleet-stage/open-computer-use/deploy/fleet/gateway-pki
BASE=https://127.0.0.1:9466
HINT="live-exec-demo-$(date +%s)"
CURL="curl -sS --max-time 20 --cacert $PKI/ca.pem --cert $PKI/client.pem --key $PKI/client.key"

echo "=================================================================="
echo " STEP 1 — CREATE a session over the gateway mTLS plane (one cert)"
echo "   hint=$HINT  (no mount_intent = compute/exec session, ADR-0017)"
echo "=================================================================="
CREATE=$($CURL -w $n__HTTP_%{http_code}__ -X POST "$BASE/v1alpha/sessions" \
  -H "content-type: application/json" \
  -d "{\"session_hint\":\"$HINT\"}")
echo "$CREATE"
echo ""

echo "=================================================================="
echo " STEP 2 — EXEC echo hi in that guest (SAME cert = SAME owner)"
echo "=================================================================="
EXEC=$($CURL -w $n__HTTP_%{http_code}__ -X POST "$BASE/v1alpha/sessions/exec" \
  -H "content-type: application/json" \
  -d "{\"session_hint\":\"$HINT\",\"argv\":[\"echo\",\"hi\"]}")
echo "$EXEC"
echo ""
STDOUT_B64=$(echo "$EXEC" | grep -o "\"stdout_b64\":\"[^\"]*\"" | sed "s/.*:\"//;s/\"//")
if [ -n "${STDOUT_B64:-}" ]; then
  echo ">>> DECODED stdout from the LIVE gVisor container: [$(echo "$STDOUT_B64" | base64 -d)]"
fi
echo ""

echo "=================================================================="
echo " STEP 3 — NON-VACUOUS PROBES (prove the gate is real, not fake-green)"
echo "=================================================================="
echo "-- 3a: NO client cert -> must be REFUSED (mTLS RequireAndVerify) --"
curl -sS --max-time 10 --cacert $PKI/ca.pem -o /dev/null -w "http=%{http_code} exit=%{exitcode}\n" \
  -X POST "$BASE/v1alpha/sessions/exec" -d "{\"session_hint\":\"$HINT\",\"argv\":[\"echo\",\"hi\"]}" 2>&1 \
  || echo "(TLS handshake refused with no client cert = correct fail-closed)"
echo ""
echo "-- 3b: exec a hint this cert never created -> must 404 (owner-sealed row) --"
$CURL -o /dev/null -w "http=%{http_code}\n" -X POST "$BASE/v1alpha/sessions/exec" \
  -d "{\"session_hint\":\"never-created-by-this-caller\",\"argv\":[\"echo\",\"hi\"]}"
