<!-- SPDX-License-Identifier: BUSL-1.1 -->
<!-- Copyright (c) 2025 Open Computer Use Contributors -->

# cli-defaults/

Canonical default configurations for sub-agent CLIs (`opencode`, `codex`).

Single source of truth — consumed by:
1. `Dockerfile` sandbox entrypoint when `OPENCODE_CONFIG_EXTRA` / `CODEX_CONFIG_EXTRA` env are unset (Plan 02-04).
2. `computer-use-server/bin/list-subagent-models` host-friendly mode (Plan 02-05).

## Files

- `opencode.json` — opencode native config (consumed by `opencode` CLI verbatim, modulo `_spdx` / `_copyright` strip).
- `codex.json` — structured JSON that the Dockerfile entrypoint converts to `~/.codex/config.toml`. JSON in repo (not TOML) for consistency and easier programmatic consumption by `list-subagent-models`.

## SPDX header convention for JSON

JSON does not support comments. To carry SPDX/copyright metadata, every file in this directory uses two top-level keys:

- `"_spdx": "BUSL-1.1"`
- `"_copyright": "Copyright (c) 2025 Open Computer Use Contributors"`

Consumers MUST strip these keys before passing the JSON to the underlying CLI. The leading-underscore prefix avoids collision with any CLI-specific schema key (opencode's schema has no `_*` keys; codex is similar). Per Phase 2 D-10.

## Adding a new CLI

1. Add `<cli>.json` here with the two SPDX keys.
2. Update the Dockerfile entrypoint (the `case "${SUBAGENT_CLI:-claude}"` block) to read it.
3. Update `computer-use-server/bin/list-subagent-models` to read it in host-friendly mode.
4. Update this README's file list.
