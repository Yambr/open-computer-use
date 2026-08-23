# Kubernetes deployment

The Docker Compose stack in `docker-compose.yml` / `docker-compose.webui.yml` ships as a Helm chart in [`helm/computer-use-server/`](../helm/computer-use-server/). This is the recommended way to run open-computer-use on Kubernetes.

## Runtime

The orchestrator runs an inner container engine to spawn the sandboxes. As of chart
0.4.0 that engine is **rootless [Podman](https://podman.io/)**, and it installs on a
stock Kubernetes node: no privileged container, no RuntimeClass, no Block-mode PVC.
`podman system service` speaks the Docker API, so the orchestrator is unchanged.

Isolation is user namespaces plus an AppArmor profile, which is weaker than the VM
boundary the Kata-based chart gave you. Say so out loud when deciding: it is a
reduction, not an equivalent. The profile must already exist on the node — a chart
cannot install one — and is selected with:

```yaml
podAnnotations:
  container.apparmor.security.beta.kubernetes.io/podman: localhost/podman-rootless
```

If your cluster has [Kata Containers](https://katacontainers.io/) and you want the VM
boundary back, set `orchestrator.runtimeClassName: kata-qemu-heavy` — see the
[Kata runtime guide](kata-runtime.md). Note that the Block-mode PVC has to come back
with it: virtio-fs inside the guest drops the `security.capability` xattrs the sandbox
image carries, which is why that volume existed in the first place.

## Quick start

```bash
# 1. Add the chart repo (published from the gh-pages branch on every release tag):
helm repo add open-computer-use https://wide-moat.github.io/open-computer-use
helm repo update

# 2. Install:
helm install ocu open-computer-use/computer-use-server \
  --namespace open-computer-use --create-namespace \
  --values examples/helm/standalone/values.yaml
```

Or, against a git checkout for unreleased changes:

```bash
helm install ocu helm/computer-use-server \
  --namespace open-computer-use --create-namespace \
  --values examples/helm/standalone/values.yaml
```

The chart README at [`helm/computer-use-server/README.md`](../helm/computer-use-server/README.md) is the authoritative reference. This page is the navigation.

## Examples

- **[`examples/helm/standalone/`](../examples/helm/standalone/)** — minimum-viable config (just the orchestrator). Closest to `docker-compose.yml`.
- **[`examples/helm/with-open-webui/`](../examples/helm/with-open-webui/)** — orchestrator + Open WebUI via the upstream Open WebUI Helm chart. Closest to `docker-compose.yml` + `docker-compose.webui.yml` together.

## Architecture

The orchestrator pod has three containers:

```text
┌──────────────────── Pod (no RuntimeClass, nothing privileged) ──────────────────┐
│                                                                                 │
│  ┌─────────────────┐   ┌─────────────────┐   ┌──────────────────────────────┐  │
│  │  orchestrator   │──►│ rootless podman │◄──│  cleanup sidecar (cron)      │  │
│  │  FastAPI :8081  │   │  spawns chat-*  │   │  reaps stale chat-* + data   │  │
│  └─────────────────┘   └─────────────────┘   └──────────────────────────────┘  │
│        │ /var/run/docker.sock  ▲       ▲                  ▲                     │
│        └──────── shared emptyDir (dind-socket) ───────────┘                     │
│                                                                                 │
│  Volumes:                                                                       │
│   - emptyDir  dind-socket    → /var/run on all three containers                │
│   - PVC       podman-storage → ~/.local/share/containers on podman ONLY        │
│   - PVC       user-data      → /tmp/computer-use-data (RWO)                    │
│   - PVC       data           → /data (RWO)                                     │
│   - PVC       skills-cache   → /data/skills-cache (RWO)                        │
└─────────────────────────────────────────────────────────────────────────────────┘

The socket is still called `docker.sock`: Podman serves the Docker API on it, which is
why the orchestrator needs no change. `podman-storage` is **not** a cache — it holds the
pulled sandbox image *and* the named volume carrying each chat's working directory, so an
emptyDir there discards user work on every pod restart.
```

**Why an inner engine instead of native k8s Pods?**
The existing orchestrator code talks to a Docker socket. Running an engine beside it keeps the app code unchanged. A future `K8sBackend` rewrite (drafted in [`docs/future-architecture/`](future-architecture/)) will spawn native Pods, at which point the inner engine disappears — but that's a separate workstream.

**Why is the orchestrator single-replica?**
It owns the inner container engine and its RWO PVCs. There is no shared state between replicas and no leader-election. The chart hard-pins `replicas: 1` in `values.schema.json`.

## Prerequisites checklist

- Kubernetes ≥ 1.27
- A StorageClass that supports `ReadWriteOnce`. `persistence.*.storageClass` is **required** on all four volumes — the chart refuses to render without it, rather than letting a PVC silently take whichever class the cluster marks default. Node-local suits the caches and the image store; replicated is worth it only for `data`.
- An AppArmor profile on the nodes for the Podman sidecar, referenced through `podAnnotations`. Without one the sandboxes still run, confined only by the cluster's default profile.
- Kata Containers **only if** you opt back into `orchestrator.runtimeClassName` — see [`kata-runtime.md`](kata-runtime.md). Not required by default.
- Ingress controller (nginx-ingress, Traefik, etc.) if you set `ingress.enabled=true`
- DNS + TLS cert for the public hostname referenced by `PUBLIC_BASE_URL`

## See also

- [`helm/computer-use-server/README.md`](../helm/computer-use-server/README.md) — chart reference and troubleshooting
- [`docs/kata-runtime.md`](kata-runtime.md) — Kata Containers runtime guide (install, configure, verify, troubleshoot)
- [`docs/future-architecture/`](future-architecture/) — draft of the future native-Pod backend (not implemented)
