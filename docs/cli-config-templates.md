<!-- SPDX-License-Identifier: BUSL-1.1 -->
<!-- Copyright (c) 2025 Open Computer Use Contributors -->

# CLI Config Templates

Companion reference for [docs/multi-cli.md](multi-cli.md). Copy-paste config snippets for the gray-area knobs the in-image entrypoint does NOT render by default — Azure routing, approval modes, MCP federation, custom OpenAI-compat gateways behind nginx, opencode personas.

The image entrypoint renders a **minimal viable** config so first-boot works for the common case. Anything beyond minimal goes through one of two operator hooks:

- `OPENCODE_CONFIG_EXTRA` — full JSON contents for `/tmp/opencode.json`. When set, **replaces** the canonical block (no merging — opencode JSON has no merge story).
- `CODEX_CONFIG_EXTRA` — TOML fragment **appended** to `~/.codex/config.toml` after the canonical block. Append-only because TOML supports independent table sections side-by-side.

Both are env vars (no plaintext secrets on disk; values can be sourced from `.env` and rendered with `{env:VAR}` substitution where the consumer supports it).

If you don't set either: the image renders today's defaults exactly as before. Backwards-compatible.

---

## Codex — Azure OpenAI

Operators on Azure OpenAI use a different `wire_api` and a per-deployment `base_url`. Source: [openai/codex docs — model_providers](https://developers.openai.com/codex).

```bash
# .env
SUBAGENT_CLI=codex
OPENAI_API_KEY="<your-azure-key>"
# Note: do NOT set OPENAI_BASE_URL — that's for the generic custom gateway.
# Azure goes through CODEX_CONFIG_EXTRA below so wire_api can be "chat".
CODEX_CONFIG_EXTRA='
model_provider = "azure"

[model_providers.azure]
name = "azure"
base_url = "https://<resource>.openai.azure.com/openai/deployments/<deployment>"
env_key = "OPENAI_API_KEY"
wire_api = "chat"
query_params = { "api-version" = "2024-08-01-preview" }
requires_openai_auth = true
'
```

Verify after `docker compose up`:

```bash
docker exec -it computer-use-server cat /home/assistant/.codex/config.toml
# Expect both the canonical [model_providers.custom] block (empty if no
# OPENAI_BASE_URL) AND the Azure block appended below.
```

---

## Codex — Approval & sandbox modes

By default the entrypoint relies on `--full-auto` in the adapter argv (see `cli_adapters/codex.py`). Operators wanting interactive approval, or a tighter sandbox, set the defaults in config so they apply when the operator drives the CLI from the ttyd terminal too:

```bash
CODEX_CONFIG_EXTRA='
approval_policy = "on-request"     # never | on-request | unless-trusted
sandbox_mode    = "workspace-write" # read-only | workspace-write | danger-full-access
'
```

The adapter's `--full-auto` continues to override these for sub-agent invocations (intentional — sub-agents must not block on user input).

---

## Codex — Custom OpenAI-compat gateway behind nginx

The simplest case (`OPENAI_BASE_URL=https://gateway.internal/v1`) is rendered by the entrypoint automatically. The advanced case (per-route auth, custom headers) needs `CODEX_CONFIG_EXTRA`:

```bash
SUBAGENT_CLI=codex
OPENAI_API_KEY="<gateway-token>"
CODEX_CONFIG_EXTRA='
model_provider = "internal-gw"

[model_providers.internal-gw]
name = "internal-gw"
base_url = "https://gateway.internal/v1"
env_key = "OPENAI_API_KEY"
wire_api = "responses"
requires_openai_auth = true
http_headers = { "X-Tenant-ID" = "research-team" }
'
```

Auth headers go in `http_headers`, never `env`. Avoid baking secrets into the table — use `env_key` to point at the env var name.

---

## OpenCode — instructions (system-prompt federation)

The entrypoint's canonical config has no `instructions[]`. Operators wanting a shared global system prompt (loaded for every opencode invocation in the container) supply the full JSON:

```bash
SUBAGENT_CLI=opencode
OPENROUTER_API_KEY="<key>"
OPENCODE_CONFIG_EXTRA='{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openrouter": { "options": { "apiKey": "{env:OPENROUTER_API_KEY}" } }
  },
  "model": "openrouter/qwen/qwen-3-coder",
  "instructions": [
    "You are a sub-agent inside the Open Computer Use sandbox.",
    "All work happens under /home/assistant. Never touch /mnt/skills."
  ]
}'
```

Verify:

```bash
docker exec -it computer-use-server cat /tmp/opencode.json
# Expect exactly your override — no merging with the canonical block.
```

---

## OpenCode — MCP federation (sub-agent CLI calls back into host MCP)

Use this when you want the opencode sub-agent to invoke MCP tools on the host orchestrator (e.g. to use `take_screenshot` or browse-spec tools without leaving the sub-agent loop):

```bash
OPENCODE_CONFIG_EXTRA='{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openrouter": { "options": { "apiKey": "{env:OPENROUTER_API_KEY}" } }
  },
  "model": "openrouter/qwen/qwen-3-coder",
  "mcp": {
    "computer-use": {
      "type": "remote",
      "url": "http://computer-use-server:8081/mcp",
      "enabled": true
    }
  }
}'
```

Caveats:

- The opencode container reaches the orchestrator via the docker-compose service name (`computer-use-server`), NOT `localhost`.
- The host MCP must accept the same auth scope as the host orchestrator's `MCP_API_KEY`. Set it explicitly in the MCP server config or pass via `headers`.

---

## OpenCode — custom OpenAI-compat provider

Mirror of the Phase 9.1 mock LLM smoke test, useful for pointing opencode at a corporate gateway:

```bash
OPENCODE_CONFIG_EXTRA='{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "internal-gw": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Internal OpenAI gateway",
      "options": {
        "baseURL": "https://gateway.internal/v1",
        "apiKey": "{env:GATEWAY_TOKEN}"
      },
      "models": {
        "qwen-3-coder": { "name": "Qwen 3 Coder" }
      }
    }
  },
  "model": "internal-gw/qwen-3-coder"
}'
```

Set the matching env var in `.env`:

```bash
GATEWAY_TOKEN="<your-token>"
SUBAGENT_CLI=opencode
```

---

## OpenCode — agent personas

Operators wanting predefined personas (e.g. a "code-reviewer" agent and a "test-writer" agent) define them in config and dispatch via `opencode run --agent <name>`:

```bash
OPENCODE_CONFIG_EXTRA='{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openrouter": { "options": { "apiKey": "{env:OPENROUTER_API_KEY}" } }
  },
  "model": "openrouter/qwen/qwen-3-coder",
  "agent": {
    "code-reviewer": {
      "model": "openrouter/anthropic/claude-sonnet-4.5",
      "instructions": ["You review code. You never write code yourself."]
    },
    "test-writer": {
      "model": "openrouter/qwen/qwen-3-coder",
      "instructions": ["You write tests. Always pytest, never unittest."]
    }
  }
}'
```

Note: the orchestrator adapter (`cli_adapters/opencode.py`) does NOT pass `--agent` today. To dispatch a specific persona from the host MCP, an adapter change is required (deferred to a future phase).

---

## Verification recipe (any of the above)

```bash
# 1. Update .env, restart the stack so the entrypoint re-renders.
docker compose down
docker compose up -d

# 2. Inspect the rendered config.
docker exec -it computer-use-server cat /tmp/opencode.json
docker exec -it computer-use-server cat /home/assistant/.codex/config.toml

# 3. Smoke the CLI inside the sandbox container (one-off).
docker exec -it computer-use-server bash -lc \
  'SUBAGENT_CLI=opencode opencode run "Say hello." --format json | tail -5'

# 4. Trigger a real sub-agent call from the host MCP and watch the orchestrator
#    logs for "[SUB-AGENT]" lines confirming the chosen CLI.
docker compose logs -f computer-use-server | grep -i sub-agent
```

If the rendered config contains the snippet you set in `*_CONFIG_EXTRA` and the CLI exits 0 on the smoke step, the override is live.

---

## What this doc does NOT do

- Render configs for you. The entrypoint does that — this doc only documents the override knobs.
- Cover Claude Code config. `claude` reads `~/.claude.json` automatically; the entrypoint does not write a config for it. Use the standard Claude Code config docs.
- Replace `docs/multi-cli.md`. Read that first to understand the basic flip; this doc is for the operator who has already shipped the basic case and wants to push further.

For the basic per-CLI flip and `.env.example` block, see [`docs/multi-cli.md`](multi-cli.md).
For known limitations and follow-up phases, see [`CHANGELOG.md`](../CHANGELOG.md).
