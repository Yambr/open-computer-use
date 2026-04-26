<!-- SPDX-License-Identifier: BUSL-1.1 -->
<!-- Copyright (c) 2025 Open Computer Use Contributors -->

# Multi-CLI Sub-Agent Runtime

> The orchestrator dispatches sub-agent calls to one of three CLIs based on the `SUBAGENT_CLI` environment variable. Default unset = `claude` (byte-identical backwards-compat with v0.9.2.0).

## When to flip the switch

| Goal | `SUBAGENT_CLI` | Why |
|------|----------------|-----|
| Default — Anthropic / LiteLLM gateway | `claude` (or unset) | Native Claude Code; cost reporting; max-turns enforced |
| OpenAI Codex (gpt-5-codex etc.) | `codex` | First-party OpenAI tooling; `--ephemeral` runs; no built-in cost reporting |
| OpenRouter / qwen / DeepSeek / OSS / Bedrock-via-LiteLLM | `opencode` | 75+ provider router; per-step cost when provider reports it |

## Setup — common steps (apply to all three)

1. Pull the latest `open-computer-use` image (codex + opencode are pre-installed alongside claude).
2. Set `SUBAGENT_CLI=<value>` in your `.env`.
3. Set the per-CLI auth env vars (see the per-CLI sections below).
4. Restart the orchestrator: `docker compose up -d --force-recreate computer-use-server`.
5. Verify the runtime took effect:
   ```bash
   docker compose logs computer-use-server | grep "Sub-agent runtime"
   # Expected: [MCP] Sub-agent runtime: <value>
   ```
6. Spawn a sandbox (any chat or `/health` poke) and verify the CLI is on PATH:
   ```bash
   docker exec <sandbox-container> <cli> --version
   # Expected: a non-zero version string
   ```

## Switch to Claude (default — no setup needed)

This is the default path. If you previously set `SUBAGENT_CLI=codex` or `=opencode` and want to revert, either delete the line from `.env` or set `SUBAGENT_CLI=claude` explicitly — both resolve identically.

For Anthropic / LiteLLM gateway configuration, see [`docs/claude-code-gateway.md`](./claude-code-gateway.md).

## Switch to Codex

Add to `.env`:
```bash
SUBAGENT_CLI=codex
OPENAI_API_KEY=sk-...
# Optional gateway (Azure OpenAI, LiteLLM proxy, etc.):
OPENAI_BASE_URL=https://your-litellm-proxy/v1
# Optional per-CLI default model:
CODEX_SUB_AGENT_DEFAULT_MODEL=gpt-5-codex
```

Restart per common steps. The container's `~/.codex/config.toml` is rendered conditionally:
- with `OPENAI_BASE_URL` set → contains a `[model_providers.custom]` block pointing at your gateway;
- without it → empty file (Codex uses defaults).

Verify:
```bash
docker exec <sandbox> codex --version    # Expect: codex-cli 0.125.0
docker exec <sandbox> cat ~/.codex/config.toml
```

## Switch to OpenCode + qwen3-coder via OpenRouter (worked recipe)

This is the headline recipe — runs sub-agents against a frontier OSS coding model with no Anthropic dependency.

Add to `.env`:
```bash
SUBAGENT_CLI=opencode
OPENROUTER_API_KEY=sk-or-v1-...
OPENCODE_SUB_AGENT_DEFAULT_MODEL=openrouter/qwen/qwen-3-coder
```

Restart:
```bash
docker compose up -d --force-recreate computer-use-server
```

Verify the orchestrator picked up the runtime:
```bash
docker compose logs computer-use-server | grep "Sub-agent runtime"
# Expected: [MCP] Sub-agent runtime: opencode
```

Spawn any sandbox and verify the OpenCode config is rendered without leaking the key:
```bash
docker exec <sandbox> cat /tmp/opencode.json
# Expected: providers.openrouter.apiKey is "{env:OPENROUTER_API_KEY}" — NOT a literal sk-or-v1-... value
```

The `{env:VAR}` syntax means OpenCode resolves the key at runtime from the container env. The file on disk contains zero plaintext secrets — the sandbox volume can be mounted, copied, or shared without leaking your OpenRouter key.

Trigger a sub-agent call from the chat (or via the MCP `sub_agent` tool). Expected response shape:
```
**Sub-Agent Completed** (success)
<the qwen3-coder reply>
**Cost:** unavailable | **Duration:** 12.3s | **Turns:** unavailable
```

`Cost: unavailable` is **expected** for opencode runs — see the next section.

## What changes when you flip the switch

| Aspect | claude | codex | opencode |
|--------|--------|-------|----------|
| Cost reporting | reported as USD | unavailable | depends on provider (some report per-step cost) |
| `max_turns` enforcement | enforced (CLI flag) | not enforced — `SUB_AGENT_TIMEOUT` is the backstop | not enforced — `SUB_AGENT_TIMEOUT` is the backstop |
| `resume_session_id` | supported | ignored with stderr warning (`--ephemeral` is stateless) | ignored with stderr warning |
| Model alias `sonnet` / `opus` / `haiku` | resolves to Claude IDs | hard-fail with actionable error message | resolves to `anthropic/claude-X-X` provider/model |
| Direct provider/model strings (e.g. `openrouter/qwen/qwen-3-coder`) | pass-through | pass-through | pass-through |
| `~/.claude/projects/*.jsonl` live log streaming | yes | no | no |
| Image install | always (pre-installed) | always (pre-installed) | always (pre-installed) |

If you set a Claude alias (`sonnet`/`opus`/`haiku`) while `SUBAGENT_CLI=codex`, the orchestrator hard-fails with a clear error rather than silently 400-ing against OpenAI:

```
Model alias 'sonnet' is Claude-only; SUBAGENT_CLI=codex requires a GPT model id
(e.g. 'gpt-5-codex') or set CODEX_SUB_AGENT_DEFAULT_MODEL.
```

## Escape hatch — plain bash terminal

`SUBAGENT_CLI` makes the in-browser ttyd terminal auto-launch the chosen CLI. To get a plain bash prompt instead:

```bash
# Per-session (in a new terminal tab):
NO_AUTOSTART=1 bash

# OR persistently for this container (next ttyd session):
touch /tmp/.no_autostart
```

The hint also appears in the entrypoint banner when you start the container.

## Auth isolation guarantee

The orchestrator injects only the active CLI's auth env vars into the sandbox container. Concretely:

- `SUBAGENT_CLI=claude` → only `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL` reach the sandbox; `OPENAI_API_KEY` and `OPENROUTER_API_KEY` are stripped even if set on the host.
- `SUBAGENT_CLI=codex` → only `OPENAI_*` and `AZURE_OPENAI_*` keys reach the sandbox; `ANTHROPIC_AUTH_TOKEN` and `OPENROUTER_API_KEY` are stripped.
- `SUBAGENT_CLI=opencode` → only `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` reach the sandbox; `ANTHROPIC_AUTH_TOKEN` (the legacy Claude key) is stripped.

This prevents an operator's leftover `OPENAI_API_KEY` (from a previous Codex experiment) from silently routing OpenCode traffic through OpenAI when they meant OpenRouter.

## Troubleshooting

- **Banner shows the wrong CLI** — `SUBAGENT_CLI` is read once at orchestrator boot, not per-request. Restart: `docker compose restart computer-use-server`.
- **`SUBAGENT_CLI=cline` (typo) → orchestrator refuses to start** — this is intentional. Fix the typo; check `docker compose logs computer-use-server` for the FATAL line listing the three accepted values.
- **OpenCode falls back to a default provider** — verify `/tmp/opencode.json` exists in the sandbox; if not, the container needs `--force-recreate` to re-render it via the entrypoint heredoc.
- **Cost reads `$0.0000` for codex/opencode** — this is a bug; the expected display is `cost: unavailable`. File an issue with the result blob attached.
- **Sub-agent for codex/opencode runs forever** — `max_turns` is Claude-only; the backstop for the other two is `SUB_AGENT_TIMEOUT` (default 3600s). Lower it in `.env` if you need a tighter cap: `SUB_AGENT_TIMEOUT=1800`.

## Prior art

- [OpenAI Codex CLI documentation](https://developers.openai.com/codex/cli/reference) — `codex exec` flags, JSONL event schema
- [sst/opencode documentation](https://opencode.ai/docs/) — `opencode run`, `{env:VAR}` config substitution, providers list
- [OpenRouter qwen3-coder model page](https://openrouter.ai/qwen/qwen3-coder)
- Issue #40 / PR #41 — community discussion that informed Phase 3 (Claude Code gateway compatibility), the foundation this milestone builds on.
