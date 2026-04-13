<!-- SPDX-License-Identifier: BUSL-1.1 -->
<!-- Copyright (c) 2025 Open Computer Use Contributors -->

# Claude Code Gateway Configuration

Every sandbox container spawned by Open Computer Use runs the Claude Code CLI
as a sub-agent (via the `sub_agent` MCP tool). Operators choose where that
CLI sends its API traffic by setting a handful of host-side environment
variables before `docker compose up`. Three paths are supported; each is
additive - set only what your deployment needs.

## Supported paths at a glance

| Path | Operator sets on host | Claude Code inside sandbox |
|------|------------------------|----------------------------|
| **A - Zero-config** | Nothing | Shows the native `/login` OAuth flow in the terminal |
| **B - Public Anthropic** | `ANTHROPIC_AUTH_TOKEN` | Talks to `https://api.anthropic.com` with the supplied token |
| **C - Custom gateway** | `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL` + optional compatibility flags | Talks to the gateway (LiteLLM / Azure / Bedrock) with the gateway-scoped token |

## Path A - Zero-config (stock Claude Code /login)

Leave every `ANTHROPIC_*` and `CLAUDE_CODE_*` variable unset on the host.
`docker compose up` starts the orchestrator with no auth env vars in its
`Env`. When the user triggers `sub_agent` from Open WebUI, Claude Code
launches inside the sandbox and prompts for OAuth login in the ttyd
terminal - the same experience as running `claude` on a fresh laptop.

Nothing else to configure. This is the default and will keep working even
if you never touch this file.

## Path B - Public Anthropic with your own key

Add one line to `.env`:

```
ANTHROPIC_AUTH_TOKEN=sk-EXAMPLE-replace-with-your-anthropic-key
# ANTHROPIC_BASE_URL defaults to https://api.anthropic.com when unset
```

Restart the orchestrator (`docker compose up -d computer-use-server`).
Every sandbox container created after that will receive the token, and
Claude Code will talk straight to Anthropic's public API with no login
prompt.

This is the simplest paid path. The token is scoped to your Anthropic
account; no gateway sits in between. See
<https://code.claude.com/docs/en/env-vars> for the canonical variable
reference.

## Path C - Custom gateway (LiteLLM, Azure, Bedrock)

Point Claude Code at a gateway with a worked LiteLLM recipe:

```
ANTHROPIC_AUTH_TOKEN=sk-EXAMPLE-litellm-master-key
ANTHROPIC_BASE_URL=https://litellm.internal/anthropic
CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1
DISABLE_PROMPT_CACHING=1
ANTHROPIC_DEFAULT_SONNET_MODEL=anthropic/claude-sonnet-4-6
ANTHROPIC_DEFAULT_OPUS_MODEL=anthropic/claude-opus-4-6
ANTHROPIC_DEFAULT_HAIKU_MODEL=anthropic/claude-haiku-4-5
```

What each variable does:

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_AUTH_TOKEN` | Gateway master key (LiteLLM `master_key`, Azure API key, etc.) |
| `ANTHROPIC_BASE_URL` | Gateway endpoint that speaks the Anthropic HTTP API shape |
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` | Set to `1` when the gateway does not forward Anthropic's beta headers |
| `DISABLE_PROMPT_CACHING` | Set to `1` when the gateway does not support `cache_control` blocks |
| `ANTHROPIC_DEFAULT_*_MODEL` | Override the model alias for `sub_agent("sonnet"/"opus"/"haiku")` requests |

The full LiteLLM recipe, including which settings are mandatory for which
backend, is at <https://code.claude.com/docs/en/llm-gateway>.

### Azure / Bedrock via LiteLLM

Claude Code does not speak Azure OpenAI or AWS Bedrock natively, but it
speaks the Anthropic API shape - and LiteLLM translates. Stand up a LiteLLM
proxy, register the Azure or Bedrock deployments there, and point Claude
Code at LiteLLM. Typical model-ID overrides look like
`azure/my-sonnet-deployment` or
`bedrock/anthropic.claude-sonnet-4-20250514-v1:0`; put them in the
`ANTHROPIC_DEFAULT_*_MODEL` vars above so every `sub_agent` call
automatically routes to the right deployment.

## Full variable reference

| Variable | Type | Default | Purpose | Example (placeholder) |
|----------|------|---------|---------|-----------------------|
| `ANTHROPIC_AUTH_TOKEN` | secret | unset | Bearer token for Anthropic / gateway | `sk-EXAMPLE-gateway-key` |
| `ANTHROPIC_BASE_URL` | URL | `https://api.anthropic.com` when `ANTHROPIC_AUTH_TOKEN` is set, otherwise unset | Where Claude Code sends requests | `https://litellm.internal/anthropic` |
| `ANTHROPIC_MODEL` | string | unset | Global default model for Claude Code | `anthropic/claude-sonnet-4-6` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | string | unset | Override for `sub_agent("sonnet")` | `azure/my-sonnet-deployment` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | string | unset | Override for `sub_agent("opus")` | `anthropic/claude-opus-4-6` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | string | unset | Override for `sub_agent("haiku")` | `anthropic/claude-haiku-4-5` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | string | unset | Model for Claude Code's internal sub-agents | `anthropic/claude-haiku-4-5` |
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` | flag | unset | Strip beta headers on outgoing requests | `1` |
| `DISABLE_PROMPT_CACHING` | flag | unset | Disable `cache_control` globally | `1` |
| `DISABLE_PROMPT_CACHING_SONNET` | flag | unset | Disable prompt caching for Sonnet only | `1` |
| `DISABLE_PROMPT_CACHING_OPUS` | flag | unset | Disable prompt caching for Opus only | `1` |
| `DISABLE_PROMPT_CACHING_HAIKU` | flag | unset | Disable prompt caching for Haiku only | `1` |

All of these are official Claude Code environment variables - see
<https://code.claude.com/docs/en/env-vars> for the upstream reference.
Open Computer Use passes them through unchanged when (and only when)
the operator sets them on the host.

## Verifying your gateway setup

1. Confirm the variables are in your `.env`:
   ```bash
   grep -E '^(ANTHROPIC|CLAUDE_CODE|DISABLE_PROMPT_CACHING)' .env
   ```
2. Recreate the orchestrator container so it picks up the new env:
   ```bash
   docker compose up -d computer-use-server
   ```
3. Confirm the orchestrator itself received the vars:
   ```bash
   docker inspect computer-use-server --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^(ANTHROPIC|CLAUDE_CODE|DISABLE_PROMPT_CACHING)'
   ```
4. Trigger a `sub_agent` call from the Computer Use tool inside Open
   WebUI (any short task - "list files in /tmp" is enough).
5. Confirm the sandbox container received the expected subset:
   ```bash
   docker exec owui-chat-<chatid> env | grep -E '^(ANTHROPIC|CLAUDE_CODE|DISABLE_PROMPT_CACHING)'
   ```
6. On Paths B and C the sub-agent should stream output without showing a
   `/login` prompt. If it still prompts, go to Troubleshooting.

## Troubleshooting

### "The sub-agent keeps asking me to `/login` even though I set `ANTHROPIC_AUTH_TOKEN`."

Two checks, in order:

1. Confirm the orchestrator container actually received the env variable
   via step 3 of the verification checklist. If it is missing, make sure
   `ANTHROPIC_AUTH_TOKEN` is declared under
   `services.computer-use-server.environment:` in `docker-compose.yml`
   (it is, on current `main`) and that you recreated the container after
   editing `.env`. `docker compose up -d` does not pick up `.env` changes
   on already-running services without `--force-recreate` or `down`/`up`.
2. Confirm you are on a version with the Phase 3 `context_vars.py` fix
   (<https://github.com/Yambr/open-computer-use/issues/40>). Earlier
   versions had a ContextVar default of `"https://api.anthropic.com/"`
   that short-circuited the `or os.environ["ANTHROPIC_BASE_URL"]` fallback
   in `docker_manager`. Symptom: the sandbox received
   `ANTHROPIC_BASE_URL=https://api.anthropic.com/` (with a stray trailing
   slash) but `ANTHROPIC_AUTH_TOKEN` was not injected.

### "LiteLLM returns 400 about prompt caching."

LiteLLM typically does not forward Anthropic's `cache_control` blocks to
the upstream model; Claude Code sends them by default. Set
`DISABLE_PROMPT_CACHING=1` on the host. If you route different model
families through different upstreams, use the per-family flags
(`DISABLE_PROMPT_CACHING_SONNET`, `_OPUS`, `_HAIKU`) instead of the
global one.

### "LiteLLM returns 400 about beta / experimental headers."

Set `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`. This strips the
`anthropic-beta` header Claude Code adds on newer features that gateways
may not forward yet.

## Further reading

- Claude Code env var reference - <https://code.claude.com/docs/en/env-vars>
- LLM gateway / LiteLLM recipe - <https://code.claude.com/docs/en/llm-gateway>
- Model configuration and aliases - <https://code.claude.com/docs/en/model-config>
