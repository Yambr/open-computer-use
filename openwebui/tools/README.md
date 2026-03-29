# Computer Use Tools - Detailed Documentation

Complete guide for installing and using Computer Use Tools for OpenWebUI.

## Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [File Structure](#file-structure)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

## Overview

Computer Use Tools provides AI with full access to a Linux environment through 5 tools:

- **bash** - execute commands in bash
- **str_replace** - edit existing files
- **file_create** - create new files
- **view** - read files or list directories
- **sub_agent** - delegate complex tasks to autonomous Claude agent

Each chat gets its own isolated Docker container that persists between messages.

### Key Features

✅ **Persistence** - container is created once per chat and reused
✅ **Isolation** - each chat runs in a separate container
✅ **Automation** - containers are automatically created/started/reused
✅ **Simplicity** - no SQLite, no background threads, just Docker API
✅ **Security** - non-root user, timeout, injection protection
✅ **Rich Environment** - Python, Node.js, Java, LibreOffice, FFmpeg, Playwright and more

## Architecture

### How It Works

```
┌──────────────────────────────────────┐
│         OpenWebUI Container          │
│                                      │
│  ┌────────────────────────────────┐ │
│  │   computer_use_tools.py        │ │
│  │   (Computer Use Tools)         │ │
│  └────────────┬───────────────────┘ │
│               │                      │
│               │ Docker SDK           │
│               ▼                      │
│      /var/run/docker.sock ────────────────┐
└──────────────────────────────────────┘    │
                                             │
        ┌────────────────────────────────────┘
        │
        │  Creates/manages sibling containers:
        │
        ├─► owui-chat-{chat_id_1}  (computer-use:latest)
        │   └─ Volume: chat-{chat_id_1}-workspace → /home/assistant
        │
        ├─► owui-chat-{chat_id_2}  (computer-use:latest)
        │   └─ Volume: chat-{chat_id_2}-workspace → /home/assistant
        │
        └─► ...
```

### Container Management Logic

For each tool call:
1. Get `chat_id` from `__metadata__`
2. Sanitize `chat_id` for Docker naming: `re.sub(r'[^a-zA-Z0-9_.-]', '-', chat_id)`
3. Check if container `owui-chat-{sanitized_id}` exists:
   - **Exists and running** → use it
   - **Exists but stopped** → start and use it
   - **Doesn't exist** → create, start, and use it

### Container Structure

Each container is created with this configuration:
- **Image:** `computer-use:latest` (from your Dockerfile)
- **User:** `assistant:assistant` (non-root with sudo)
- **Working dir:** `/home/assistant`
- **Volume:** `chat-{chat_id}-workspace` → `/home/assistant` (persistent workspace)
- **Resources:** Configurable CPU and RAM limits
- **Network:** Optionally disabled
- **Command:** `tail -f /dev/null` (keeps container running)

## Requirements

### 1. Docker

Docker must be installed and running on the host machine.

```bash
docker --version
# Docker version 24.0.0 or higher
```

### 2. Docker Socket in OpenWebUI

OpenWebUI container must have access to the Docker socket.

**Option A: Docker Compose (recommended)**

```yaml
services:
  openwebui:
    image: ghcr.io/open-webui/open-webui:main
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - openwebui:/app/backend/data
    # ... rest of configuration
```

**Option B: Docker Run**

```bash
docker run -d \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v openwebui:/app/backend/data \
  -p 3000:8080 \
  ghcr.io/open-webui/open-webui:main
```

### 3. Docker Image for Computer Use

The `computer-use:latest` image must be built from your Dockerfile.

```bash
cd openwebui-computer-use
docker-compose build
```

This image contains:
- Ubuntu 24.04
- Python 3, Node.js 22, Java 21
- LibreOffice, FFmpeg, Playwright
- Tesseract OCR, ImageMagick, Ghostscript
- User `assistant` with sudo
- Directories `/mnt/user-data/uploads` (read-only), `/mnt/user-data/outputs` (read-write), `/mnt/skills`
- Skills copied to `/mnt/skills`

## Installation

### Step 1: Prepare the Image

```bash
# Navigate to directory with Dockerfile
cd openwebui-computer-use

# Build the image
docker-compose build

# Verify the image was created
docker images | grep computer-use
# Should show: computer-use  latest  ...
```

### Step 2: Configure OpenWebUI

Make sure OpenWebUI has access to the Docker socket (see [Requirements](#requirements)).

### Step 3: Install Tool in OpenWebUI

1. Open OpenWebUI in browser
2. Go to **Settings** → **Tools**
3. Click **+ Create Tool**
4. Copy contents of `computer_use_tools.py` into the editor
5. Click **Save**

### Step 4: Activate the Tool

1. Create a new chat
2. Open chat settings (⚙️)
3. In the **Tools** section, enable **Computer Use Tools**
4. Start using it!

## Configuration

### Valves (configuration parameters)

The Tool provides the following configurable parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DOCKER_SOCKET` | `unix://var/run/docker.sock` | Path to Docker socket |
| `DOCKER_IMAGE` | `computer-use:latest` | Docker image for containers |
| `CONTAINER_MEM_LIMIT` | `2g` | RAM limit per container (e.g., `1g`, `512m`) |
| `CONTAINER_CPU_LIMIT` | `1.0` | CPU limit per container (1.0 = 1 core) |
| `COMMAND_TIMEOUT` | `120` | Command execution timeout (seconds) |
| `ENABLE_NETWORK` | `True` | Allow network access in containers |

### Modifying Valves

1. In OpenWebUI go to **Settings** → **Tools**
2. Find **Computer Use Tools**
3. Click the settings icon (⚙️)
4. Modify desired parameters
5. Save

## Usage

### Core Tools

#### 1. bash

Executes commands in bash.

**Examples:**
```python
# Show current directory
bash("pwd")
# Output: /home/assistant

# Install Python package
bash("pip install requests")

# Run Python script
bash("python script.py")

# Compile C program
bash("gcc hello.c -o hello && ./hello")

# Work with git
bash("git clone https://github.com/user/repo.git && cd repo && ls")
```

**Working directory:** `/home/assistant`
**User:** `assistant` (has sudo for root access)
**Timeout:** Configurable via `COMMAND_TIMEOUT`

#### 2. str_replace

Edits an existing file by replacing text.

**Syntax:**
```python
str_replace(
    path="/home/assistant/file.py",
    old_str="old text",
    new_str="new text"
)
```

**Examples:**
```python
# Fix a function
str_replace(
    path="script.py",
    old_str="def hello():\n    print('hi')",
    new_str="def hello():\n    print('Hello, World!')"
)

# Change a variable
str_replace(
    path="config.json",
    old_str='"debug": false',
    new_str='"debug": true'
)
```

**Notes:**
- Replaces only the first occurrence of `old_str`
- `old_str` must match exactly (including spaces and newlines)
- Returns an error if `old_str` is not found

#### 3. file_create

Creates a new file with specified content.

**Syntax:**
```python
file_create(
    path="/home/assistant/file.py",
    content="file contents"
)
```

**Examples:**
```python
# Create Python script
file_create(
    path="hello.py",
    content="""
def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
"""
)

# Create config file
file_create(
    path="config.json",
    content='{"api_key": "xxx", "debug": true}'
)

# Create file in subfolder (creates folders automatically)
file_create(
    path="projects/myapp/main.py",
    content="# My Application"
)
```

**Notes:**
- Automatically creates parent directories
- Overwrites file if it already exists

#### 4. view

Reads a file or shows directory contents.

**Syntax:**
```python
view(path="/home/assistant/file.py")
```

**Examples:**
```python
# Read file
view("script.py")
# Output: [file contents]

# Show directory
view("/home/assistant")
# Output: [ls -lah listing]

# View system files (with sudo if needed)
view("/etc/hosts")
```

**Notes:**
- If path is a file → returns contents
- If path is a directory → returns `ls -lah` listing
- If path doesn't exist → error

#### 5. sub_agent

Delegates complex, multi-step tasks to an autonomous Claude agent.

**When to use:**
- Creating presentations (10+ slides)
- Multi-file refactoring
- Iterative test-fix cycles
- Code review with fixes
- Complex Git operations

**When NOT to use:**
- Simple file reads/writes
- Single bash command
- Quick edits to one file

**Syntax:**
```python
sub_agent(
    task="""
## ROLE
You are a [role] specializing in [domain]

## DIRECTIVE
Clear, specific instruction what to do.

## CONSTRAINTS
- Do NOT [action]
- Only [scope], don't [out-of-scope]

## PROCESS
1. First, [explore/scan]
2. Then, [identify/evaluate]
3. Finally, [implement/report]

## OUTPUT
- Save to [path]
- Verify by running [command]
""",
    description="Why you're delegating",
    model="sonnet",  # or "opus"
    max_turns=50
)
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `task` | required | Structured task with ROLE/DIRECTIVE/CONSTRAINTS/PROCESS/OUTPUT |
| `description` | required | Why you're delegating |
| `mode` | "act" | "act" (execute) or "plan" (plan only) |
| `model` | "sonnet" | "sonnet" (fast) or "opus" (complex) |
| `max_turns` | 50 | Max iterations |
| `working_directory` | /home/assistant | Agent's working directory |
| `resume_session_id` | "" | Resume previous session |

**Full documentation:** See `/mnt/skills/public/sub-agent/SKILL.md`

### Workflow Examples

#### Example 1: Create and Run Python Script

**User:** Create a Python script that fetches data from an API and saves it to a file.

**AI will execute:**
```python
# 1. Create script
file_create(
    path="fetch_data.py",
    content="""
import requests
import json

def fetch_data():
    response = requests.get('https://api.example.com/data')
    data = response.json()

    with open('data.json', 'w') as f:
        json.dump(data, f, indent=2)

    print('Data saved to data.json')

if __name__ == '__main__':
    fetch_data()
"""
)

# 2. Install dependencies
bash("pip install requests")

# 3. Run
bash("python fetch_data.py")

# 4. Check result
view("data.json")
```

#### Example 2: Work with Documents

**User:** Convert this PDF to text and count the words.

**AI will execute:**
```python
# 1. Check that PDF is uploaded
view("/mnt/user-data/uploads")

# 2. Extract text
bash("pdftotext /mnt/user-data/uploads/document.pdf output.txt")

# 3. Count words
bash("wc -w output.txt")

# 4. Show first lines
bash("head -n 20 output.txt")

# 5. Save result to outputs
bash("cp output.txt /mnt/user-data/outputs/extracted.txt")
```

#### Example 3: Develop a Web Server

**User:** Create a simple Flask API with two endpoints.

**AI will execute:**
```python
# 1. Create app.py
file_create(
    path="app.py",
    content="""
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/api/hello')
def hello():
    return jsonify({"message": "Hello, World!"})

@app.route('/api/status')
def status():
    return jsonify({"status": "running"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
"""
)

# 2. Install Flask
bash("pip install flask")

# 3. Run server in background
bash("python app.py &")

# 4. Wait and test
bash("sleep 2 && curl http://localhost:8000/api/hello")
```

#### Example 4: Create Presentation with SubAgent

**User:** Create a 15-slide presentation on AI trends for executives.

**AI will execute:**
```python
# Delegate to sub_agent for complex multi-step task
sub_agent(
    task="""
## ROLE
You are a business presentation specialist.

## DIRECTIVE
Create a 15-slide presentation on AI adoption trends for executives.

## CONSTRAINTS
- Do NOT use technical jargon
- Do NOT include more than 5 bullets per slide
- Cite all sources

## PROCESS
1. Research current AI adoption statistics
2. Create slide outline with key messages
3. Build presentation using python-pptx
4. Add speaker notes for each slide
5. Create executive summary

## OUTPUT
- Save to /mnt/user-data/outputs/ai_trends.pptx
- Create /mnt/user-data/outputs/executive_summary.md
""",
    description="AI presentation for board meeting",
    model="sonnet",
    max_turns=50
)
```

## File Structure

### Directories in Container

```
/home/assistant/                 # Working directory (persistent via volume)
├── [your files and projects]   # Saved between sessions

/mnt/user-data/
├── uploads/                     # Uploaded files (READ-ONLY for assistant)
│   └── [files from user]       # Can read via view() or bash("cat ...")
└── outputs/                     # Output files (READ-WRITE for assistant)
    └── [work results]          # Bash can write, user can download

/mnt/skills/                     # Skills from your repository (READ-ONLY)
└── [skill files]               # Available for reading and execution

/mnt/transcripts/                # Transcripts (READ-WRITE for assistant)
└── [session records]
```

### Access Permissions

| Path | Owner | Permissions | Description |
|------|-------|-------------|-------------|
| `/home/assistant` | `assistant:assistant` | `rwx` | Working directory, full access |
| `/mnt/user-data/uploads` | `root:root` | `r-x` | User uploads, read-only |
| `/mnt/user-data/outputs` | `assistant:assistant` | `rwx` | Work results, write allowed |
| `/mnt/skills` | `root:root` | `r-x` | Skills, read-only |
| `/mnt/transcripts` | `assistant:assistant` | `rwx` | Transcripts, write allowed |

### Data Persistence

- **Persistent:** All files in `/home/assistant` are saved via Docker volume
- **Ephemeral:** System changes (apt packages without sudo, global configs) are lost on container recreation
- **Recommendation:** Use pip/npm for user space installation (`pip install --user` or npm without `-g`)

## Security

### Implemented Security Measures

#### 1. Non-root User

All commands run as user `assistant`, who:
- Has no root privileges by default
- Has sudo access (NOPASSWD) for cases where root is needed
- Is limited to their home directory

#### 2. Injection Protection

**Shell injection prevention:**
- All commands are wrapped through `shlex.quote()`
- Parameters are passed via JSON stdin instead of direct string concatenation

**Example of safe implementation:**
```python
# BAD (vulnerable):
command = f"cat {path}"  # Path could contain `; rm -rf /`

# GOOD (safe):
quoted_path = shlex.quote(path)
command = f"cat {quoted_path}"
```

#### 3. Timeout Protection

All commands are wrapped in `timeout`:
```bash
timeout 120 bash -c 'your command here'
```

This prevents:
- Infinite loops
- Hanging processes
- DoS attacks

#### 4. Resource Limits

Each container has limits:
- **CPU:** Default 1.0 (1 core)
- **RAM:** Default 2GB
- **Network:** Optionally disabled

#### 5. Docker Isolation

Docker provides kernel-level isolation:
- Separate filesystem namespace
- Separate network namespace
- Separate process namespace
- Security opt: `no-new-privileges:true`

#### 6. Read-only Uploads

Uploaded files are read-only:
- User cannot accidentally modify original data
- AI cannot overwrite uploaded files
- Use `cp` to create a working copy: `bash("cp /mnt/user-data/uploads/file.txt .")`

### Additional Recommendations

1. **Don't disable network unnecessarily** - many tools require internet (pip, npm, git)
2. **Regularly clean old containers:**
   ```bash
   docker container prune -f --filter "label=managed-by=openwebui"
   ```
3. **Monitor resource usage:**
   ```bash
   docker stats $(docker ps --filter "label=managed-by=openwebui" -q)
   ```
4. **Backup important volumes:**
   ```bash
   docker volume ls --filter "name=chat-" | awk '{print $2}' | xargs -I {} docker run --rm -v {}:/data -v $(pwd):/backup alpine tar czf /backup/{}.tar.gz -C /data .
   ```

## Troubleshooting

### Problem: "Failed to connect to Docker"

**Symptoms:** Tool cannot connect to Docker socket.

**Solution:**
1. Check that Docker socket is mounted in OpenWebUI:
   ```bash
   docker exec -it openwebui ls -l /var/run/docker.sock
   # Should show: srwxrwxrwx ... /var/run/docker.sock
   ```

2. Check access permissions:
   ```bash
   docker exec -it openwebui groups
   # Should have 'docker' or 'root' group
   ```

3. If running via Docker Compose, check volumes in compose file:
   ```yaml
   volumes:
     - /var/run/docker.sock:/var/run/docker.sock
   ```

### Problem: "Image not found: computer-use:latest"

**Symptoms:** Tool tries to create container but can't find image.

**Solution:**
1. Check that image is built:
   ```bash
   docker images | grep computer-use
   ```

2. If not, build it:
   ```bash
   cd openwebui-computer-use
   docker-compose build
   ```

3. Check that tag is correct (should be `computer-use:latest`)

### Problem: Commands return timeout

**Symptoms:** Commands always finish with "[Command timed out after N seconds]"

**Solution:**
1. Increase `COMMAND_TIMEOUT` in Valves
2. Check that command isn't actually hanging:
   ```bash
   docker exec owui-chat-{chat_id} ps aux
   ```
3. Kill hanging processes if needed

### Problem: Containers accumulate

**Symptoms:** Many old containers, disk filling up.

**Solution:**
1. View all containers:
   ```bash
   docker ps -a --filter "label=managed-by=openwebui"
   ```

2. Stop old ones:
   ```bash
   docker stop $(docker ps -a --filter "label=managed-by=openwebui" -q)
   ```

3. Remove unused:
   ```bash
   docker container prune -f --filter "label=managed-by=openwebui"
   ```

4. Clean volumes (WARNING: deletes all data):
   ```bash
   docker volume rm $(docker volume ls -q --filter "name=chat-")
   ```

### Problem: Permission denied in /mnt/user-data/uploads

**Symptoms:** AI cannot write to uploads.

**Solution:**
This is expected behavior! `/mnt/user-data/uploads` is READ-ONLY for security.

To work with files:
```python
# Copy to working directory
bash("cp /mnt/user-data/uploads/file.txt .")

# Work with the copy
bash("sed -i 's/old/new/g' file.txt")

# Save result to outputs
bash("cp file.txt /mnt/user-data/outputs/result.txt")
```

### Problem: Skills not found

**Symptoms:** `/mnt/skills` is empty or doesn't exist.

**Solution:**
1. Check that skills are copied to image during build:
   ```bash
   docker run --rm computer-use:latest ls -la /mnt/skills
   ```

2. If empty, check `.dockerignore` - make sure `skills/` is NOT ignored

3. Rebuild image:
   ```bash
   docker-compose build --no-cache
   ```

### Problem: Python packages don't persist

**Symptoms:** After `pip install` package disappears on next run.

**Solution:**
Install in user space:
```python
# Instead of:
bash("pip install requests")

# Use:
bash("pip install --user requests")

# Or create venv in /home/assistant:
bash("python -m venv venv && source venv/bin/activate && pip install requests")
```

This ensures packages install to `/home/assistant/.local` (persistent volume).

### Problem: Container doesn't start

**Symptoms:** Error creating/starting container.

**Solution:**
1. Check logs:
   ```bash
   docker logs owui-chat-{chat_id}
   ```

2. Check status:
   ```bash
   docker inspect owui-chat-{chat_id} | jq '.[0].State'
   ```

3. Try starting manually:
   ```bash
   docker start owui-chat-{chat_id}
   ```

4. If that doesn't help, delete and recreate:
   ```bash
   docker rm -f owui-chat-{chat_id}
   docker volume rm chat-{chat_id}-workspace
   # Tool will create new one on next call
   ```

---

**Version:** 2.0.0
**Date:** 2025-01-15
**Author:** OpenWebUI Implementation
