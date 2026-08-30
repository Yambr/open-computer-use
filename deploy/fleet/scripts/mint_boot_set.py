#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
#
# Vendored into the fleet deploy layer from the ocu-mcp-gateway repo
# (scripts/mint_boot_set.py) — the gateway owns the boot-set minting formula;
# this copy lets a clean clone of THIS repo render the fixture without the
# gateway checkout. Keep in sync if the gateway's hashBearer formula changes.
#
# Mint a valid gateway boot-set (and the companion service-credential and
# provisioning-policy fixtures) for a deployment, so a keyed MCP create is
# reproducible end-to-end in an assembly (e.g. the fleet compose in Lima).
#
# This is the SINGLE source of the boot-set minting formula: the gateway resolves
# a presented "sk-ocu-" bearer by computing sha256(salt || bearer) and matching it
# against a record's key_hash (internal/auth/skkey.go: hashBearer). Rendering the
# artifact by hand risks forking that formula; this script keeps it in one place,
# next to the vendored mcp-key-set.schema.json it validates against.
#
# It is a DEPLOYMENT FIXTURE tool, not a production key service: real deployments
# render the boot-set from the Control-owned key set (P4, ADR-0027). Here the
# operator supplies the plaintext bearer (or lets the script generate one) so an
# assembly test can present that exact key and observe auth pass. The plaintext is
# NEVER written into the boot-set — only the salted hash — mirroring production.
#
# stdlib only (no pip), matching the other scripts in this directory.
#
# Usage:
#   scripts/mint_boot_set.py --deployment fleet-local --out-dir deploy/fleet/secrets/gateway
#     -> writes boot-set.json, service-credential.token, provisioning-policy.json
#        and prints the plaintext bearer (present it as `Authorization: Bearer <it>`).
#   scripts/mint_boot_set.py --deployment fleet-local --bearer sk-ocu-<known> --out-dir /tmp/gw
#     -> uses a caller-supplied bearer instead of generating one.

import argparse
import hashlib
import json
import os
import re
import secrets
import sys

# The vendored key-set schema, resolved relative to this script so the tool works
# from any working directory.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCHEMA = os.path.join(ROOT, "contracts", "mcp", "mcp-key-set.schema.json")

BEARER_PREFIX = "sk-ocu-"


def mint_bearer():
    """Generate a fresh opaque bearer: the sk-ocu- prefix plus 256 bits of
    URL-safe randomness. Matches the minimal-shelf per-caller key shape."""
    return BEARER_PREFIX + secrets.token_urlsafe(32)


def hash_bearer(salt_hex, bearer):
    """sha256(salt_bytes || bearer_ascii), hex-encoded — the EXACT formula the
    gateway uses to resolve a presented bearer (internal/auth/skkey.go)."""
    salt = bytes.fromhex(salt_hex)
    h = hashlib.sha256()
    h.update(salt)
    h.update(bearer.encode("ascii"))
    return h.hexdigest()


def _record(bearer, deployment, tenant, key_id, created_at):
    """One active boot-set record resolving the given bearer."""
    salt_hex = secrets.token_bytes(16).hex()  # >= 8 bytes, satisfies the schema
    return {
        "key_id": key_id,
        "key_hash": hash_bearer(salt_hex, bearer),
        "salt": salt_hex,
        "tenant": tenant,
        "deployment": deployment,
        "status": "active",
        "created_at": created_at,
    }


# Callers that only need to LEARN which storage scope a chat is bound to, never to
# execute a tool: the embed portal (to mint a pane token for the right subtree) and
# the chat download-link filter (to build /download/{scope}/{name}). Each gets a
# credential of its own — two components sharing one cannot be told apart in an
# audit trail — and the gateway confines both to resolve_scope via
# -resolve-only-key-ids. They stay in the CALLER'S TENANT: the gateway derives its
# session hint from the resolved principal's tenant, so a foreign-tenant key would
# resolve a different session and hand back a scope matching no guest. Narrow the
# tool set, never the tenant.
RESOLVE_ONLY_KEY_IDS = ("kid-portal-resolve", "kid-filter-resolve")


def build_boot_set(bearer, deployment, tenant, key_id, created_at):
    """Build an active boot-set that resolves the given bearer for the given
    deployment, plus one resolve-only record per RESOLVE_ONLY_KEY_IDS. A record
    whose deployment does not match the set's deployment fails to resolve
    (ADR-0027 absent-from-set 401), so all share the deployment here.

    The resolve-only bearers are returned alongside so the caller can write them
    where the portal and the filter read them; they are never stored in the
    boot-set, only their salted hashes."""
    records = [_record(bearer, deployment, tenant, key_id, created_at)]
    resolve_only = {}
    for kid in RESOLVE_ONLY_KEY_IDS:
        b = mint_bearer()
        resolve_only[kid] = b
        records.append(_record(b, deployment, tenant, kid, created_at))
    return {"version": 1, "records": records}, resolve_only


def provisioning_policy():
    """A minimal admissible deployment provisioning policy: a non-Unspecified
    trust profile, a well-formed mount, a default-deny egress, and a set pids cap
    (an unset pids_limit boot-refuses at the gateway). Mirrors the vocabulary of
    internal/config/provisioning.go."""
    return {
        "workload_trust_profile": "internal_workforce",
        "mount_intent": {
            "destination": "/workspace",
            "filesystem_id": "fs-fleet",
            "read_only": False,
        },
        "egress_policy": {"default_deny": True},
        "resource_caps": {
            "cpu_cores": 2,
            "memory_bytes": 2147483648,
            "pids_limit": 512,
        },
    }


def validate_against_schema(boot_set):
    """Best-effort structural validation against the vendored schema WITHOUT a
    third-party validator (stdlib only): check the const version, minItems, the
    required record fields, and the hash/salt/status patterns the gateway relies
    on. This catches a minting regression before the artifact ever reaches a
    gateway; it is not a full JSON-Schema engine."""
    with open(SCHEMA, encoding="utf-8") as f:
        schema = json.load(f)
    defs = schema["$defs"]
    required = defs["HashedKeyRecord"]["required"]
    hash_pat = re.compile(defs["KeyHash"]["pattern"])
    salt_pat = re.compile(defs["Salt"]["pattern"])

    if boot_set.get("version") != 1:
        raise ValueError("boot-set version must be the const 1")
    records = boot_set.get("records")
    if not isinstance(records, list) or len(records) < 1:
        raise ValueError("boot-set records must be a non-empty array (minItems 1)")
    for i, rec in enumerate(records):
        for field in required:
            if field not in rec:
                raise ValueError(f"record {i} missing required field {field!r}")
        if rec["status"] != "active":
            raise ValueError(f"record {i} status must be the const 'active'")
        if not hash_pat.match(rec["key_hash"]):
            raise ValueError(f"record {i} key_hash is not 64 lowercase hex chars")
        if not salt_pat.match(rec["salt"]):
            raise ValueError(f"record {i} salt is not >= 8 hex-encoded bytes")


def write_file(path, content, mode=0o600):
    """Write content to path with a restrictive mode (secret material)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(path, mode)


def main(argv):
    ap = argparse.ArgumentParser(description="Mint a gateway boot-set fixture.")
    ap.add_argument(
        "--deployment",
        required=True,
        help="the deployment scope; MUST equal the gateway's -deployment (a foreign-deployment record 401s, ADR-0027)",
    )
    ap.add_argument(
        "--out-dir",
        required=True,
        help="directory to write boot-set.json, service-credential.token, provisioning-policy.json",
    )
    ap.add_argument(
        "--bearer",
        default=None,
        help="present this exact sk-ocu- bearer (default: generate a fresh one and print it)",
    )
    ap.add_argument("--tenant", default="tenant-fixture", help="the record's tenant (session-scoping principal)")
    ap.add_argument("--key-id", default="kid-fixture-1", help="the record's key_id")
    ap.add_argument(
        "--service-token",
        default="gateway-service-token-fixture",
        help="the gateway's own F5 service credential (the Generic internal token presented to Control)",
    )
    ap.add_argument(
        "--created-at",
        default="2026-01-01T00:00:00Z",
        help="the record's created_at (RFC 3339)",
    )
    args = ap.parse_args(argv)

    bearer = args.bearer or mint_bearer()
    if not bearer.startswith(BEARER_PREFIX):
        ap.error(f"--bearer must start with {BEARER_PREFIX!r}")

    boot_set, resolve_only = build_boot_set(
        bearer, args.deployment, args.tenant, args.key_id, args.created_at
    )
    validate_against_schema(boot_set)

    os.makedirs(args.out_dir, exist_ok=True)
    write_file(os.path.join(args.out_dir, "boot-set.json"), json.dumps(boot_set, indent=2) + "\n")
    # The resolve-only bearers DO go to files: the portal and the filter read them
    # from a path rather than an environment value, because a container's
    # environment is readable by anything that can inspect it. They are
    # credentials, so they land beside the boot-set in the gitignored secrets
    # directory and never in an artifact that is committed or printed.
    for kid, b in resolve_only.items():
        name = "portal-bearer.txt" if "portal" in kid else "filter-bearer.txt"
        write_file(os.path.join(args.out_dir, name), b + "\n")
    write_file(os.path.join(args.out_dir, "service-credential.token"), args.service_token + "\n")
    write_file(
        os.path.join(args.out_dir, "provisioning-policy.json"),
        json.dumps(provisioning_policy(), indent=2) + "\n",
    )

    # The plaintext bearer goes to stdout ONLY (never into an artifact), for the
    # operator to present as the Authorization header. The boot-set holds only the
    # salted hash.
    print(f"deployment: {args.deployment}")
    print(f"out-dir:    {args.out_dir}")
    print("present this bearer as `Authorization: Bearer <it>`:")
    print(bearer)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
