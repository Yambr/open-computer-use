# Installation Guide

## Prerequisites

- **Docker Engine** 24+ with Docker Compose v2
- **8 GB RAM** minimum (16 GB recommended)
- **20 GB disk** (sandbox image is ~5 GB)

## Quick Start

```bash
git clone https://github.com/Yambr/openwebui-computer-use-community.git
cd openwebui-computer-use-community
cp .env.example .env
# Edit .env — set OPENAI_API_KEY (or any OpenAI-compatible provider)

# 1. Build and start Computer Use Server (~15 min first time)
docker compose up --build

# 2. Start Open WebUI (in another terminal)
docker compose -f docker-compose.webui.yml up --build
```

Open http://localhost:3000 — login with `admin@open-computer-use.dev` / `admin`.

## Configuration

Edit `.env` before starting. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | LLM API key (any OpenAI-compatible provider) |
| `OPENAI_API_BASE_URL` | No | Custom API URL (OpenRouter, local vLLM, etc.) |
| `MCP_API_KEY` | Recommended | Bearer token for MCP endpoint security |
| `ANTHROPIC_API_KEY` | No | For Claude Code sub-agent |
| `VISION_API_KEY` | No | For describe-image skill |

See `.env.example` for the full list with defaults.

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
- Open WebUI and Computer Use Server are in separate Docker networks
- `docker-compose.webui.yml` uses `host.docker.internal` — this works on Docker Desktop (Mac/Windows)
- On Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the service

## Architecture

See [DOCKER.md](DOCKER.md) for detailed Docker architecture and [MCP.md](MCP.md) for the MCP protocol reference.
