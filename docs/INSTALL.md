# Installation Guide

This guide is for **self-hosting**. For the managed version (GitHub/Google sign-in, no Docker), see [CLOUD.md](CLOUD.md) or try [chat.yambr.com](https://chat.yambr.com) directly.

## Prerequisites

- **Docker Engine** 24+ with Docker Compose v2
- **8 GB RAM** minimum (16 GB recommended)
- **20 GB disk** (sandbox image is ~5 GB)

## Quick Start

```bash
git clone https://github.com/Yambr/open-computer-use.git
cd open-computer-use
cp .env.example .env
# Edit .env — see the REQUIRED section at the top of .env.example.

# 1. Pre-flight: catch common misconfigurations before docker starts
./scripts/check-config.sh

# 2. Build and start Computer Use Server (~15 min first time)
docker compose up --build

# 3. Start Open WebUI (in another terminal)
docker compose -f docker-compose.webui.yml up --build
```

`scripts/check-config.sh` reports `[OK]` / `[WARN]` / `[ERR]` for each setting and exits 1 if anything is likely to break end-to-end (e.g. `PUBLIC_BASE_URL` left at the internal-DNS default, half-configured Vision group). WARNs are fine for local dev.

**Re-seeding Valves after editing `.env`.** The `open-webui` container runs an init script that writes Open WebUI Valves from env **on first start only** — a marker file (`/app/backend/data/.computer-use-initialized`) guards re-runs so your admin UI edits are never clobbered. The only env propagated into Valves is `ORCHESTRATOR_URL` (the internal URL, consumed by both the Computer Use tool and filter). To pick up a new value, delete the marker on `open-webui` and restart it:

```bash
docker compose -f docker-compose.webui.yml exec open-webui \
    rm /app/backend/data/.computer-use-initialized
docker compose -f docker-compose.webui.yml restart open-webui
```

`PUBLIC_BASE_URL` lives only on the `computer-use-server` container — it is **not** propagated into Open WebUI Valves. If you change it in `.env`, restart the server container instead: `docker compose up -d --force-recreate computer-use-server`.

Open http://localhost:3000 — login with `admin@open-computer-use.dev` / `admin`.

## Configuration

Edit `.env` before starting. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | LLM API key (any OpenAI-compatible provider) |
| `OPENAI_API_BASE_URL` | No | Custom API URL (OpenRouter, local vLLM, etc.) |
| `MCP_API_KEY` | Recommended | Bearer token for MCP endpoint security |
| `ANTHROPIC_AUTH_TOKEN` | No | For Claude Code sub-agent |
| `VISION_API_KEY` | No | For describe-image skill |
| `CHAT_RESPONSE_MAX_TOOL_CALL_RETRIES`, `TOOL_RESULT_MAX_CHARS`, `TOOL_RESULT_PREVIEW_CHARS`, `ORCHESTRATOR_URL` | No | Settings on the **`open-webui` container** (not CU-server). Required for multi-step tasks, large tool results, and preview rendering. Full guide: [README.md → Required setup when embedding Open WebUI](../README.md#required-setup-when-embedding-open-webui-into-your-own-stack). |

See `.env.example` for the full list with defaults.

Routing Claude Code through a custom gateway (LiteLLM / Azure / Bedrock)? See [claude-code-gateway.md](claude-code-gateway.md) for the full recipe.

## Model Settings

After login, go to your model settings and set:

| Setting | Value | Why |
|---------|-------|-----|
| **Function Calling** | `Native` | Required for tools to work |
| **Stream Chat Response** | `On` | Real-time output |

The init script auto-creates a workspace model with these settings, but verify if using a different model.

## Verification

```bash
# Server health
curl http://localhost:8081/health
# → {"status":"healthy"}

# Open WebUI
curl -s http://localhost:3000 | head -1
# → <!DOCTYPE html>

# Run project tests
./tests/test-no-corporate.sh
./tests/test-project-structure.sh
```

## Troubleshooting

### "Model not found" or tool calls fail
- Check **Function Calling** is set to `Native` in model settings
- Verify `OPENAI_API_KEY` is correct: `curl -H "Authorization: Bearer $OPENAI_API_KEY" $OPENAI_API_BASE_URL/models`

### Container creation timeout
- First run downloads the sandbox image (~5 GB). Wait for `docker compose up --build` to finish.
- Check Docker has enough resources: `docker system info | grep Memory`

### Files not appearing in preview
- Verify `BASE_DATA_DIR` and `USER_DATA_BASE_PATH` match in docker-compose.yml
- Check: `curl http://localhost:8081/api/outputs/{chat_id}`

### Connection refused from Open WebUI
- Verify the Computer Use Server stack is up: `docker compose ps`
- Verify Open WebUI's `ORCHESTRATOR_URL` points at the service DNS URL `http://computer-use-server:8081`. The two compose stacks share the default Docker network because they share the project name (the parent directory `open-computer-use`), so `computer-use-server` resolves directly — no `host.docker.internal` / `extra_hosts` needed.
- If you override the Compose project name (`-p myproj`) or set a custom `container_name:` on the server, point `ORCHESTRATOR_URL` at the new internal hostname. Then re-seed Valves (see Re-seeding section above).
- Quick check from inside the `open-webui` container: `docker compose -f docker-compose.webui.yml exec open-webui curl -sf http://computer-use-server:8081/health`.

## Architecture

See [DOCKER.md](DOCKER.md) for detailed Docker architecture and [MCP.md](MCP.md) for the MCP protocol reference.
