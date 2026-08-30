<!-- SPDX-License-Identifier: FSL-1.1-Apache-2.0 -->
<!-- Copyright (c) 2025 Open Computer Use Contributors -->

# Journey e2e suite — PoC vs fleet

A paired user-journey test suite that runs the same journeys against two
systems and asserts the per-system outcome: the PoC (`main` — Open WebUI +
computer-use-server on plain Docker) and the fleet (`next/v1` — gateway mTLS,
control, gVisor guest, FUSE, egress edge, filestore, MinIO). Every scenario
records whether the two behave the same (IDENTICAL), the fleet closes a loose
edge (HARDENED), or the PoC has no boundary at all and the fleet adds one
(PoC-HOLE).

## Layout

| Path | Role |
| --- | --- |
| `scenarios.yaml` | Single source of truth. One entry per scenario A1..G6. |
| `backends/base.py` | The `Backend` Protocol: the journey verbs a test calls. |
| `backends/poc.py` | `PocBackend` — real HTTP + docker against the PoC surface. |
| `backends/fleet.py` | `FleetBackend` — real mTLS wire against control + guest. |
| `conftest.py` | The `backend` fixture (parametrized poc/fleet) + honesty rules. |
| `render_contrast.py` | Generates `CONTRAST.md` from `scenarios.yaml`. |
| `CONTRAST.md` | Generated table. Do not hand-edit; re-run the renderer. |

Group tests (the A..G bodies that call the verbs) build on this scaffold.

## Running

The `backend` fixture is parametrized over `["poc", "fleet"]`, so each paired
test runs twice — once per system that is live.

```bash
# From the repo root. Run the whole matrix; -rs prints skip reasons.
python3 -m pytest deploy/tests/journeys -rs

# One backend only.
python3 -m pytest deploy/tests/journeys -k poc -rs
python3 -m pytest deploy/tests/journeys -k fleet -rs
```

- **PoC** runs anywhere Docker runs (Darwin included). Bring up
  `docker-compose.yml` + `docker-compose.webui.yml` first. If the local Docker
  daemon is unreachable, the PoC cases skip with a loud reason.
- **Fleet** runs LIVE only inside Lima with the `runsc` runtime registered and
  `deploy/fleet/docker-compose.fleet.yml` up. FUSE and runsc cannot run on a
  Darwin host, so on a Mac every fleet case skips loudly. The fleet is never
  mocked green.

Override endpoints and paths via env vars: `POC_SERVER_URL`, `POC_CHAT_ID`,
`FLEET_BASE`, `FLEET_PKI`, `FLEET_GUEST_IMAGE`, `FLEET_FS_ID`,
`FLEET_OPERATOR_SOCK`.

## Live vs stub

A green here means a real system produced the asserted end state. The rules the
scaffold enforces:

- A backend whose `live()` is False is **skipped with a loud reason**, not
  passed. skip-if-inapplicable is not skip-green.
- A mechanism that is real but inactive in the current env (for example a
  read-only bind that a given driver does not enforce) is `xfail(reason)` via
  `conftest.inactive_mechanism` — a recorded gap, never a silent pass.
- A boundary the PoC does not have raises `PocHoleNotEnforced`; the paired
  `[PoC-HOLE]` test catches that as the finding. That is distinct from a skip:
  the stack is up, the boundary is simply absent.
- Assertions drive the real end state plus the scenario's keystone (the
  negative / inversion). Asserting only that a field or markup element is
  present is a fake green; a green must be reproducibly reddable.
- Browser journeys use a real fill + click (Playwright), never
  `page.evaluate(fetch)`.
- A load probe is sized to stress the whole buffer chain (above the stream
  ceiling), not a neuter payload that any single buffer absorbs.

## CONTRAST.md is generated

`CONTRAST.md` is emitted from `scenarios.yaml` by `render_contrast.py`. Edit
scenarios in the YAML, then regenerate:

```bash
python3 deploy/tests/journeys/render_contrast.py
```

The scenario text lives in one place. If a scenario's expectation changes,
change `scenarios.yaml` and re-run the renderer — never edit `CONTRAST.md` by
hand.
