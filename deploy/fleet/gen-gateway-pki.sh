#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
#
# Generate the gateway<->control mTLS PKI for a LOCAL fleet bring-up. The
# private keys are dev-only and are NEVER committed (see .gitignore); this
# script regenerates them per checkout so a clone carries no key material.
#
# It mints three things into ./gateway-pki/:
#   - ca.pem / ca.key          a self-signed dev CA (Ed25519)
#   - server.pem / server.key  the control gateway-plane leaf, SAN
#                              DNS:control, DNS:localhost, IP:127.0.0.1
#                              (serverAuth) — what control presents on :9466
#   - client.pem / client.key  the MCP-gateway caller leaf, SAN
#                              URI:spiffe://ocu-fleet/internal-workforce/mcp-gateway
#                              (clientAuth) — what the gateway presents dialing in
#
# The URI SAN is the identity control's CertSANResolver maps to
# Identity{Tenant: internal-workforce, Caller: mcp-gateway}. Changing it here
# without changing the resolver breaks admission — keep them in lockstep.
#
# Usage:  ./gen-gateway-pki.sh            # idempotent: skips if certs present
#         ./gen-gateway-pki.sh --force    # re-mint from scratch

set -euo pipefail
cd "$(dirname "$0")"

PKI_DIR="gateway-pki"
FORCE="${1:-}"

if [[ "$FORCE" == "--force" ]]; then
  rm -rf "$PKI_DIR"
fi

if [[ -f "$PKI_DIR/server.pem" && -f "$PKI_DIR/client.pem" && -f "$PKI_DIR/ca.pem" ]]; then
  echo "gateway-pki: certs already present in $PKI_DIR (pass --force to re-mint)"
  exit 0
fi

mkdir -p "$PKI_DIR"
cd "$PKI_DIR"

# --- CA (Ed25519, self-signed) ---
openssl genpkey -algorithm ed25519 -out ca.key
openssl req -x509 -new -key ca.key -sha256 -days 30 \
  -subj "/CN=ocu-fleet-gateway-dev-ca" -out ca.pem

# --- server leaf (control gateway plane, serverAuth) ---
cat > server.cnf <<'EOF'
[req]
distinguished_name = dn
req_extensions = v3
prompt = no
[dn]
CN = control-gateway
[v3]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:control, DNS:localhost, IP:127.0.0.1
EOF
openssl genpkey -algorithm ed25519 -out server.key
openssl req -new -key server.key -out server.csr -config server.cnf
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -days 30 -extfile server.cnf -extensions v3 -out server.pem

# --- client leaf (MCP-gateway caller, clientAuth, SPIFFE URI SAN) ---
cat > client.cnf <<'EOF'
[req]
distinguished_name = dn
req_extensions = v3
prompt = no
[dn]
CN = mcp-gateway-client
[v3]
basicConstraints = CA:FALSE
keyUsage = digitalSignature
extendedKeyUsage = clientAuth
subjectAltName = URI:spiffe://ocu-fleet/internal-workforce/mcp-gateway
EOF
openssl genpkey -algorithm ed25519 -out client.key
openssl req -new -key client.key -out client.csr -config client.cnf
openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -days 30 -extfile client.cnf -extensions v3 -out client.pem

# Lock down the private keys.
chmod 600 ca.key server.key client.key

echo "gateway-pki: minted CA + server (DNS:control) + client (spiffe://ocu-fleet/internal-workforce/mcp-gateway) into $PWD"
