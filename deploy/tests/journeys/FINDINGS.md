<!-- SPDX-License-Identifier: FSL-1.1-Apache-2.0 -->
<!-- Copyright (c) 2025 Open Computer Use Contributors -->

# Journey-suite findings

Defects the user-journey e2e suite surfaced by running FIRSTHAND against the
live fleet (Lima, runsc + runsc-fuse). Each was reproduced with a raw
create/exec against control, not inferred from code. The suite records each as
a strict `real_finding` xfail with the reproduction below, so the finding is
tracked, not hidden, and the run stays green on the invariants that DO hold.

Live-run baseline: 20 passed / 6 failed / 50 skipped / 24 xfailed. The six
non-xfail failures all trace to finding 1 (the storage-write plane) or the two
separate download/audit surfaces (E8, G3) noted at the end.

## 1. Storage-write plane does not round-trip (B1–B5, D5, G1)

A FUSE write to `/mnt/user-data/outputs/` reports success in-guest but the
object does not read back.

Two distinct causes, both reproduced firsthand:

- The in-guest mount client streams the object `Put` without the
  contract-required `declared_size_bytes`; the broker answers
  `400 INVALID_ARGUMENT {"reason_code":"INVALID_ARGUMENT","message":"declared_size_bytes required"}`.
  The contract makes the field required, so the gap is in the mount wrapper,
  not the broker.
- The fleet's filestore is a stand-in whose read/resolve plane is unimplemented:
  a read-back logs `ocufs: resolve "/x": brokerrpc: status 501 UNIMPLEMENTED
  "operation not implemented in this build"`.

Effect: a docx written by the agent cannot be downloaded — the outputs journey
does not complete on the fleet stand-in.

Reproduce:

```bash
# create a storage session (returns 201), then in-guest:
/bin/busybox sh -c 'echo HELLO > /mnt/user-data/outputs/x.txt; /bin/busybox cat /mnt/user-data/outputs/x.txt'
# read-back is empty; the guest rclone-mount log carries the 400 / 501 above.
```

The pure-Python OOXML validity keystone (`_assert_valid_docx`) stays a hard
pass; only the mount round-trip is xfail.

## 2. Concurrency-counter leak wedges the deployment (E7) — RESOLVED

Historical finding, kept for the E7 keystone's provenance. As first observed,
the `DimConcurrentSessions` counter was a write-only ratchet under the operator
kill-switch path (`RevokeAll` / `forceKillRow` released the row but never the
slot) and boot reconcile treated an Exited-but-present container as live, so
the counter climbed to the tier cap and every create 409'd against zero live
sessions (observed then: counter stuck at 64 against 3 live rows).

RESOLVED in the current control build, verified behaviorally on the live
stack: `forceKillRow` refunds the slot through the same decrement the destroy
path uses (a revoke-one decrements the live quota cell and tombstones the
row), boot reconcile recomputes the counter from actual state, a failed create
unwinds its charge, and the idle reaper reclaims a substrate-lost ACTIVE row
at the idle-TTL with a `reconcile_reclaim` audit record. E7's counter-parity
keystone remains the regression guard. A suite-scale 409 cascade now indicates
HARNESS slot hygiene (sessions created faster than they are destroyed inside
one idle-TTL window), which the per-test operator sweep in `conftest.py`
addresses.

## 3. Egress is open to the public internet (G4)

The `ocu-fleet_ocu-mount-facing` network is `internal: false` — a NAT bridge
with a default route out — so a guest reaches arbitrary external hosts. The
single-hop invariant (guest reaches only its allow-listed edge) holds only for
in-cluster names via DNS scoping, not at L3.

Reproduce (repeatable, rc 0):

```bash
/bin/busybox nc -w5 1.1.1.1 443   # rc 0 — reached the public internet
```

The network must be `internal: true`. Ties the shared-mount-facing network-model
convergence issue.

## Control observability gaps the incidents exposed

These made the findings above hard to diagnose from outside; worth fixing
regardless:

- The create pipeline's host-side stages (handoff / mint / render / materialize)
  emit no audit event on failure and the failing stage name is logged nowhere,
  so a create refusal surfaces only as an opaque `409 "request refused"`. The
  audit-first invariant stops before these stages.
- `readCACertPEM` silently yields an empty string when `-ca-cert` is set but the
  file is unreadable, latching an empty CA at boot (every storage-scoped create
  then dies at the render stage). It should fail-closed at boot the way the
  signing key does — this is what a clean `down -v` + `up` raced into until the
  `harness-init` `depends_on` was added.
- A mountless (compute) create fails at a host-side stage with no audit event
  and no docker activity, so it too is an opaque 409.

## Deploy fixes applied (deploy/fleet)

Two real deployment fixes landed while unblocking the suite:

- `control` `depends_on` now waits on `harness-init` (it writes the CA the
  control plane latches at boot), so a clean `down -v` + `up` self-heals instead
  of racing into an empty-CA boot.
- `control` command gains `-guest-image-allow ocu-guest:assembled-demo` (the
  demo image carries the busybox an in-guest exec needs; the default assembled
  image is distroless). Without it, deny-by-default refused the demo image `400`.

## MCP tool-surface arc — scenario → test traceability (group I + gateway L4)

Source of truth: `mcp_tool_surface.feature` (23 scenarios). `@L4` scenarios are
proven in the gateway repo's `internal/forward` e2e (a control-mock executes the
real committed projection scripts); `@L5` scenarios are proven here as live
journeys against a real Lima fleet. Every scenario maps to a named covering test
or an explicit deferral — no unmapped rows.

| Scenario (feature) | Level | Covering test |
|---|---|---|
| bash_tool first cold call returns stdout | L5 | `test_h_gateway.py::test_h5_cold_bash_tool_first_call_returns_output` |
| non-zero exit, no output → `[Exit code: N]` | L4 | ocu-mcp-gateway `forward.TestL4BashExitNoOutputSynthesizesMarker` @f7b6e5c |
| non-zero exit + stderr relays stderr | L4 | gateway `TestL4BashExitWithStderrRelaysStderr` |
| non-zero exit + stdout-only relays stdout | L4 | gateway `TestL4BashExitWithStdoutOnlyRelaysStdout` |
| grep no-match is a tool error (contrast) | L4 | gateway `TestL4BashGrepNoMatchIsExitCodeError` |
| zero exit, no output = silent success | L4 | gateway `TestL4BashZeroExitNoOutputIsSilentSuccess` |
| real failing command transports non-zero exit | L5 | `test_i_mcp_surface.py::test_i1_nonzero_exit_transports_to_iserror` |
| stdout/stderr in own fields (3-way probe) | L4 | gateway `TestExecMockSeparatesStdoutStderrAndExit` |
| oversized output truncated + flagged | L5 | `test_i_mcp_surface.py::test_i2_oversized_output_bounded_at_ceiling_with_marker` (+ `test_i2b_moderate_output_returns_whole`) |
| command past timeout is killed | L5 | `test_i_mcp_surface.py::test_i3_timeout_is_enforced` (+ `test_i3b_timeout_surfaces_as_tool_result_with_partial_output`) |
| str_replace single unambiguous replace | L4 | gateway `TestL4StrReplaceHappyEditsFile` |
| str_replace refuses ambiguous/empty (outline) | L4 | gateway `TestL4StrReplaceErrorsComposeToIsError` (identical/not-found/multi) |
| create_file writes body + parents | L4 | gateway `TestL4CreateFileWritesWithParents` |
| create_file overwrites without a guard | L4 | gateway `TestL4CreateFileOverwritesExisting` |
| create_file read-only dir errors, no partial | L4 | gateway `TestL4CreateFileReadOnlyDirErrors` (+ `file_tool_script_behavior_test.go` L3) |
| guest identity determines writability | L5 | `test_i_mcp_surface.py::test_i4_write_permission_is_guest_identity_contrast` |
| view text file with line numbers | L4 | gateway `TestL4ViewNumbersTextLines` |
| view lists a directory | L4 | gateway `TestL4ViewListsDirectory` |
| view missing path errors | L4 | gateway `TestL4ViewMissingPathErrors` |
| view non-text file does not crash | L4 | gateway `TestL4ViewBinaryFileDoesNotCrash` |
| four tools carry same session identity | L4 | gateway `TestL4SequenceCarriesSameSessionIdentity` |
| later call sees earlier call's workspace | L5 | `test_i_mcp_surface.py::test_i5_workspace_persists_across_calls_in_one_session` |
| create→view→edit→confirm over one workspace | L5 | `test_i_mcp_surface.py::test_i6_four_tools_compose_over_one_workspace` |

Total: 23 scenarios, 0 unmapped. The gateway `TestL4*` tests run in ocu-mcp-gateway
CI (Go test job); the group-I tests run live against a Lima fleet (tier-2, tracked)
and collect-only in this repo's CI (`journeys-collect.yml`).

## Exec-reply cap invariant (the large-output-502 root cause)

The large-output-502 defect was a cross-component sizing-invariant violation: control
captured 8 MiB per stream while the gateway read-capped the reply at 64 KiB, so a
legal reply above ~48 KiB raw truncated mid-JSON and became a 502 that lost the whole
result. The fix pins:

- **control** bounds each F5 exec-reply stream at **64 KiB** at the source (`defaultStdioCap`, ocu-control #64 @37d6492) + sets `stdout_truncated`/`stderr_truncated`.
- **gateway** reads the reply capped at **256 KiB** (`maxReplyBytes`, ocu-mcp-gateway PR #44 @f7b6e5c); `maxExecContentBytes` (boundContent) ≥ the 64 KiB ceiling so it never fires on a legal reply.
- **Invariant**: `gateway.maxReplyBytes >= 2 × ceil(control.replyCeiling × 4/3) + envelope`. With control ceiling 64 KiB → `2 × ceil(65536 × 4/3) + envelope ≈ 176 KiB ≪ 256 KiB`.

The F5 exec-reply envelope has no shared schema yet (it is Go structs in both repos —
exactly how the caps diverged); authoring it is tracked in
[open-computer-use#344](https://github.com/Wide-Moat/open-computer-use/issues/344). Field
names are frozen de-facto.
