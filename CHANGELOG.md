# Changelog

## v0.8.12.3 (2026-04-01)

### Security
- Fix 28 GitHub CodeQL security alerts: path traversal, XSS, URL redirect vulnerabilities
- Centralized input sanitization via `security.py` (sanitize_chat_id, safe_path)
- XSS prevention in file preview with same-origin checks
- SRI integrity for CDN resources
- 40+ security tests

### MCP Tools Best Practices
- **Output truncation**: bash_tool output capped at 30K chars (head+tail) to protect context window
- **Command semantics**: grep/find/diff exit code 1 is no longer treated as error (matches Claude Code behavior)
- **str_replace uniqueness**: errors when old_str matches multiple times, preventing accidental edits
- **view threshold**: increased from 16K to 30K for consistency with bash_tool
- **System prompt**: added tool usage tips (prefer view over cat, grep exit codes explained)
- 15 new unit tests for MCP tools

### Open WebUI Patches
- **fix_large_tool_results**: truncates large MCP tool results (>50K chars) to prevent context window exhaustion
  - Handles both Chat Completions and Responses API formats
  - Truncates current results in tool loop AND historical results from DB
  - Optional upload of full results via DOCKER_AI_UPLOAD_URL
  - Config: `TOOL_RESULT_MAX_CHARS` (default 50000), `TOOL_RESULT_PREVIEW_CHARS` (default 2000)
  - 10 new unit tests

## v1.0.0 - Initial Open Source Release (2026-03-30)

### Features
- **MCP Server**: Computer Use orchestrator with full MCP (Model Context Protocol) support
- **Docker Sandbox**: Isolated Ubuntu 24.04 containers with Python 3.12, Node.js 22, Java 21
- **CDP Browser**: Live browser viewer via Chrome DevTools Protocol proxy
- **Terminal**: Interactive terminal via ttyd + tmux + xterm.js
- **Claude Code**: Pre-installed Claude Code CLI with TTY support
- **Skills System**: 13 built-in public skills + 14 examples (pptx, docx, xlsx, pdf, sub-agent, playwright-cli, and more)
- **Open WebUI Integration**: Docker-compose stack with patched Open WebUI + PostgreSQL
- **Tools**: bash, str_replace, create_file, view, sub_agent
- **File Server**: Upload/download with archive support

### Included Tools
- Playwright (Chromium), LibreOffice, Tesseract OCR, FFmpeg, Pandoc
- ImageMagick, Graphviz, Mermaid CLI
- Python: docx, pptx, openpyxl, pypdf, Pillow, OpenCV, pandas, numpy
- Node.js: React, TypeScript, pdf-lib, pptxgenjs, sharp
