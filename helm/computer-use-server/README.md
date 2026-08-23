# computer-use-server Helm chart

Deploys the [open-computer-use](https://github.com/Wide-Moat/open-computer-use) orchestrator on Kubernetes. The pod runs the FastAPI MCP server, an inner container engine, and an optional cleanup sidecar. Disposable workspace containers are spawned by that engine — the same architecture as the Docker Compose stack, lifted onto Kubernetes.

> **This copy is ahead of the published chart, and the two render different pods.**
>
> The installation instructions below describe the upstream chart at
> `oci://ghcr.io/wide-moat/charts/computer-use-server`. That is a different artefact from the
> one you are reading. Rendered against this platform's values, published 0.10.2 produces
> `orchestrator, dind, cleanup` with a `var-lib-docker` volume; this copy — and the running
> cluster — produce `orchestrator, podman, cleanup` with `podman-storage`.
>
> Installing from the published chart would therefore detach the Podman volume and put
> Docker-in-Docker back, which is the emergency rollback procedure, not an upgrade. The
> Podman work has not been merged upstream yet; until it is, this vendored copy is the only
> place it exists.

**The engine is rootless Podman**, which runs on a stock node: no privileged container, no `RuntimeClass`, no block storage. It is the only engine this chart renders — the Docker-in-Docker path was removed, not made optional.

Open WebUI is **not** packaged here. It has its own [official chart](https://github.com/open-webui/helm-charts) and most users already run it. See [`examples/helm/with-open-webui/`](../../examples/helm/with-open-webui/README.md) for the integration walkthrough.

---

## Prerequisites

1. **Kubernetes ≥ 1.27** with a working CNI and a default StorageClass that supports `ReadWriteOnce`.
2. **An AppArmor profile permitting user namespaces**, installed on every node that may schedule the pod, and named in `podAnnotations` (`container.apparmor.security.beta.kubernetes.io/podman`). A chart cannot install one. Without it the pod still starts, but the sandboxes get only the cluster's default confinement.
3. **`helm` ≥ 3.14** (Helm 4 also works).
4. The orchestrator and workspace images published to a registry the cluster can pull from.

> **Why Podman by default?** The orchestrator spawns containers inside its own pod, which historically meant `dockerd` in there — and `dockerd` needs either Sysbox or `privileged: true`, the latter giving the inner daemon host-kernel access and trivially breaking pod isolation.
>
> Rootless Podman serves the same Docker API on the same socket, so the application code is unchanged, but needs none of that: no privileged container, no special runtime, no block-mode PVC. It asks a cluster for nothing unusual, which is the difference between a chart you can install and one you have to negotiate for.

---

## Install

### From the public Helm repo (after the first release tag is pushed)

```bash
helm repo add open-computer-use https://wide-moat.github.io/open-computer-use
helm repo update
helm install ocu open-computer-use/computer-use-server \
  --namespace open-computer-use --create-namespace \
  -f my-values.yaml
```

### From the OCI registry (any `v*` tag, including release candidates)

Every `v*` git tag — stable and pre-release — pushes the chart to `oci://ghcr.io/wide-moat/charts/computer-use-server`. Use this path to install an `-rc.N` build for testing without contaminating users on the stable `helm repo`.

The chart and the Docker images use different version strings:

- **`APP_VERSION`** (Docker image tags + chart `appVersion`): full 4-segment app version, e.g. `0.9.2.5-rc.1`. Comes directly from the git tag.
- **`CHART_VERSION`** (Helm chart `version`, what `helm install --version` resolves): strict 3-segment SemVer, e.g. `0.9.2-rc.1`. The 4th segment of the app version is dropped because Helm rejects 4-segment chart versions.

```bash
APP_VERSION=0.9.2.5-rc.1     # Docker image tag
CHART_VERSION=0.9.2-rc.1     # Helm chart version (4th segment dropped)

helm install ocu-rc oci://ghcr.io/wide-moat/charts/computer-use-server \
  --version "$CHART_VERSION" \
  --namespace open-computer-use --create-namespace \
  -f my-values.yaml \
  --set image.tag="$APP_VERSION" \
  --set workspaceImage.tag="$APP_VERSION" \
  --set cleanup.image.tag="$APP_VERSION"
```

The `release-chart.yml` workflow prints both values in the Actions Job Summary on every tag push, so you don't have to derive them yourself.

Stable users running `helm repo add open-computer-use https://wide-moat.github.io/...` are unaffected — Helm excludes SemVer pre-releases from `helm install` resolution unless `--devel` or an explicit `--version X.Y.Z-rc.N` is passed.

### From a git checkout (development / unreleased changes)

```bash
helm install ocu helm/computer-use-server \
  --namespace open-computer-use --create-namespace \
  --set secrets.mcpApiKey=$(openssl rand -hex 32) \
  --set orchestrator.env.PUBLIC_BASE_URL=https://orchestrator.example.com \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=orchestrator.example.com \
  --set ingress.hosts[0].paths[0].path=/ \
  --set ingress.hosts[0].paths[0].pathType=Prefix
```

See [`examples/helm/standalone/values.yaml`](../../examples/helm/standalone/values.yaml) for a values-file version.

After install:

```bash
helm test ocu -n open-computer-use   # runs a Pod that curls /health
kubectl -n open-computer-use logs deployment/ocu-computer-use-server -c orchestrator
```

---

## Values reference

The full schema lives in [`values.yaml`](values.yaml). The knobs you most often need:

| Key | Default | Notes |
|---|---|---|
| `image.repository` | `ghcr.io/wide-moat/open-computer-use-server` | orchestrator image |
| `image.tag` | `.Chart.AppVersion` | override if pinning |
| `workspaceImage.repository` | `ghcr.io/wide-moat/open-computer-use` | passed as `DOCKER_IMAGE` to the orchestrator; Podman pulls this on first chat |
| `orchestrator.runtimeClassName` | `""` | stock node. Set `kata-qemu-heavy` for a VM boundary — see the note below |
| `orchestrator.replicas` | `1` | **must stay 1** — single owner of the engine and the RWO PVCs |
| `orchestrator.env.PUBLIC_BASE_URL` | `""` | **REQUIRED** — browser-facing URL (no trailing slash). Without it, chat file previews 404. |
| `orchestrator.extraEnv` / `envFrom` | `[]` | inject `ANTHROPIC_*`, `VISION_*`, etc. from existing Secrets / ConfigMaps |
| `secrets.create` | `true` | renders a Secret from `secrets.mcpApiKey` etc. (handy, bad for GitOps) |
| `secrets.existingSecret` | `""` | when set, ignores `secrets.create` and uses your Secret via `envFrom`. Must include `MCP_API_KEY`. |
| `secrets.mcpApiKey` | `""` | **REQUIRED** unless `existingSecret` is set |
| `persistence.userData.size` | `20Gi` | `/tmp/computer-use-data` — uploads + outputs |
| `persistence.data.size` | `5Gi` | `/data` — long-lived orchestrator state |
| `persistence.skillsCache.size` | `2Gi` | `/data/skills-cache` |
| `persistence.podmanStorage.size` | `40Gi` | Podman's graph root. **Not a cache** — it holds pulled images *and* the named volume for each chat's working directory, so an emptyDir here loses user work on every restart. |
| `cleanup.enabled` | `true` | runs the same crons as `docker-compose.yml` (`cron/cleanup.sh` + `cron/cleanup-quick.sh`) |
| `cleanup.containerMaxAgeHours` | `24` | stop workspace containers older than this |
| `cleanup.dataMaxAgeDays` | `7` | remove stale data dirs older than this |
| `ingress.enabled` | `false` | standard Ingress template — `className`, `annotations`, `hosts`, `tls` |
| `networkPolicy.enabled` | `false` | default-deny + allowed egress to public internet |
| `podDisruptionBudget.enabled` | `false` | irrelevant at `replicas: 1` |

---

## Postgres

The orchestrator itself does not use Postgres — only Open WebUI does. This chart intentionally does **not** bundle Postgres as a subchart, to keep `helm install` paths predictable (Helm 4 has several open bugs around `condition:` dependencies, see [helm/helm#13341](https://github.com/helm/helm/issues/13341)).

If you need Postgres for an adjacent Open WebUI deployment, install it as a separate release. Example:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install pg bitnami/postgresql \
  -n open-computer-use \
  --set auth.username=openwebui \
  --set auth.database=openwebui \
  --set auth.existingSecret=ocu-shared
```

See [`examples/helm/with-open-webui/README.md`](../../examples/helm/with-open-webui/README.md) for the full walkthrough.

---

## Bring your own Secret (GitOps mode)

Recommended for anything you check into git:

```bash
kubectl -n open-computer-use create secret generic ocu-server-creds \
  --from-literal=MCP_API_KEY=$(openssl rand -hex 32) \
  --from-literal=ANTHROPIC_AUTH_TOKEN=sk-ant-... \
  --from-literal=VISION_API_KEY=...

helm install ocu helm/computer-use-server \
  --set secrets.create=false \
  --set secrets.existingSecret=ocu-server-creds \
  --set orchestrator.env.PUBLIC_BASE_URL=https://orchestrator.example.com
```

The Secret is mounted via `envFrom` — every key becomes an env var on the orchestrator container.

---

## The engine

Rootless Podman, and only that. The pod runs one `podman system service` sidecar speaking the
Docker API on `/var/run/docker.sock`, so the orchestrator's Docker client needs no change.
Isolation is user namespaces plus the AppArmor profile named in `podAnnotations`.

There used to be a `sandboxRuntime` switch offering Docker-in-Docker under Sysbox, under
`privileged: true`, or under Kata. All three are gone. The privileged variant gave the inner daemon
host-kernel access and broke pod isolation outright; the other two demanded cluster features — a
`RuntimeClass`, raw block storage — that a shared or managed cluster often will not provide, and
that turned out not to be necessary. An option nobody runs is an option nobody tests, and this one
could only fail in a privileged context.

If you set `orchestrator.runtimeClassName: kata-qemu-heavy` to get a VM boundary back, note what
comes with it: virtio-fs inside a Kata guest drops the `security.capability` xattrs the sandbox
image carries, so the image will not unpack on ordinary storage and you need a Block-mode PVC for
Podman's graph root. That is a property of the guest, not of the storage, which is why the stock
Podman path needs no block device.

---

## Troubleshooting

**`unlinkat /etc/ld.so.cache: operation not permitted` in the dind container.**
Sysbox issue #406 — you're sharing `/var/lib/docker` somewhere you shouldn't. Confirm `var-lib-docker` is its own `emptyDir`, mounted **only** into the `dind` container. Don't replace it with a PVC and don't bind it into the orchestrator.

**Chat file preview links 404 from the browser.**
`PUBLIC_BASE_URL` is wrong. It must be the URL the user's browser sees (same host as the Ingress), not the in-cluster service DNS. Update `orchestrator.env.PUBLIC_BASE_URL` and `helm upgrade`.

**`pod has unbound immediate PersistentVolumeClaims`.**
Your StorageClass doesn't support `ReadWriteOnce` or there is no default class. Set `persistence.<vol>.storageClass` explicitly or pre-create PVCs and reference them via `persistence.<vol>.existingClaim`.

**Cleanup sidecar logs `Cannot connect to the Docker daemon`.**
The dind container hasn't finished starting yet, or the shared `dind-socket` volume isn't mounted. Wait 30s — the cron only runs every 2 hours and on schedule, so brief startup gaps are harmless.

**Workspace containers can't pull the workspace image.**
The inner dockerd does the pull, not Kubernetes. The image must be reachable from inside the pod (public registry, or `imagePullSecrets` won't help — they apply only to outer kubelet pulls). For private registries, configure inner-dockerd auth via a custom dind image or `dockerd --insecure-registry` arg.

---

## Uninstall

```bash
helm uninstall ocu -n open-computer-use
kubectl -n open-computer-use delete pvc -l app.kubernetes.io/instance=ocu
```

PVCs are not deleted by `helm uninstall` — remove them explicitly to free the storage.

---

## License

BUSL-1.1, Copyright (c) 2025 Open Computer Use Contributors.
