<!-- SPDX-License-Identifier: FSL-1.1-Apache-2.0 -->
<!-- Copyright (c) 2025 Open Computer Use Contributors -->

# Fleet assembly

Wires the six next/v1 components into one running deployment. This is the
enterprise-architecture (`next/v1`) assembly — distinct from the
proof-of-concept `docker-compose.yml` at the repository root, which stays in
place and untouched.

## Fleet vs PoC

| | PoC (`/docker-compose.yml`) | Fleet (`deploy/fleet/`) |
|---|---|---|
| Components | MCP server + workspace image | The six `next/v1` components |
| Storage | local workspace volume | object-store service + real S3 (MinIO) |
| Auth | none | embed-token verify + first-party session |
| Egress | none | trust-edge (south mount leg) |
| Audience | local experimentation | the enterprise architecture under assembly |

The PoC keeps working as-is. Migration is a move-over, not a cut-over: run the
fleet stack alongside the PoC, point traffic at it when ready, retire the PoC
compose last.

## What runs live today

| Seam | Status |
|---|---|
| F9 north — web UI → object-store `/v1/files` | live: real HTTP, keystone-404, MinIO backend |
| control → sandbox guest (create → exec → destroy) | live: `octl` raw smoke, runc × scratch |
| south mount — guest → edge → object-store | exchange semantics live-proven on the Go edge; the stock-Envoy container hop is Phase F (see below) |

## South mount leg — Phase E vs Phase F

The weak-session-JWT → real-credential exchange that the south mount leg
depends on has two realizations:

- **Phase E (live-proven).** The exchange chain — real JWKS verification, real
  RFC-8693 token exchange keyed on `filesystem_id`, real strip-and-inject —
  runs on a Go edge (`ocu-rclone-filestore` `test/harness/cmd/edge` +
  `edgeglue`). The mount leg's behavior is proven against it.
- **Phase F (deferred).** Production uses stock Envoy (`envoy.yaml`, the SDS
  secret `filestore_exchanged_credential`). The live `envoyproxy/envoy`
  container hop is not yet run. The missing winch is an SDS source serving the
  exchanged credential keyed on the validated `filesystem_id` (an HTTP→SDS shim
  for a single-`filesystem_id` demo; a multi-`filesystem_id` SDS is the
  real-deployment follow-up).

The fleet south leg runs the Go edge — the same chain, the same semantics —
flagged Phase F for the literal stock-Envoy container. Nothing here claims the
stock Envoy hop runs live, because it does not yet.

## Networks

| Network | Members | Purpose |
|---|---|---|
| `ocu-frontend` | web UI, external client | the embeddable UI surface |
| `ocu-north` | web UI, object-store north | F9 no-credential Files-API leg |
| `ocu-mount-facing` | guest mount, edge | the guest's only route out (south leg) |
| `ocu-edge-backend` | edge, object-store south, control JWKS, exchange, MinIO | the credential-bearing plane; the guest has no membership |

The guest sits on `ocu-mount-facing` only — it has no route to the object-store
south face, control, the exchange peer, or MinIO. The single-hop invariant.

## TLS

One leaf, two listeners: the object-store service's north (`:7080`) and south
(`:8444`) faces share one certificate whose SAN covers `filestore` and
`ocu-filestore`. The `cert-init` one-shot mints it. The web UI trusts that leaf
via `NODE_EXTRA_CA_CERTS` (the CA is mounted, never baked, and certificate
verification is never disabled).

## Bring-up

The web UI BFF refuses to start without a real embed-verify and session secret
(no default — a default-keyed deployment would accept forged embed tokens), so
provide an env file first:

```
cp deploy/fleet/.env.example deploy/fleet/.env
# set OCU_EMBED_VERIFY_SECRET and OCU_SESSION_SECRET (openssl rand -hex 32 each)
# on a native Linux / Lima dockerd (not Docker Desktop), also set the socket gid:
#   echo "OCU_DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)" >> deploy/fleet/.env
docker compose -f deploy/fleet/docker-compose.fleet.yml --env-file deploy/fleet/.env \
  up -d --build --wait
```

Control runs as uid 65532 and reads the Docker socket for the per-session
container lifecycle. Under Docker Desktop the socket is root-owned and the
default `OCU_DOCKER_GID=0` fits; on a native dockerd the socket has a distinct
`docker` gid, so set `OCU_DOCKER_GID` to it (the line above) or control cannot
dial the daemon and fail-closes at boot.

Control also needs a Storage/Exec-JWT signing key and fail-closes at boot
without one (there is no daemon-default key). The `signing-key-init` one-shot
mints a throwaway Ed25519 PKCS8 key into a shared volume on first `up`, so the
command above works unchanged. For a managed key, write your own PKCS8 PEM key
into that volume as `storage-jwt-signing.key` before the first `up`:

```
docker volume create ocu-fleet_control-signing-key
docker run --rm -v ocu-fleet_control-signing-key:/keys alpine/openssl:latest \
  sh -c 'openssl genpkey -algorithm ED25519 -out /keys/storage-jwt-signing.key && chown 65532:65532 /keys/storage-jwt-signing.key'
```

The object-store engine reaches MinIO over a dedicated `ocu-storage-backend`
network, kept off the credential-bearing south plane. Without it the daemon's
S3 versioning probe cannot dial `minio` and the process fail-closes at boot.

The sandbox guest is not a long-lived service: control creates it per session
through the Docker socket. The standalone sandbox smoke runs through `octl`
(see `ocu-sandbox`).

## Published-artifact path

The default bring-up above builds every OCU service from its sibling checkout
(the dev path). The published path boots services from cosign-verified,
digest-pinned GHCR images instead:

```
deploy/fleet/scripts/verify-published-images.sh    # cosign, fail-closed
docker compose -f deploy/fleet/docker-compose.fleet.yml \
               -f deploy/fleet/docker-compose.published.yml \
               --env-file deploy/fleet/.env up -d --wait
```

The verify script parses the digest references out of
`docker-compose.published.yml` (one source of truth: the set verified is the
set booted), requires every reference to be digest-pinned, and checks each
signature against the publishing repo's release-workflow identity (keyless,
GitHub-Actions OIDC). Any failure - a mutable tag, an unmapped image, a bad
signature - exits 1: do not `up`.

Coverage today is filestore only, at v0.1.0-rc.7 (2026-06-13). That image
predates the credential-claim subtree join, the sha256 dedup surface and the
Storage-JWT verifier, so the journey suite is NOT expected green on this path
until a fresh filestore tag is published. No other component publishes an
image at all. Owner-gated steps to grow this path, in order:

1. Tag a fresh `ocu-filestore` release (its pipeline already signs the image
   by digest) and bump the digest in `docker-compose.published.yml`.
2. Tag the first `ocu-control` release (release.yml exists; no tag has ever
   been pushed, so no image exists).
3. Land publish pipelines in gateway, webui, admin and the rclone edge, then
   join each service to the override.

The acceptance keystone for the whole path: a clean environment runs the
journey suite green with every OCU service booted from a verified published
digest and zero sibling checkouts.

## Durable state

The control plane's session state — the reservation registry, the deny posture,
and the quota counters — is durable in Postgres (`control-db`), not in-memory.
Control opens it via `-state-dsn` and applies its embedded schema idempotently
on boot, so a fresh deployment provisions the three lock-domain tables and an
existing one is a no-op. Session reservations survive a control restart.

Verify the schema provisioned + state survives a restart:

```
docker compose -f deploy/fleet/docker-compose.fleet.yml exec control-db \
  psql -U ocu -d ocu_control -c '\dt'
# -> sessions, denylist, quota_counters

docker compose -f deploy/fleet/docker-compose.fleet.yml exec control-db \
  psql -U ocu -d ocu_control -c \
  "INSERT INTO denylist (scope,key,reason,since) VALUES (0,'probe','x',now());"
docker compose -f deploy/fleet/docker-compose.fleet.yml restart control
docker compose -f deploy/fleet/docker-compose.fleet.yml exec control-db \
  psql -U ocu -d ocu_control -c "SELECT key FROM denylist WHERE key='probe';"
# -> the row survives the daemon restart
```

## Seam smokes

Each data seam has a smoke that reds on a real break — run them after bring-up.

North F9 (web UI → object-store north), from the `ocu-north` network:

```
# keystone: an unknown or cross-scope file_id is 404 not_found, never 403
docker run --rm --network ocu-fleet_ocu-north curlimages/curl -sk \
  -H 'X-OCU-Filesystem-Id: fs-fleet' \
  -o /dev/null -w '%{http_code}\n' https://filestore:7080/v1/files/unknown
# -> 404 (a 403 here would be an enumeration leak)

# the BFF trusts the object-store leaf via NODE_EXTRA_CA_CERTS, not by disabling
# verification — proven from inside the web UI container
docker compose -f deploy/fleet/docker-compose.fleet.yml exec webui \
  node -e 'const https=require("https"),fs=require("fs");
  https.get({host:"filestore",port:7080,path:"/v1/files?limit=1",
  headers:{"X-OCU-Filesystem-Id":"fs-fleet"},ca:fs.readFileSync(process.env.NODE_EXTRA_CA_CERTS)},
  r=>console.log(r.statusCode))'
# -> 200
```

South mount (guest → edge → exchange → south object-store), from
`ocu-mount-facing`, using the weak JWT the harness renders into the shared
volume:

```
# valid weak JWT completes the validate->strip->exchange->inject->route chain
curl -sk --cacert <ca.pem from south-shared> \
  -H "Authorization: Bearer <weak JWT from guest-config.json>" \
  -X POST -d '{"filesystem_id":"fsrw","path":"/"}' \
  https://edge:8450/v1/filestore/fs/listDirectory
# -> 200 ; the same request with no token -> 401
```

Sandbox leg: `octl create --runtime runc --image process_api:prod` →
`octl exec` → `octl destroy` (zero-leak), run in Lima (`ocu-sandbox`,
`make e2e-vm`). The createFile write verb on the north leg is `501` until #304
freezes the upload body; the live read-plane (list, metadata, content, the
keystone) is fully exercised.

## Smoke-wave verdict

Each component carries its own critical-aspect smokes, run firsthand against
the real component (not the fleet stand-ins where those differ — see the live
stack caveats below). Every smoke was proven non-vacuous by a planted mutation
that drove it red before revert.

| Component | Aspects proven (PASS) | Non-vacuity |
|---|---|---|
| filestore (04) | north/south router split (#10: north 404 / south 405); F9 503 fail-closed without scope header, 501 create-fenced (#304), 404 keystone byte-identical for foreign vs unknown fsid; handle-store durability across kill+restart | 2 planted mutations red the keystone + the create-fence tests |
| rclone mount (04) | validate→strip→RFC8693→inject→route swap; weak-JWT matrix on the **live edge** (fsrw=200, no-token=401, forged=401, foreign-scope=403); single-hop proven by L3 route block (backend IPs unreachable from mount-facing); FUSE cap hardening | 3 planted mutations red the swap, the sig check, the cap posture |
| control (02) | killswitch isolation, required-flag boot gate, ADR-0017 no-scope mint refusal, audit-error propagation on destroy-deny; live `ocu-controld` 0.0.0.0 bind fail-closes 401 on unattested caller; distroless image (no shell) | 4 planted mutations each red their aspect |
| webui (08) | proxy runs on the Node runtime (no node:crypto-in-edge); F9 TLS trust via NODE_EXTRA_CA_CERTS; embed-verify boot gate refuses a short key (HTTP 500); live F9 round-trip list=200, keystone=404 | 2 planted mutations + a defanged short-key boot |
| admin | every Constitution "never" (BFF→authority import, `.sock` leak, gate fail-open, JWT alg-pin drop, cookie `Secure`/`SameSite` drop, config fallback); build, typecheck, 40/40 vitest, Stryker 92.45% | 6 planted defects each red their guard |

### Live stack caveats (honest)

- **filestore** — the live fleet container now runs the F9 north plane (`:7080`)
  and stays healthy; the S3 dial it crashed on at first bring-up is fixed (the
  `ocu-storage-backend` network). The live F9 round-trip above (list=200,
  keystone=404) is proven from inside the web UI container.
- **control** — the live fleet `control-plane` container is the south-credential
  harness stand-in (mint + JWKS only), not this repo's `ocu-controld`. The
  control invariants are smoked against the real daemon directly; smoking the
  stand-in would be a fake-green.
- **admin** — not in the fleet compose and has no Dockerfile; its operator
  read-surface (ADR-0022) is unbuilt, so it is correctly absent from the live
  data path. Its guards are smoked in-repo.
- **sandbox** — the live FUSE/runtime e2e needs `/dev/fuse` + runsc, which live
  on Lima `ocu-linux`, not the Darwin Docker host the fleet runs on. The leg is
  proven through `octl` in Lima (above), not the Darwin stack.

## Running the journey suite

The PoC-vs-fleet journeys (`deploy/tests/journeys/`) need `pytest` + `pyyaml`;
everything else they use is stdlib. From a clean clone with the fleet up:

The gateway auth-edge journeys (group H) + the tool-surface journeys (group I)
need a minted boot-set + bearer first — render them with the vendored minter.
`--deployment` MUST equal the gateway's `-deployment` (the fleet compose runs
`fleet-local`; a foreign-deployment record 401s, ADR-0027). The minter prints the
plaintext bearer to stdout; the tests read it from a sibling `bearer.txt`, so
capture the last printed line there:

```bash
out=deploy/fleet/secrets/gateway
mkdir -p "$out"
python3 deploy/fleet/scripts/mint_boot_set.py \
  --deployment fleet-local --out-dir "$out" > /tmp/mint.out
tail -1 /tmp/mint.out > "$out/bearer.txt"   # the printed bearer is the last line
```

The gateway also bind-mounts a provisioning policy from the same directory.
It carries no secrets (it lives there only to share the mount root); a clean
clone copies the tracked fixture, which pins `exec_timeout_seconds: 55`. The
gateway's built-in default is 30s; the exec channel drops any command silent
for 60s (a host-side idle-read window, tracked in issue #145), so 55 is the
honest ceiling until that lands - a longer value lets a silent command past
60s lose its result to a 502. The fixture's `cpu_cores: 2` is intentional
headroom over the PoC's 1.0.

The fixture provisions TWO storage mounts (`mount_intents`): the guest sees
`/mnt/user-data/uploads` (read-only; chat attachments and Files-panel uploads)
and `/mnt/user-data/outputs` (read-write; agent deliverables, listable by the
writer, served for download). Each mount's credential carries its own intent
claim; the engine (`-claims-bind` on the `filestore` service) joins every op
under the claim's subtree - `read -> uploads/`, `write -> outputs/` (ADR-0029).
This is the PoC guest contract (`docker_manager.py` binds the same two paths):

```bash
cp deploy/fleet/fixtures/provisioning-policy.json "$out/provisioning-policy.json"
```

The gateway loads the boot-set at boot, so after (re-)minting, recreate it to
pick up the new set: `docker compose up -d --force-recreate --no-deps mcp-gateway`.

The Open WebUI chat leg holds the SAME bearer in its tool Valve (seeded from
`MCP_API_KEY` in `.env` on first boot). After a re-mint, update it too or every
chat tool-call dies 401 behind the MCP SDK's opaque transport error while the
journey suite stays green:

```bash
sed -i "s|^MCP_API_KEY=.*|MCP_API_KEY=$(cat "$out/bearer.txt")|" deploy/fleet/.env
docker compose up -d --force-recreate --no-deps open-webui
docker compose exec open-webui rm -f /app/backend/data/.computer-use-initialized
docker compose restart open-webui   # init re-runs and re-seeds the Valve
```

Then install the test deps and run the suite:

```bash
python3 -m venv .venv
.venv/bin/pip install -r deploy/tests/journeys/requirements.txt
.venv/bin/pytest deploy/tests/journeys
```

Groups A–G run against the live fleet or loud-skip when a stand is absent (never
a silent pass); group H is the MCP gateway auth edge; group I is the MCP
tool-surface below the exec contract.

Expected outcome (so honest-green is distinguishable from green-by-skip): with a
python3-bearing guest, H + I = **13 passed, 0 skipped**; with the stripped
default guest, I4/I5/I6 loud-skip and the total is **10 passed + 3 skipped**. A
skip on H (or on I1/I2/I3) means the boot-set or the stand is not wired, not a
pass.

The file-tool legs (I4/I5/I6) need a guest that bears python3, `sh`, and `cat`.
The stripped default (`ocu-guest:assembled`) runs the bash legs only. Build a
fat guest by layering the assembly Dockerfile over the PoC userland base (the
repo-root `Dockerfile`, an Ubuntu 24.04 image with python3), then point `.env`
at it:

```bash
# 1. the fat userland base (repo root); --platform per repo policy, drop it
#    when building natively on Lima arm64
docker build --platform linux/amd64 -t ocu-poc-fat:local .
# 2. layer the guest agent + co-located mount over that base
docker build \
  --build-arg AGENT_IMAGE=<guest-agent-image> \
  --build-arg MOUNT_IMAGE=<rclone-filestore-image> \
  --build-arg BASE_IMAGE=ocu-poc-fat:local \
  -f deploy/guest-image/Dockerfile -t ocu-guest:poc-fat deploy/guest-image
# 3. select it for the demo stand
echo 'OCU_GUEST_IMAGE=ocu-guest:poc-fat' >> deploy/fleet/.env
```

The demo default guest bearing python3 is tracked as #345; until it lands, the
build above is the documented path to the full group-I run.
