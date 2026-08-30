#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
#
# Cosign-verify every digest-pinned image the published override
# (docker-compose.published.yml) boots, BEFORE any `up`. Fail-closed: any
# verification failure exits 1 and nothing should be started.
#
# The digest references are parsed OUT OF the override file, so the set that
# is verified is exactly the set that boots - bumping a digest in the compose
# file is enough, there is no second list to drift out of sync. What the
# script must know per image is only WHO may have signed it: the keyless
# signing identity (the publishing repo's release workflow at a v* tag,
# asserted by the GitHub-Actions OIDC issuer). An image whose identity is not
# mapped below fails closed - an unknown artifact is never bootable just
# because it carries some valid signature.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OVERRIDE="${1:-${HERE}/../docker-compose.published.yml}"

ISSUER="https://token.actions.githubusercontent.com"

# Keyless signing identity per image repository: the workflow ref that is
# allowed to have signed it. Anchored on both ends; the tag stays a pattern
# (the digest already pins the exact artifact, the identity pins the signer).
identity_for() {
  case "$1" in
    ghcr.io/wide-moat/ocu-filestore)
      echo '^https://github\.com/Wide-Moat/ocu-filestore/\.github/workflows/release\.yml@refs/tags/v.*$'
      ;;
    *)
      echo ""
      ;;
  esac
}

if ! command -v cosign >/dev/null 2>&1; then
  echo "cosign not found. Install it first (brew install cosign / https://docs.sigstore.dev)." >&2
  exit 2
fi
if [ ! -f "$OVERRIDE" ]; then
  echo "published override not found at ${OVERRIDE}" >&2
  exit 2
fi

# Every image reference in the override, digest-pinned or not. A published
# service referencing a mutable tag (no @sha256) is itself a failure: the
# verified artifact and the booted artifact could then differ.
mapfile -t refs < <(grep -Eo 'image:[[:space:]]*[^[:space:]]+' "$OVERRIDE" | awk '{print $2}')
if [ "${#refs[@]}" -eq 0 ]; then
  echo "no image references found in ${OVERRIDE} - nothing to verify is a failure, not a pass" >&2
  exit 1
fi

rc=0
for ref in "${refs[@]}"; do
  case "$ref" in
    *@sha256:*) ;;
    *)
      echo "FAIL: ${ref} is not digest-pinned (@sha256:...) - a mutable tag cannot be verified-then-booted safely" >&2
      rc=1
      continue
      ;;
  esac
  repo="${ref%%@*}"
  ident="$(identity_for "$repo")"
  if [ -z "$ident" ]; then
    echo "FAIL: no signing identity mapped for ${repo} - add it to identity_for() with the publishing workflow ref" >&2
    rc=1
    continue
  fi
  echo "--- cosign verify ${ref}"
  if out="$(cosign verify \
      --certificate-oidc-issuer "$ISSUER" \
      --certificate-identity-regexp "$ident" \
      "$ref" 2>&1)"; then
    echo "OK: signature verified against ${ident}"
  else
    echo "FAIL: cosign verification failed for ${ref}:" >&2
    printf '%s\n' "$out" | tail -5 >&2
    rc=1
  fi
done

if [ "$rc" -ne 0 ]; then
  echo "verify-published-images: FAILED - do not boot the published override" >&2
  exit 1
fi
echo "verify-published-images: all published images verified"
