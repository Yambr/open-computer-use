# Project Instructions

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

## Project Structure

- `Dockerfile` — Sandbox container image (Ubuntu 24.04, Python, Node.js, CDP, ttyd)
- `computer-use-server/` — MCP orchestrator (FastAPI, Docker management, CDP/terminal proxy)
- `openwebui/` — Open WebUI integration (tools, functions, patches)
- `skills/` — AI skills (pptx, xlsx, docx, pdf, sub-agent, playwright-cli, etc.)
- `docs/` — Documentation
- `tests/` — Test scripts
- `docker-compose.yml` — Full stack (Open WebUI + PostgreSQL + Computer Use Server)
