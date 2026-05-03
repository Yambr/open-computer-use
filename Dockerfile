# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
# AI Computer Use - Dockerfile
# Based on Ubuntu 24.04 Noble Numbat

FROM ubuntu:24.04

LABEL maintainer="OpenWebUI Implementation"
LABEL description="AI Computer Use Environment"
LABEL version="1.0.0"

# Claude Code version. Pinned to 2.1.112 — the last release that ships the
# package as plain JS (cli.js in the tarball). Starting with 2.1.113 the pkg
# repackaged to a postinstall loader (install.cjs) that downloads a native
# claude.exe binary and drops cli.js entirely, which breaks our bun-wrapper
# shim below ("Module not found .../cli.js"). Do NOT bump to 2.1.113+ without
# also removing the wrapper and verifying the native binary works under Bun.
ARG CLAUDE_CODE_VERSION=2.1.112

# Codex CLI version. Pinned per RESEARCH STACK.md and Pitfall 6 (CLI version
# drift breaks adapter contract while tests stay green). Bump only after
# re-running tests/orchestrator/test_cli_adapters.py against the new release.
ARG CODEX_VERSION=0.125.0

# OpenCode (sst fork — opencode-ai on npm, NOT the unrelated similarly-named
# package). See RESEARCH STACK.md for fork rationale. The npm package
# downloads platform binaries from GitHub Releases at install time; pinning
# the version neutralises URL drift (Pitfall 6).
ARG OPENCODE_VERSION=1.14.25

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_PATH=/home/node_modules:/usr/local/lib/node_modules_global/lib/node_modules \
    PATH=/usr/local/lib/node_modules_global/bin:/home/assistant/.local/bin:/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
    JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    GLAB_NO_UPDATE_NOTIFIER=1

# Update and install system packages
RUN apt-get update && apt-get install -y \
    # Build essentials
    build-essential \
    gcc \
    g++ \
    make \
    binutils \
    dpkg-dev \
    # Python
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    # Node.js (will install specific version later)
    curl \
    wget \
    ca-certificates \
    gnupg \
    # Git and version control
    git \
    # Compression tools
    zip \
    unzip \
    bzip2 \
    # Text editors
    vim \
    nano \
    # Image processing dependencies
    libmagickwand-dev \
    imagemagick \
    # Graphics libraries
    libcairo2-dev \
    libpango1.0-dev \
    libjpeg-dev \
    libgif-dev \
    librsvg2-dev \
    # OCR dependencies
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-rus \
    # PDF dependencies
    poppler-utils \
    ghostscript \
    qpdf \
    # Document conversion
    pandoc \
    # Video/audio processing
    ffmpeg \
    # Java (for tabula-py and LibreOffice)
    default-jre-headless \
    openjdk-21-jre-headless \
    # LibreOffice (for unoserver)
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    # Fonts
    fontconfig \
    fonts-liberation \
    fonts-liberation2 \
    fonts-dejavu \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    fonts-freefont-ttf \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    # Graphics and rendering
    graphviz \
    # System utilities
    bc \
    file \
    jq \
    dbus \
    # Networking
    socat \
    apt-transport-https \
    libnss3-tools \
    # Terminal sharing (tmux for persistent sessions, ttyd installed separately)
    tmux \
    sudo \
    inotify-tools \
    # Clean up
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22.x via binary distribution (more reliable than nodesource)
RUN curl -fsSL https://nodejs.org/dist/v22.11.0/node-v22.11.0-linux-x64.tar.xz -o /tmp/node.tar.xz \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
    && rm /tmp/node.tar.xz

# Install Bun runtime (required for Claude Code)
RUN curl -fsSL https://bun.sh/install | bash && \
    mv /root/.bun/bin/bun /usr/local/bin/ && \
    rm -rf /root/.bun

# Verify versions
RUN python3 --version && \
    node --version && \
    npm --version

# Create python symlink to python3 for compatibility
# Many scripts and tools expect 'python' command to be available
RUN ln -s /usr/bin/python3 /usr/bin/python

# Create a non-root user with sudo access FIRST
RUN useradd -m -s /bin/bash assistant && \
    echo "assistant ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Configure npm global directory and sudo to preserve needed ENV variables
RUN mkdir -p /usr/local/lib/node_modules_global && \
    chown -R assistant:assistant /usr/local/lib/node_modules_global && \
    echo 'Defaults env_keep += "NODE_PATH PLAYWRIGHT_BROWSERS_PATH PATH JAVA_HOME NODE_EXTRA_CA_CERTS REQUESTS_CA_BUNDLE SSL_CERT_FILE PYTHONUNBUFFERED PIP_ROOT_USER_ACTION PIP_BREAK_SYSTEM_PACKAGES PYTHONDONTWRITEBYTECODE"' >> /etc/sudoers

# Copy and install Python dependencies (as root first for system-wide availability)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages --ignore-installed \
    -r /tmp/requirements.txt

# Pre-register Cyrillic and Emoji fonts in reportlab
# Append font registration to reportlab/__init__.py (runs after full initialization)
RUN REPORTLAB_INIT=$(python3 -c "import reportlab; print(reportlab.__file__)") && \
    printf '\n# Auto-register Cyrillic and Emoji fonts\ntry:\n    from reportlab.pdfbase import pdfmetrics\n    from reportlab.pdfbase.ttfonts import TTFont\n    from reportlab.pdfbase.pdfmetrics import registerFontFamily\n    pdfmetrics.registerFont(TTFont("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))\n    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))\n    pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"))\n    pdfmetrics.registerFont(TTFont("DejaVuSans-BoldOblique", "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"))\n    registerFontFamily("DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold", italic="DejaVuSans-Oblique", boldItalic="DejaVuSans-BoldOblique")\n    pdfmetrics.registerFont(TTFont("NotoEmoji", "/usr/share/fonts/truetype/custom/NotoEmoji-Regular.ttf"))\nexcept Exception:\n    pass\n' >> "$REPORTLAB_INIT"

# Install Node.js dependencies: global CLI tools + local packages in /home/node_modules
# Global install: CLI tools (npx mmdc, tsc, tsx) → /usr/local/lib/node_modules_global
# Local install: /home/node_modules (parent directory trick for ES modules + CommonJS)
#   Volume mounts on /home/assistant → /home/node_modules stays in image layer, shared
#   Node.js resolves: /home/assistant/node_modules (volume) → /home/node_modules (image)
COPY package.json /tmp/package.json
RUN chown assistant:assistant /tmp/package.json && \
    cd /tmp && \
    sudo -u assistant bash -c "npm config set prefix '/usr/local/lib/node_modules_global' && npm install -g \$(node -pe \"Object.entries(require('./package.json').dependencies).map(([pkg, ver]) => pkg + '@' + ver).join(' ')\")"

# Install packages in /home/node_modules for ES modules import support
# This is OUTSIDE /home/assistant (volume mount point), so it stays in image layer
COPY package.json /home/package.json
RUN mkdir -p /home/node_modules && \
    chown assistant:assistant /home/package.json /home/node_modules && \
    cd /home && \
    sudo -u assistant bash -c "npm install --prefer-offline --no-package-lock" && \
    rm -f /home/package.json

# Install Playwright browsers (only once, shared by both Python and Node.js)
RUN python3 -m playwright install --with-deps chromium && \
    chmod -R 755 /opt/pw-browsers && \
    chown -R assistant:assistant /opt/pw-browsers

# Copy and install custom fonts
COPY fonts/ /usr/share/fonts/truetype/custom/
RUN fc-cache -f -v

# Create directory structure with proper ownership
RUN mkdir -p /mnt/user-data/uploads \
             /mnt/user-data/outputs \
             /mnt/skills \
             /mnt/transcripts && \
    chown -R root:root /mnt/user-data/uploads /mnt/skills && \
    chown -R assistant:assistant /mnt/user-data/outputs /mnt/transcripts && \
    chmod 755 /mnt/user-data/uploads /mnt/skills && \
    chmod 755 /mnt/user-data/outputs /mnt/transcripts

# Install html2pptx from local .tgz file (required for PPTX skill)
# Copy only the .tgz to avoid invalidating cache when other skills change
COPY --chown=assistant:assistant ./skills/public/pptx/html2pptx.tgz /tmp/html2pptx.tgz
RUN sudo -u assistant bash -c "cd /tmp && npm install -g /tmp/html2pptx.tgz" && \
    rm -f /tmp/html2pptx.tgz && \
    ln -s /usr/local/lib/node_modules_global/lib/node_modules/@ant /home/node_modules/@ant

# Install glab CLI for GitLab operations
RUN curl -fsSL https://gitlab.com/gitlab-org/cli/-/releases/v1.52.0/downloads/glab_1.52.0_linux_amd64.tar.gz \
    | tar -xzf - -C /tmp && \
    mv /tmp/bin/glab /usr/local/bin/glab && \
    chmod +x /usr/local/bin/glab && \
    rm -rf /tmp/bin /tmp/LICENSE && \
    sudo -u assistant glab config set check_update false --global

# xdg-open wrapper: routes browser-open through playwright-cli (CDP 9222)
RUN printf '#!/bin/bash\nplaywright-cli open "$1" 2>/dev/null &\n' > /usr/local/bin/xdg-open && \
    chmod +x /usr/local/bin/xdg-open

# Install Claude Code CLI from npm registry
RUN sudo -u assistant bash -c "npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"

# Install Codex CLI from npm registry (Phase 6 — sub-agent runtime alternative).
# Ships native linux-x64 binary via optionalDependencies; no Bun wrapper needed
# (unlike claude-code, which repackaged in 2.1.113 — see CLAUDE_CODE_VERSION note).
# Uses an isolated --cache dir to prevent postinstall scripts from corrupting
# the shared ~/.npm/_cacache (which would break later installs like @playwright/cli
# with EEXIST+ENOENT collisions on content-v2/sha512/X/Y shards).
RUN sudo -u assistant bash -c "mkdir -p /tmp/npm-codex-cache && npm install -g --cache /tmp/npm-codex-cache @openai/codex@${CODEX_VERSION} && rm -rf /tmp/npm-codex-cache"

# Install OpenCode CLI from npm registry (sst fork — Phase 6 third runtime).
# Native binary downloaded at npm-postinstall time from GitHub Releases.
# Same isolated --cache dir pattern as codex above (and for the same reason).
RUN sudo -u assistant bash -c "mkdir -p /tmp/npm-opencode-cache && npm install -g --cache /tmp/npm-opencode-cache opencode-ai@${OPENCODE_VERSION} && rm -rf /tmp/npm-opencode-cache /home/assistant/.npm/_cacache"

# Install Playwright CLI for browser automation (used by main AI via bash, Claude Code via skills)
# Version pinned — patch below depends on internal structure
RUN sudo -u assistant bash -c "npm install -g @playwright/cli@0.1.1" && \
    cd /home/assistant && sudo -u assistant npx @playwright/cli install --skills && \
    # Patch: fixed CDP port 9223 instead of random (for browser viewer on 9222 via socat) \
    FACTORY=$(find /usr/local/lib/node_modules_global/lib/node_modules/@playwright/cli -path "*/mcp/browser/browserContextFactory.js" | head -1) && \
    sed -i 's/browserConfig\.launchOptions\.cdpPort = await findFreePort()/browserConfig.launchOptions.cdpPort = 9223/' "$FACTORY" && \
    grep -q 'cdpPort = 9223' "$FACTORY" || (echo "PATCH FAILED: cdpPort not found in $FACTORY" && exit 1) && \
    echo "Playwright CLI patched: fixed CDP port 9223"

# Create wrapper: env config + socat for external CDP access
# Chromium listens on 127.0.0.1:9223 (patched), socat exposes on 0.0.0.0:9222 for viewer
# "open <url>" is split into "open" + sleep + "goto <url>" so browser-viewer has time
# to connect CDP and enable Fetch.authRequired interception before navigation starts
RUN ORIG=$(which playwright-cli) && \
    mv "$ORIG" "${ORIG}-orig" && \
    printf '#!/bin/bash\nexport PLAYWRIGHT_CLI_CONFIG="${PLAYWRIGHT_CLI_CONFIG:-/home/assistant/playwright-cli.json}"\nif ! pgrep -f "socat.*TCP-LISTEN:9222" >/dev/null 2>&1; then\n  socat TCP-LISTEN:9222,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:9223 &\nfi\nif [ "$1" = "open" ] && [ -n "$2" ] && [[ "$2" == http* ]]; then\n  URL="$2"\n  shift 2\n  playwright-cli-orig open "$@"\n  sleep 3\n  exec playwright-cli-orig goto "$URL"\nfi\nexec playwright-cli-orig "$@"\n' > "$ORIG" && \
    chmod +x "$ORIG"

# Install ttyd (WebSocket terminal server) — download binary for reliability
# Download binary directly from GitHub releases for reliability
RUN curl -fsSL https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 -o /usr/local/bin/ttyd && \
    chmod +x /usr/local/bin/ttyd

# CLAUDE.md is written by entrypoint (not here) because /home/assistant is a volume mount

# Enable MCP Tool Search — reduces tool context consumption by 85%
# Without this, 7+ MCP servers consume 50-70% of context on tool definitions
ENV ENABLE_TOOL_SEARCH=true \
    COLORTERM=truecolor \
    CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=50

# Create wrapper to run Claude Code with Bun runtime (fixes "Bun is not defined" error)
RUN mv /usr/local/lib/node_modules_global/bin/claude /usr/local/lib/node_modules_global/bin/claude-node && \
    printf '#!/bin/bash\nexec bun /usr/local/lib/node_modules_global/lib/node_modules/@anthropic-ai/claude-code/cli.js "$@"\n' > /usr/local/lib/node_modules_global/bin/claude && \
    chmod +x /usr/local/lib/node_modules_global/bin/claude

# Create entrypoint script that configures git/glab and Claude Code
# This runs on container start and sets up dynamic configuration based on env vars
RUN printf '#!/bin/bash\n\
# Configure GitLab\n\
if [ -n "$GITLAB_TOKEN" ]; then\n\
    GITLAB_HOST="${GITLAB_HOST:-gitlab.com}"\n\
    git config --global url."https://oauth2:${GITLAB_TOKEN}@${GITLAB_HOST}/".insteadOf "https://${GITLAB_HOST}/"\n\
    echo "Git configured for $GITLAB_HOST with token auth"\n\
else\n\
    echo "No GITLAB_TOKEN - git/glab will work without auth (public repos only)"\n\
fi\n\
\n\
# Configure Claude Code\n\
if [ -n "$ANTHROPIC_AUTH_TOKEN" ]; then\n\
    export ANTHROPIC_AUTH_TOKEN\n\
    export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"\n\
    if [ -n "$ANTHROPIC_CUSTOM_HEADERS" ]; then\n\
        export ANTHROPIC_CUSTOM_HEADERS\n\
    fi\n\
    echo "Claude Code configured with base URL: $ANTHROPIC_BASE_URL"\n\
else\n\
    echo "No ANTHROPIC_AUTH_TOKEN - Claude Code will not work"\n\
fi\n\
\n\
# Discoverability: how to escape sub-agent autostart\n\
echo "Tip: plain bash with NO_AUTOSTART=1 bash  OR  touch /tmp/.no_autostart"\n\
\n\
# Configure Playwright CLI for browser automation\n\
cat > /home/assistant/playwright-cli.json << PCLIEOF\n\
{\n\
  "outputDir": "/mnt/user-data/outputs",\n\
  "browser": {\n\
    "launchOptions": {\n\
      "args": [\n\
        "--disable-blink-features=AutomationControlled",\n\
        "--disable-infobars",\n\
        "--no-first-run",\n\
        "--disable-background-timer-throttling",\n\
        "--disable-backgrounding-occluded-windows",\n\
        "--disable-renderer-backgrounding",\n\
        "--disable-dev-shm-usage",\n\
        "--disable-default-apps",\n\
        "--disable-sync",\n\
        "--disable-breakpad",\n\
        "--disable-hang-monitor",\n\
        "--disable-prompt-on-repost",\n\
        "--metrics-recording-only",\n\
        "--no-default-browser-check",\n\
        "--window-size=1920,1080"\n\
      ]\n\
    },\n\
    "contextOptions": {\n\
      "navigationTimeout": 300000,\n\
      "extraHTTPHeaders": {\n\
      }\n\
    }\n\
  }\n\
}\n\
PCLIEOF\n\
\n\
mkdir -p /home/assistant/.claude\n\
# Write CLAUDE.md (environment info for Claude Code — same for interactive and MCP sub-agent)\n\
cat > /home/assistant/.claude/CLAUDE.md << CLAUDEMDEOF\n\
# Environment\n\
\n\
## File Locations\n\
- **Workspace**: /home/assistant (working directory)\n\
- **User uploads**: /mnt/user-data/uploads (read-only, files from user)\n\
- **Output files**: /mnt/user-data/outputs (save results here — auto-synced to preview)\n\
- **Skills**: /mnt/skills/ (read-only, run: cat /mnt/skills/<name>/SKILL.md)\n\
\n\
## Output Rules\n\
- Save ALL user-facing files to /mnt/user-data/outputs/\n\
- Files in outputs automatically appear in the preview UI under the Files tab\n\
- When telling the user where to find files, say: open the Files tab in the artifacts panel\n\
- Workspace /home/assistant is for intermediate files only, not synced\n\
\n\
## Plan Mode — MANDATORY\n\
CRITICAL: You MUST enter plan mode BEFORE writing ANY code or creating files.\n\
This applies to ALL tasks except single-line fixes (typos, variable renames).\n\
If you skip plan mode, the user will reject your work.\n\
If something goes sideways, STOP and re-plan immediately — do not keep pushing.\n\
Plan must include: what files to create, architecture decisions, verification steps.\n\
\n\
## Verification\n\
Before completing any task:\n\
1. Verify output files exist in /mnt/user-data/outputs/\n\
2. Run the code or check the result\n\
3. If tests exist, run them\n\
\n\
## Self-Improvement\n\
When you make a mistake, update this CLAUDE.md so you do not repeat it.\n\
\n\
## Useful Commands\n\
- ls /mnt/skills/ — list available skills\n\
- cat /mnt/skills/<name>/SKILL.md — skill instructions\n\
- ls /mnt/user-data/uploads/ — user-uploaded files\n\
- GSD (Get Shit Done): /gsd:help in Claude Code for spec-driven workflow commands\n\
- Superpowers skills: test-driven-development, brainstorming, systematic-debugging, etc.\n\
\n\
CLAUDEMDEOF\n\
cat > /home/assistant/.claude/settings.json << CCEOF\n\
{\n\
  "permissions": {\n\
    "allow": [\n\
      "Bash(playwright-cli:*)",\n\
      "Bash(*mnt/user-data/outputs*)",\n\
      "Write(/mnt/user-data/outputs/**)",\n\
      "Edit(/mnt/user-data/outputs/**)",\n\
      "Read(/mnt/user-data/outputs/**)",\n\
      "Read(/mnt/user-data/uploads/**)",\n\
      "Read(/mnt/skills/**)",\n\
      "Read(/home/assistant/.claude/**)",\n\
      "Write(/home/assistant/.claude/CLAUDE.md)",\n\
      "Write(/home/assistant/.claude/settings.json)",\n\
      "Edit(/home/assistant/.claude/CLAUDE.md)",\n\
      "Edit(/home/assistant/.claude/settings.json)",\n\
      "Bash(gsd:*)",\n\
      "Bash(ls*)",\n\
      "Bash(cat*)",\n\
      "Bash(mkdir*)",\n\
      "Bash(cp*)",\n\
      "Bash(mv*)"\n\
    ]\n\
  },\n\
  "hooks": {\n\
    "SessionStart": [\n\
      {"hooks": [{"type": "command", "command": "[ -f /home/assistant/.claude/hooks/gsd-check-update.js ] && node /home/assistant/.claude/hooks/gsd-check-update.js || true"}]},\n\
      {"hooks": [{"type": "command", "command": "[ -f /home/assistant/.claude/hooks/gsd-session-state.sh ] && bash /home/assistant/.claude/hooks/gsd-session-state.sh || true"}]}\n\
    ],\n\
    "PreToolUse": [\n\
      {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "[ -f /home/assistant/.claude/hooks/gsd-prompt-guard.js ] && node /home/assistant/.claude/hooks/gsd-prompt-guard.js || true", "timeout": 5}]},\n\
      {"matcher": "Read", "hooks": [{"type": "command", "command": "[ -f /home/assistant/.claude/hooks/gsd-read-guard.js ] && node /home/assistant/.claude/hooks/gsd-read-guard.js || true", "timeout": 5}]},\n\
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "[ -f /home/assistant/.claude/hooks/gsd-validate-commit.sh ] && bash /home/assistant/.claude/hooks/gsd-validate-commit.sh || true", "timeout": 5}]},\n\
      {"matcher": "", "hooks": [{"type": "command", "command": "[ -f /home/assistant/.claude/hooks/gsd-workflow-guard.js ] && node /home/assistant/.claude/hooks/gsd-workflow-guard.js || true", "timeout": 5}]}\n\
    ],\n\
    "PostToolUse": [\n\
      {"matcher": "Bash|Edit|Write|MultiEdit|Agent|Task", "hooks": [{"type": "command", "command": "[ -f /home/assistant/.claude/hooks/gsd-context-monitor.js ] && node /home/assistant/.claude/hooks/gsd-context-monitor.js || true", "timeout": 10}]},\n\
      {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "[ -f /home/assistant/.claude/hooks/gsd-phase-boundary.sh ] && bash /home/assistant/.claude/hooks/gsd-phase-boundary.sh || true", "timeout": 5}]}\n\
    ]\n\
  }\n\
}\n\
CCEOF\n\
\n\
# Skip Claude Code onboarding (theme picker, trust dialog)\n\
# Write for both assistant (production) and root (test/fallback)\n\
CLAUDE_JSON='"'"'{"hasCompletedOnboarding":true,"lastOnboardingVersion":"99.0.0","projects":{"/home/assistant":{"hasTrustDialogAccepted":true},"/":{"hasTrustDialogAccepted":true}}}'"'"'\n\
echo "$CLAUDE_JSON" > /home/assistant/.claude.json\n\
echo "$CLAUDE_JSON" > /root/.claude.json 2>/dev/null\n\
\n\
# Symlink each skill individually so Claude Code /skills sees them (flat structure required)\n\
mkdir -p /home/assistant/.claude/skills\n\
mkdir -p /root/.claude/skills 2>/dev/null\n\
for skilldir in /mnt/skills/public/ /mnt/skills/private/ /mnt/skills/user/; do\n\
    for skill in ${skilldir}*/; do\n\
        [ -d "$skill" ] && ln -sf "$skill" /home/assistant/.claude/skills/$(basename "$skill") 2>/dev/null\n\
        [ -d "$skill" ] && ln -sf "$skill" /root/.claude/skills/$(basename "$skill") 2>/dev/null\n\
    done\n\
done\n\
\n\
# External skills (GSD + Superpowers) — SYMLINK into volume to keep /home/assistant small\n\
# (per-container volume — see commit 934197d "Move npm packages out of volume mount")\n\
# GSD get-shit-done/ is read-only: cache lives in ~/.cache/gsd/, state in project .planning/\n\
mkdir -p /home/assistant/.claude/agents /home/assistant/.claude/commands /home/assistant/.claude/hooks\n\
if [ -d /opt/skills-external/gsd ]; then\n\
    ln -sfn /opt/skills-external/gsd/get-shit-done /home/assistant/.claude/get-shit-done\n\
    for f in /opt/skills-external/gsd/agents/*.md; do\n\
        [ -e "$f" ] && ln -sfn "$f" /home/assistant/.claude/agents/$(basename "$f")\n\
    done\n\
    ln -sfn /opt/skills-external/gsd/commands/gsd /home/assistant/.claude/commands/gsd\n\
    for h in /opt/skills-external/gsd/hooks/*; do\n\
        [ -e "$h" ] && ln -sfn "$h" /home/assistant/.claude/hooks/$(basename "$h")\n\
    done\n\
fi\n\
if [ -d /opt/skills-external/superpowers ]; then\n\
    for d in /opt/skills-external/superpowers/skills/*/; do\n\
        name=$(basename "$d")\n\
        [ -e "/home/assistant/.claude/skills/$name" ] || ln -sfn "$d" "/home/assistant/.claude/skills/$name"\n\
    done\n\
    for f in /opt/skills-external/superpowers/commands/*.md; do\n\
        [ -e "$f" ] && [ ! -e "/home/assistant/.claude/commands/$(basename "$f")" ] && ln -sfn "$f" /home/assistant/.claude/commands/$(basename "$f")\n\
    done\n\
    for f in /opt/skills-external/superpowers/agents/*.md; do\n\
        [ -e "$f" ] && [ ! -e "/home/assistant/.claude/agents/$(basename "$f")" ] && ln -sfn "$f" /home/assistant/.claude/agents/$(basename "$f")\n\
    done\n\
fi\n\
chown -R --no-dereference $(id -u assistant 2>/dev/null || echo 1000):$(id -g assistant 2>/dev/null || echo 1000) /home/assistant/.claude 2>/dev/null || true\n\
\n\
# Copy CLAUDE.md and settings.json for root too\n\
cp /home/assistant/.claude/CLAUDE.md /root/.claude/CLAUDE.md 2>/dev/null\n\
cp /home/assistant/.claude/settings.json /root/.claude/settings.json 2>/dev/null\n\
\n\
# Phase 6 — render per-CLI config files once per container (marker-gated).\n\
# Marker is in /tmp (NOT volume) so an env-var change + restart re-renders\n\
# from scratch (AUTH-04). Distinct from openwebui/init.sh persistent marker.\n\
if [ ! -f /tmp/.cli-runtime-initialised ]; then\n\
    case "${SUBAGENT_CLI:-claude}" in\n\
        opencode)\n\
            mkdir -p /tmp\n\
            if [ -n "${OPENCODE_CONFIG_EXTRA:-}" ]; then\n\
                printf "%s" "$OPENCODE_CONFIG_EXTRA" > /tmp/opencode.json\n\
                echo "OpenCode config sourced from OPENCODE_CONFIG_EXTRA (operator override; canonical block skipped)"\n\
            else\n\
                cat > /tmp/opencode.json <<'"'"'OCEOF'"'"'\n\
{\n\
  "$schema": "https://opencode.ai/config.json",\n\
  "provider": {\n\
    "openrouter": {\n\
      "options": { "apiKey": "{env:OPENROUTER_API_KEY}" }\n\
    },\n\
    "openai": {\n\
      "options": { "apiKey": "{env:OPENAI_API_KEY}" }\n\
    },\n\
    "anthropic": {\n\
      "options": { "apiKey": "{env:ANTHROPIC_API_KEY}" }\n\
    }\n\
  },\n\
  "model": "anthropic/claude-sonnet-4-6"\n\
}\n\
OCEOF\n\
                echo "OpenCode config rendered to /tmp/opencode.json (env-substituted, no plaintext secrets)"\n\
            fi\n\
            export OPENCODE_CONFIG=/tmp/opencode.json\n\
            ;;\n\
        codex)\n\
            mkdir -p /home/assistant/.codex\n\
            if [ -n "${OPENAI_BASE_URL:-}" ]; then\n\
                cat > /home/assistant/.codex/config.toml <<CXEOF\n\
model_provider = "custom"\n\
\n\
[model_providers.custom]\n\
name = "custom-gateway"\n\
base_url = "${OPENAI_BASE_URL}"\n\
env_key = "OPENAI_API_KEY"\n\
wire_api = "responses"\n\
requires_openai_auth = true\n\
CXEOF\n\
                echo "Codex config rendered with custom gateway: $OPENAI_BASE_URL"\n\
            else\n\
                : > /home/assistant/.codex/config.toml\n\
                echo "Codex config empty — public OpenAI defaults"\n\
            fi\n\
            if [ -n "${CODEX_CONFIG_EXTRA:-}" ]; then\n\
                printf "\\n# === CODEX_CONFIG_EXTRA (operator-supplied) ===\\n%s\\n" "$CODEX_CONFIG_EXTRA" >> /home/assistant/.codex/config.toml\n\
                echo "Codex config extended via CODEX_CONFIG_EXTRA"\n\
            fi\n\
            chown -R assistant:assistant /home/assistant/.codex\n\
            ;;\n\
    esac\n\
    touch /tmp/.cli-runtime-initialised\n\
fi\n\
\n\
# Auto-start chosen sub-agent CLI on first interactive bash login (both users).\n\
# Honours SUBAGENT_CLI (default claude). Escape hatches: NO_AUTOSTART=1 env\n\
# OR `touch /tmp/.no_autostart` from a second terminal to opt subsequent sessions out.\n\
# Marker renamed from the old per-CLI name to SUBAGENT_AUTOSTARTED (independent\n\
# check; existing volumes with the old marker still autostart exactly once on next session).\n\
AUTOSTART_LINE='"'"'[ -z "$SUBAGENT_AUTOSTARTED" ] && [ -z "$NO_AUTOSTART" ] && [ ! -f /tmp/.no_autostart ] && [ -n "$PS1" ] && export SUBAGENT_AUTOSTARTED=1 && exec "${SUBAGENT_CLI:-claude}"'"'"'\n\
for rc in /home/assistant/.bashrc /root/.bashrc; do\n\
    if [ ! -f "$rc" ] || ! grep -q SUBAGENT_AUTOSTARTED "$rc" 2>/dev/null; then\n\
        echo "$AUTOSTART_LINE" >> "$rc"\n\
    fi\n\
done\n\
\n\
# Mark volume as active (used by cleanup script to calculate TTL from last use, not creation)\n\
touch /home/assistant/.last_active\n\
\n\
# Skill usage tracking: inotify watcher logs SKILL.md reads to outputs bind mount\n\
if command -v inotifywait >/dev/null 2>&1 && [ -d /mnt/skills ]; then\n\
  (\n\
    inotifywait -q -e access -m -r /mnt/skills/ --format "%%w%%f" 2>/dev/null |\n\
    while IFS= read -r filepath; do\n\
      if [[ "$filepath" == */SKILL.md ]]; then\n\
        skill=$(basename "$(dirname "$filepath")")\n\
        ts=$(date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ)\n\
        if [ -w /mnt/user-data/outputs ]; then\n\
          echo "{\"ts\":\"$ts\",\"skill\":\"$skill\",\"email\":\"${GIT_AUTHOR_EMAIL:-unknown}\",\"chat_id\":\"${CHAT_ID:-unknown}\"}" >> /mnt/user-data/outputs/.skill-usage.jsonl 2>/dev/null || true\n\
        fi\n\
      fi\n\
    done\n\
  ) &\n\
fi\n\
\n\
exec "$@"\n' > /home/assistant/.entrypoint.sh && \
    chmod +x /home/assistant/.entrypoint.sh && \
    chown assistant:assistant /home/assistant/.entrypoint.sh

# Configure git defaults (user info)
RUN printf '[user]\n\
    name = AI Assistant\n\
    email = ai-assistant@open-computer-use.dev\n' > /home/assistant/.gitconfig && \
    chown assistant:assistant /home/assistant/.gitconfig

# Clean up caches to minimize /home/assistant size (will be copied to volumes)
# Keep only essential config files, remove npm/pip caches
# Create empty package.json so npm install from /home/assistant doesn't traverse
# to /home/node_modules (parent dir) and corrupt system packages
RUN rm -rf /home/assistant/.npm /home/assistant/.cache && \
    npm cache clean --force && \
    printf '{"private":true}\n' > /home/assistant/package.json && \
    chown assistant:assistant /home/assistant/package.json && \
    sudo -u assistant npm config delete prefix

# Set working directory
WORKDIR /home/assistant

# extract-text CLI: unified plain-text extractor for docx/odt/epub/xlsx/pptx/rtf/html/htm/ipynb
# Anthropic-built Rust binary (x86_64 ELF, ~2MB). Used by the file-reading and pdf-reading skills.
# See vendor/extract-text/README.md for licensing and the followup to fetch it at build time.
COPY --chown=root:root vendor/extract-text/extract-text /usr/local/bin/extract-text
RUN chmod +x /usr/local/bin/extract-text

# list-subagent-models — canonical Python tool for the sub-agent skill (REQ-MCP-04)
COPY --chown=root:root computer-use-server/bin/list-subagent-models /usr/local/bin/list-subagent-models
RUN chmod +x /usr/local/bin/list-subagent-models

# Copy skills into image (available in all containers)
# Placed late in Dockerfile so skill file changes don't invalidate heavy layers above
COPY --chown=root:root ./skills /mnt/skills/

# ── External skills for Claude Code only: GSD + Superpowers ──────────────────
# Cloned at build-time from GitHub; laid out under /opt/skills-external/, then
# symlinked into /home/assistant/.claude/ by entrypoint. NOT exposed to main AI
# (main AI reads /mnt/skills/, these live only in the Claude Code home volume).
#
# Refs are pinned to upstream tags. Tags are mutable (upstream can re-tag);
# `--branch` accepts only tag/branch names — not raw SHAs. For strict
# reproducibility, switch the clone strategy to `clone --no-checkout`
# followed by `git fetch <sha> && git checkout <sha>`. Tracked as a
# followup in CHANGELOG.md "Known followups". To bump the pinned tags,
# change the ARGs below and rebuild.
ARG GSD_REF=v1.9.9
ARG SUPERPOWERS_REF=v5.0.7

# GSD (Get Shit Done) — commands, agents, hooks, engine
# NOTE: upstream repo has no skills/ dir — gsd-* skills are generated by the
# official npx installer. Users invoke via /gsd:<cmd> slash-commands instead.
RUN git clone --depth 1 --branch "${GSD_REF}" https://github.com/gsd-build/get-shit-done.git /tmp/gsd && \
    mkdir -p /opt/skills-external/gsd/get-shit-done \
             /opt/skills-external/gsd/agents \
             /opt/skills-external/gsd/commands \
             /opt/skills-external/gsd/hooks && \
    cp -r /tmp/gsd/get-shit-done/. /opt/skills-external/gsd/get-shit-done/ && \
    cp /tmp/gsd/agents/gsd-*.md /opt/skills-external/gsd/agents/ && \
    cp -r /tmp/gsd/commands/. /opt/skills-external/gsd/commands/ && \
    cp -r /tmp/gsd/hooks/. /opt/skills-external/gsd/hooks/ && \
    git clone --depth 1 --branch "${SUPERPOWERS_REF}" https://github.com/obra/superpowers.git /tmp/superpowers && \
    mkdir -p /opt/skills-external/superpowers && \
    cp -r /tmp/superpowers/skills /opt/skills-external/superpowers/ && \
    cp -r /tmp/superpowers/commands /opt/skills-external/superpowers/ && \
    cp -r /tmp/superpowers/agents /opt/skills-external/superpowers/ && \
    if [ -d /tmp/superpowers/hooks ]; then cp -r /tmp/superpowers/hooks /opt/skills-external/superpowers/; fi && \
    find /opt/skills-external -name .git -type d -exec rm -rf {} + && \
    rm -rf /tmp/gsd /tmp/superpowers && \
    ln -sf /opt/skills-external/gsd/get-shit-done/bin/gsd-tools.cjs /usr/local/bin/gsd && \
    find /opt/skills-external/gsd/hooks -type f \( -name '*.sh' -o -name '*.js' \) -exec chmod +x {} +

# Verify installations
RUN python3 -c "import docx, pptx, openpyxl; print('Python packages OK')" && \
    node -e "console.log('Node.js OK')" && \
    npm list -g --depth=0 && \
    sudo -u assistant bash -c "export PATH=/usr/local/lib/node_modules_global/bin:\$PATH && claude --version" && echo "Claude Code OK" && \
    rm -rf /home/assistant/.bun

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "print('healthy')" || exit 1

# Entrypoint: creates .claude.json, CLAUDE.md, settings.json, skills symlinks, git config
ENTRYPOINT ["/home/assistant/.entrypoint.sh"]

# Default command (keepalive for container orchestration)
CMD ["bash", "-c", "trap 'exit 0' SIGTERM SIGINT; tail -f /dev/null & wait $!"]
