# Installation Guide

Comprehensive installation guide for AI Computer Use Docker environment.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation Steps](#installation-steps)
3. [Manual Installation](#manual-installation)
4. [Verification](#verification)
5. [Configuration](#configuration)
6. [Troubleshooting](#troubleshooting)

## Prerequisites

### System Requirements

**Minimum:**
- 8GB RAM
- 2 CPU cores
- 20GB free disk space
- Internet connection (for initial build)

**Recommended:**
- 16GB RAM
- 4+ CPU cores
- 50GB free disk space
- Fast internet connection

### Software Requirements

#### 1. Docker Engine

**macOS:**
```bash
# Install Docker Desktop from official website
# https://docs.docker.com/desktop/install/mac-install/

# Or via Homebrew
brew install --cask docker
```

**Linux (Ubuntu/Debian):**
```bash
# Update package index
sudo apt-get update

# Install dependencies
sudo apt-get install ca-certificates curl gnupg

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Set up repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify installation
docker --version
docker compose version
```

**Windows:**
- Install Docker Desktop for Windows with WSL2 backend
- https://docs.docker.com/desktop/install/windows-install/

#### 2. Git (Optional)

```bash
# macOS
brew install git

# Linux
sudo apt-get install git

# Windows
# Download from https://git-scm.com/download/win
```

## Installation Steps

### Method 1: Automated Setup (Recommended)

1. **Download/Clone Repository:**
```bash
git clone <repository-url>
cd files-ai-computer-use
```

2. **Run Setup Script:**
```bash
chmod +x setup.sh
./setup.sh
```

The script will:
- Check Docker installation
- Create directory structure
- Verify configuration files
- Build Docker image (~10-15 minutes)
- Verify installation

3. **Start Container:**
```bash
docker-compose up -d
```

4. **Verify:**
```bash
docker-compose ps
docker-compose exec ai-computer-use python3 --version
```

### Method 2: Manual Installation

#### Step 1: Create Directory Structure

```bash
mkdir -p data/uploads data/outputs docs scripts/mcp-server
touch data/uploads/.gitkeep data/outputs/.gitkeep
```

#### Step 2: Review Configuration Files

Ensure these files exist:
- `Dockerfile`
- `docker-compose.yml`
- `requirements.txt`
- `package.json`
- `apt-packages.txt`
- `.env.example`

#### Step 3: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit as needed (optional)
nano .env
```

#### Step 4: Build Image

```bash
# Build with no cache (recommended for first build)
docker-compose build --no-cache

# Or with progress output
docker-compose build --progress=plain
```

**Build Time:**
- First build: 10-20 minutes (depends on internet speed)
- Subsequent builds: 2-5 minutes (with caching)

**Image Size:**
- Final image: ~15-20 GB (includes Playwright browsers)

#### Step 5: Start Container

```bash
# Start in detached mode
docker-compose up -d

# Or with logs
docker-compose up
```

#### Step 6: Verify Installation

```bash
# Check container status
docker-compose ps

# Access container
docker-compose exec ai-computer-use /bin/bash

# Inside container, verify components
python3 --version     # Should show 3.12.3
node --version        # Should show 22.20.x
npm --version         # Should show 10.9.x

# Test Python packages
python3 -c "import docx, pptx, openpyxl; print('OK')"

# Test Node packages
node -e "console.log('OK')"

# Exit container
exit
```

## Configuration

### Environment Variables

Edit `.env` file:

```bash
# Python
PYTHONUNBUFFERED=1
PIP_BREAK_SYSTEM_PACKAGES=1

# Node.js
NODE_PATH=/usr/local/lib/node_modules_global

# Java
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

# Playwright
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# Optional: Proxy settings
# HTTP_PROXY=http://proxy:port
# HTTPS_PROXY=http://proxy:port
# NO_PROXY=localhost,127.0.0.1
```

### Resource Limits

Edit `docker-compose.yml` to adjust resources:

```yaml
deploy:
  resources:
    limits:
      cpus: '4.0'      # Adjust based on your system
      memory: 8G       # Adjust based on available RAM
    reservations:
      cpus: '2.0'
      memory: 4G
```

### Port Mapping

To expose web services, uncomment in `docker-compose.yml`:

```yaml
ports:
  - "8000:8000"    # Python HTTP server
  - "3000:3000"    # Node.js app (optional)
```

## Verification

### 1. Container Health

```bash
# Check health status
docker-compose ps

# View logs
docker-compose logs

# Inspect container
docker inspect ai-computer-use
```

### 2. Component Verification

```bash
# Execute verification commands
docker-compose exec ai-computer-use bash -c "
  echo '=== Python ==='
  python3 --version
  pip list | head -10

  echo '=== Node.js ==='
  node --version
  npm list -g --depth=0 | head -10

  echo '=== System ==='
  gcc --version | head -1
  java --version | head -1

  echo '=== Python Packages ==='
  python3 -c 'import docx, pptx, openpyxl, pypdf, PIL, cv2, pandas, numpy; print(\"All core packages imported successfully\")'
"
```

### 3. Skills System

```bash
# Check skills directory
docker-compose exec ai-computer-use ls -la /mnt/skills/

# Verify skills structure
docker-compose exec ai-computer-use bash -c "
  ls -1 /mnt/skills/public/
  ls -1 /mnt/skills/examples/
"
```

### 4. File Operations

```bash
# Test uploads directory (from host)
echo "Test file" > data/uploads/test.txt

# Verify inside container
docker-compose exec ai-computer-use cat /mnt/user-data/uploads/test.txt

# Test outputs directory
docker-compose exec ai-computer-use bash -c "
  echo 'Generated output' > /mnt/user-data/outputs/output.txt
"

# Verify on host
cat data/outputs/output.txt

# Cleanup
rm data/uploads/test.txt data/outputs/output.txt
```

## Troubleshooting

### Build Failures

**Problem:** Build fails with "no space left on device"

**Solution:**
```bash
# Clean up Docker
docker system prune -a --volumes

# Check available space
df -h
```

**Problem:** Build fails downloading packages

**Solution:**
```bash
# Check internet connection
ping google.com

# Retry with verbose output
docker-compose build --no-cache --progress=plain
```

### Container Won't Start

**Problem:** Container exits immediately

**Solution:**
```bash
# Check logs
docker-compose logs

# Try running interactively
docker-compose run --rm ai-computer-use /bin/bash
```

**Problem:** Port already in use

**Solution:**
```bash
# Find process using port
lsof -i :8000

# Stop conflicting service or change port in docker-compose.yml
```

### Permission Issues

**Problem:** Cannot write to outputs directory

**Solution:**
```bash
# Fix permissions
chmod 755 data/uploads data/outputs

# Check ownership
ls -la data/
```

### Memory Issues

**Problem:** Container is killed (OOM)

**Solution:**
```bash
# Reduce memory limit in docker-compose.yml
# limits:
#   memory: 4G  # Instead of 8G

# Restart container
docker-compose down
docker-compose up -d
```

### Network Issues

**Problem:** Cannot access external resources

**Solution:**
```bash
# Check DNS
docker-compose exec ai-computer-use ping google.com

# Try different DNS (edit docker-compose.yml)
# dns:
#   - 8.8.8.8
#   - 8.8.4.4
```

## Post-Installation

### 1. Set up MCP Server (Optional)

See [scripts/mcp-server/README.md](../scripts/mcp-server/README.md)

### 2. Configure SubAgent (Optional)

SubAgent allows delegating complex, multi-step tasks to an autonomous Claude agent.
This is an **optional** feature - you can start using basic tools (bash, str_replace, file_create, view) without it.

**Requirements:**
- `ANTHROPIC_API_KEY` configured in OpenWebUI Tool Valves
- Claude Code CLI installed in container (already included)

**To use:**
1. Configure `ANTHROPIC_API_KEY` in Tool settings (Settings → Tools → Computer Use Tools → Valves)
2. See `/mnt/skills/public/sub-agent/SKILL.md` for usage examples

**Use cases:**
- Creating presentations (10+ slides)
- Multi-file refactoring
- Iterative test-fix cycles
- Code review with fixes
- Complex Git operations

**Note:** SubAgent is useful for complex tasks that require many iterations. For simple operations, use the basic tools directly.

### 3. Import Skills (If not present)

```bash
# If you have skills_archive.zip
unzip skills_archive.zip -d skills/
```

### 4. Configure Claude Desktop

Add MCP server to Claude Desktop config for seamless integration.

### 5. Test Document Processing

```bash
# Create test document
docker-compose exec ai-computer-use python3 << 'EOF'
from docx import Document
doc = Document()
doc.add_heading('Test Document', 0)
doc.add_paragraph('Created in Docker container')
doc.save('/mnt/user-data/outputs/test.docx')
print('Document created successfully')
EOF

# Verify
ls -lh data/outputs/test.docx
```

## Updating

### Update Image

```bash
# Pull latest changes (if using git)
git pull

# Rebuild image
docker-compose build --no-cache

# Restart container
docker-compose down
docker-compose up -d
```

### Update Dependencies

Edit `requirements.txt` or `package.json`, then:

```bash
docker-compose build --no-cache
docker-compose up -d
```

## Uninstallation

```bash
# Stop and remove container
docker-compose down

# Remove volumes (deletes ephemeral workspace)
docker-compose down -v

# Remove image
docker rmi ai-computer-use

# Remove all Docker data (WARNING: affects all Docker)
docker system prune -a --volumes
```

## Support

For additional help:
1. Check main [README.md](../README.md)
2. Review [DOCKER.md](DOCKER.md) for architecture details
3. Check Docker logs: `docker-compose logs`
4. Verify Docker daemon status: `docker info`

## Next Steps

- Read [DOCKER.md](DOCKER.md) for architecture details
- Explore [SKILLS.md](SKILLS.md) for skills system
- Set up [MCP server](../scripts/mcp-server/README.md) for Claude Desktop integration
