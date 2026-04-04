# Project Instructions

## Language

All code, comments, commit messages, PR titles, PR descriptions, documentation, and any text visible in the repository MUST be written in **English only**. No exceptions.

## Building Docker Image

Always build with `--platform linux/amd64`:

```bash
docker build --platform linux/amd64 -t open-computer-use:latest .
```

## Testing

After building the image or changing `Dockerfile`, `package.json`, `requirements.txt`, skills, or npm configuration — run tests:

```bash
./tests/test-docker-image.sh [image-name]
./tests/test-no-corporate.sh
./tests/test-project-structure.sh
```

Default image: `open-computer-use:latest`.

Tests verify: npm packages (CommonJS `require()`, ESM `import`), CLI tools (mmdc, tsc, tsx, claude), Python packages, Playwright, html2pptx, volume size (`/home/assistant/` < 1MB), file permissions, project structure, no corporate references.

## npm Packages Layout

Packages are installed outside `/home/assistant` (volume mount point) to avoid duplication per container:

| Path | Contents | Storage |
|------|----------|---------|
| `/home/node_modules/` | Libraries (react, pptxgenjs, pdf-lib...) | Image layer (shared) |
| `/usr/local/lib/node_modules_global/` | CLI tools (mmdc, tsc, tsx, claude) | Image layer (shared) |
| `/home/assistant/node_modules/` | User-installed packages (`npm install`) | Volume (per-container) |

Node.js uses parent directory resolution: if a package isn't found in `/home/assistant/node_modules`, it looks in `/home/node_modules`.

## Versioning

Format: `v0.8.X.Y` — the first three segments (`0.8.X`) track the **Open WebUI** base version this project is built on. Never bump them independently.

- **Patch release** (`Y+1`): bug fixes, security patches, dependency bumps, test additions → e.g. `v0.8.12.3` → `v0.8.12.4`
- **Minor release** (`X+1`, reset `Y=0`): new features, new tools, significant changes → only when Open WebUI base version also bumps

To release:
1. Update `CHANGELOG.md` with the new version heading
2. Commit: `chore: release vX.X.X.X`
3. Tag: `git tag vX.X.X.X && git push origin main --tags`

## Project Structure

- `Dockerfile` — Sandbox container image (Ubuntu 24.04, Python, Node.js, CDP, ttyd)
- `computer-use-server/` — MCP orchestrator (FastAPI, Docker management, CDP/terminal proxy)
- `openwebui/` — Open WebUI integration (tools, functions, patches)
- `skills/` — AI skills (pptx, xlsx, docx, pdf, sub-agent, playwright-cli, etc.)
- `docs/` — Documentation
- `tests/` — Test scripts
- `docker-compose.yml` — Computer Use Server
- `docker-compose.webui.yml` — Open WebUI + PostgreSQL (connects to server via `host.docker.internal`)

## License Headers

All new source files MUST include an SPDX license header as the first comment:

- Files in `skills/public/describe-image/` or `skills/public/sub-agent/`: `# SPDX-License-Identifier: MIT`
- Files in other `skills/` directories with their own LICENSE.txt: DO NOT add headers
- All other new files: `# SPDX-License-Identifier: BUSL-1.1`

Always include: `# Copyright (c) 2025 Open Computer Use Contributors`
