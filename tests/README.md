# Tests

Validation scripts for the project. Run before submitting PRs.

## Running Tests

```bash
# All tests (no Docker required for first two)
./tests/test-no-corporate.sh
./tests/test-project-structure.sh

# Requires built Docker image
./tests/test-docker-image.sh [image-name]
```

Default image: `open-computer-use:latest`.

## Test Scripts

| Script | What it validates | Docker required |
|--------|-------------------|-----------------|
| `test-no-corporate.sh` | No corporate/internal references leak into codebase | No |
| `test-project-structure.sh` | Correct directory structure (12 checks) | No |
| `test-docker-image.sh` | Docker image contents: npm packages, CLI tools, Python packages, Playwright, volume size, permissions | Yes |

## test-no-corporate.sh

Scans all project files against patterns in `corporate-patterns.txt`. Catches internal domains, hardcoded API keys, registry URLs, and service accounts that shouldn't be in open-source code.

## test-project-structure.sh

Verifies the expected project layout: `computer-use-server/`, `openwebui/`, required files, no legacy directories, docker-compose services, `.env.example` variables.

## test-docker-image.sh

Runs inside the Docker image to verify:
- Node.js CommonJS `require()` and ESM `import` work
- CLI tools available: `mmdc`, `tsc`, `tsx`, `claude`
- Python packages: `docx`, `pptx`, `openpyxl`, `playwright`
- npm package layout (`/home/node_modules/` vs `/home/assistant/`)
- Volume size (`/home/assistant/` < 1MB — packages should be outside)
- File permissions and guard files
