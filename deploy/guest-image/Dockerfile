# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors

# Assembled session-guest image. ONE container per session; the guest agent is
# PID 1 and starts the mount binary as its managed boot-child ([ADR-0020] ruling
# 2: "the control agent (PID 1) and the ocu-rclone-filestore mount binary the
# agent starts"). Composition is appended OCI layers over a base — here two
# `COPY --from` stages over the userland base — not a bake ([ADR-0020] ruling 2:
# `mutate.AppendLayers`-style, base byte-unmutated). Assembly lives in THIS repo
# (the deploy layer): each component ships its own artifact image; the guest
# image is composed here, and neither component repo owns the weld.
#
# Two static (no-libc) binaries ride the layers:
#   - the guest agent, PID 1, UDS-only exec/control listener;
#   - the ocu-rclone-filestore mount binary, started by the agent, which FUSE-
#     mounts /mnt/user-data/{uploads,outputs} in-sentry and dials the egress
#     edge outbound for the object-store leg.
#
# Under gVisor (runsc) the mount is co-located in the SAME guest — the sentry
# rejects rshared cross-container root-mount propagation, so a separate mount
# container cannot propagate /mnt/user-data into the sandbox. Co-location is the
# only shape that works, and it is exactly canon (one container per session,
# 05-session-sandbox invariant 1). FUSE mount(2) under runsc is proven: the
# guest runs with cap-drop ALL + cap-add SYS_ADMIN (the minimal add-back for
# mount(2)) + no-new-privileges + a read-only rootfs + /dev/fuse from the host.
#
# Build inputs (both pinned by the caller as digests in a real release):
#   AGENT_IMAGE  — the guest-agent image (repo ocu-sandbox, host/guestimage)
#   MOUNT_IMAGE  — the ocu-rclone-filestore mount image (repo ocu-rclone-filestore)
#   BASE_IMAGE   — the userland rung the session sees (min/medium/high/xhigh per
#                  [ADR-0020]); the agent + mount are NOT baked into it, they are
#                  layered on here. Defaults to an empty base for the minimal rung.
#
# Build (platform pinned per repo policy):
#   docker build --platform linux/amd64 \
#     --build-arg AGENT_IMAGE=process_api:prod \
#     --build-arg MOUNT_IMAGE=ocu-rclone-filestore:latest \
#     --build-arg BASE_IMAGE=<userland-rung-or-scratch> \
#     -f deploy/guest-image/Dockerfile -t ocu-guest:assembled deploy/guest-image
#
# SCOPE. This Dockerfile is the INTERIM realization of the [ADR-0020] ruling-1
# pipe (an image is given -> OCU appends its runtime layers -> OCU starts it),
# executed at deploy-build time because the control-plane image-provisioning role
# (image selection, two-signature admission verify, OCI layer-append — distinct
# from the existing RuntimeProvider.Materialize container seam)
# ([ADR-0020] Decision, component-02 admission) does not exist yet. It is the
# pipe's OUTPUT, not a second image mode, and it is RETIRED when that role
# lands. The assembled tag is a deployment handle, never a provenance root: the
# per-session provenance record cites the BASE_IMAGE digest plus BOTH OCU
# runtime-input digests — AGENT_IMAGE and MOUNT_IMAGE — SEPARATELY ([ADR-0020]
# ruling 5, and ruling 2 names both static binaries as the appended layers; a
# merged-rootfs signature is not the system of record). Not a release artifact:
# do NOT wire this into a registry-push CI job until ADR-0020's Decision and the
# bundled-image Bill-of-Materials row land.

# The two artifact images are MANDATORY and have no defaults: an unpinned build
# fails closed (empty FROM errors). Releases pass sha256 digests; local dev
# passes tags. The base defaults to scratch (the minimal rung).
ARG AGENT_IMAGE
ARG MOUNT_IMAGE
ARG BASE_IMAGE=scratch

# Name the artifact stages so the COPY --from lines below read against a stable
# alias regardless of the concrete image the caller pins.
FROM ${AGENT_IMAGE} AS agent
FROM ${MOUNT_IMAGE} AS mount

# ---------------------------------------------------------------------------
# The assembled guest. The base is the customer/OCU userland rung; the agent
# and the mount binary are layered on top (never baked into the base image).
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS guest

LABEL org.opencontainers.image.title="ocu-guest" \
      org.opencontainers.image.description="Open Computer Use assembled session guest (agent PID1 + co-located FUSE mount, UDS-only exec)" \
      org.opencontainers.image.licenses="FSL-1.1-Apache-2.0" \
      org.opencontainers.image.vendor="Open Computer Use Contributors"

# The guest agent (PID 1). Same path the standalone guest-agent image uses, so
# the host's create-time command wiring is unchanged.
COPY --from=agent /usr/local/bin/process_api /usr/local/bin/process_api

# The mount binary the agent starts as its boot-child. It dials the egress edge
# outbound (service_url + ca_cert_pem + per-mount auth_token all arrive in the
# mount config); it opens no listener and bakes no credential.
#
# Kept at /ocu-rclone-filestore — the SAME path the standalone mount image homes
# it at and runs it as ENTRYPOINT — so the standalone and assembled images share
# one path truth. The control plane will name this path as the first --boot-child-argv
# token; that argv is a cross-repo contract, so the path must not drift between
# the two images.
COPY --from=mount /ocu-rclone-filestore /ocu-rclone-filestore

# The canonical mountpoints must exist in the image: the mount binary does not
# create destinations, and the base may have no shell to mkdir them at boot.
# Copied from the mount image, which stages them root-owned and traversable.
COPY --from=mount /mnt/user-data /mnt/user-data

# No EXPOSE, no port: the exec/control transport is Unix-domain-socket only, and
# the mount's only network handle is its outbound HTTPS to the egress edge.
#
# No USER: the agent is PID 1 and must start as in-container root to create its
# cgroup subtree and to let the mount's mount(2) use CAP_SYS_ADMIN from the
# effective set; the agent drops privileges per spawned exec child, and the
# container itself runs cap-drop ALL + SYS_ADMIN-add-back + no-new-privileges +
# read-only rootfs. A non-root USER here would fail the boot cgroup writes and
# the FUSE mount(2).
#
# The entrypoint is the bare agent binary; the control plane supplies the full
# command at create time (the UDS listener wiring plus --boot-child-argv naming
# the mount binary + its --config/--ready-file). Exec form only.
#
# USER 0 is set EXPLICITLY: FROM ${BASE_IMAGE} inherits USER from the base, and a
# hardened rung or BYO base that sets a non-root USER would silently break the
# boot cgroup writes and the FUSE mount(2) CAP_SYS_ADMIN effective-set need above.
# ENTRYPOINT resets an inherited CMD but nothing resets an inherited USER, so it
# is pinned here. This is in-container root only — user-namespace mapping keeps
# host UID 0 != guest UID 0 (component-05 invariant 7), so the posture is intact.
USER 0
# nosemgrep: dockerfile.security.missing-user-entrypoint.missing-user-entrypoint
ENTRYPOINT ["/usr/local/bin/process_api"]
