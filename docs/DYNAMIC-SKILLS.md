# Dynamic Per-User Skill Injection

Dynamic system that fetches user-enabled skills from `mcp-settings-wrapper` and injects them into Docker containers at runtime.

## Architecture

There are **two paths** for creating Computer Use containers. Both now support dynamic skill injection:

```
                     mcp-settings-wrapper
                    ()
                     /api/internal/user-config/{email}
                     /api/internal/skills/{name}/download
                              |
              +---------------+---------------+
              |                               |
     Path 1: MCP                    Path 2: Direct Connector
     (computer-use-orchestrator)                  (computer_use_tools.py)
              |                               |
  skill_manager.py                  GET /skill-mounts
  (direct import)                   GET /skill-list
              |                     (calls computer-use-orchestrator API)
              |                               |
              +-------------------------------+
              |
        Docker Container
        owui-chat-{chat_id}
              |
  /mnt/skills/public/*    (baked in image)
  /mnt/skills/examples/*  (baked in image)
  /mnt/skills/user/*      (bind-mounted from host cache)
```

### Path 1: MCP (computer-use-orchestrator + mcp_tools.py)

Used by: LiteLLM MCP proxy, direct `/mcp` API calls, n8n integrations.

- `mcp_tools.py` imports `skill_manager` directly (same process)
- On container creation: `skill_manager.get_skill_mounts()` returns volume mounts
- On system prompt build: `skill_manager.build_available_skills_xml()` generates dynamic `<available_skills>` XML
- On sub_agent: `skill_manager.build_sub_agent_skills_text()` generates skill list

### Path 2: Direct Connector (computer_use_tools.py in OpenWebUI)

Used by: OpenWebUI chat UI (the primary user-facing path).

- Runs in OpenWebUI K8s pod, not on docker-ai host
- Cannot import `skill_manager.py` directly
- Calls computer-use-orchestrator HTTP API:
  - `GET /skill-mounts?user_email={email}` - returns Docker volume mounts dict
  - `GET /skill-list?user_email={email}&format=sub_agent` - returns skills text for sub_agent prompt
- System prompt: fetched from `GET /system-prompt?user_email={email}`
- Fallback on API errors: empty mounts `{}`, hardcoded 7-skill list

## Components

### skill_manager.py (computer-use-orchestrator)

Core module. Handles:

| Function | Purpose |
|----------|---------|
| `get_user_skills(email)` | Fetch enabled skills (async, 3-level fallback) |
| `get_user_skills_sync(email)` | Sync version (reads cache only) |
| `ensure_skill_cached(skill)` | Download + extract user-uploaded ZIP |
| `build_available_skills_xml(skills)` | `<available_skills>` XML for system prompt |
| `build_sub_agent_skills_text(skills)` | `- name: location - description` for sub_agent |
| `get_skill_mounts(skills)` | Docker volume mounts dict for user skills |

### File-server API endpoints (app.py)

| Endpoint | Purpose |
|----------|---------|
| `GET /system-prompt?user_email=X` | Dynamic system prompt with user's skills |
| `GET /skill-mounts?user_email=X` | Docker volume mounts for user skills |
| `GET /skill-list?user_email=X&format=sub_agent` | Skills text for sub_agent prompt |

### mcp-settings-wrapper API (external)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/internal/user-config/{email}` | User's enabled skills list |
| `GET /api/internal/skills/{name}/download` | Download skill ZIP |

Authenticated via `X-Internal-Api-Key` header.

## Skill Categories

| Category | Storage | Mount Point | Source |
|----------|---------|-------------|--------|
| `public` | Baked in Docker image | `/mnt/skills/public/{name}/` | Repository `skills/public/` |
| `example` | Baked in Docker image | `/mnt/skills/examples/{name}/` | Repository `skills/examples/` |
| `user` | Host cache `/tmp/skills-cache/{name}/` | `/mnt/skills/user/{name}/` | ZIP from mcp-settings-wrapper |

## Data Flow: User-Uploaded Skill

```
1. User uploads ZIP via mcp-settings-wrapper UI
2. User enables skill in settings

3. On chat start, computer-use-orchestrator receives user_email
4. skill_manager.get_user_skills(email) calls mcp-settings-wrapper API
5. Response: [{name, description, category:"user", zip_sha256}]
6. skill_manager.ensure_skill_cached(skill):
   a. Check /data/skills-cache/{name}/ + manifest SHA256
   b. If match → skip download
   c. If miss → download ZIP → extract to temp dir → atomic rename
7. get_skill_mounts() returns:
   {"/tmp/skills-cache/{name}": {"bind": "/mnt/skills/user/{name}", "mode": "ro"}}
8. Docker creates container with bind mount
9. Inside container: /mnt/skills/user/{name}/SKILL.md is accessible
```

Note: `/data/skills-cache/` is the container-internal path; `/tmp/skills-cache/` is the host path (Docker daemon needs host paths for mounts).

## Caching & Fallback

### 3-level fallback for skill lists

```
get_user_skills(email):
  1. In-memory cache (TTL: 60s)
  2. API call to mcp-settings-wrapper
  3. Disk cache (~/.skills-cache/_user_configs/{hash}.json)
  4. Hardcoded 10 public skills (last resort)
```

### ZIP cache

- Location: `/data/skills-cache/{skill-name}/`
- Manifest: `/data/skills-cache/.manifest.json` (name → sha256 + timestamp)
- Atomic extraction: unzip to temp dir → `os.rename` to final path
- Stale cache reuse: if API/download fails but old cache exists, use it

## Configuration

Environment variables on computer-use-orchestrator:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TOKENS_URL` | `` | mcp-settings-wrapper URL |
| `MCP_TOKENS_API_KEY` | (required) | Internal API key |
| `SKILLS_CACHE_DIR` | `/data/skills-cache` | Container-internal cache path |
| `SKILLS_CACHE_HOST_PATH` | `/tmp/skills-cache` | Host path for Docker mounts |

Docker-compose volumes for computer-use-orchestrator:
```yaml
volumes:
  - /tmp/skills-cache:/data/skills-cache:rw
```

## Test Cases

### Scenario 1: Basic verification (no changes)

**Goal**: Confirm existing skills work without modifications.

1. Login to `https://example.com`
2. Create a new chat with a Computer Use model
3. Send: "List files in /mnt/skills/public/"
4. **Expected**: Container created, `ls` output shows public skill directories (docx, pdf, pptx, xlsx, etc.)

### Scenario 2: Enable an existing example skill

**Goal**: Confirm that enabling a skill in mcp-settings-wrapper makes it visible in the AI prompt.

1. Enable an example skill (e.g. `algorithmic-art`) via mcp-settings-wrapper settings
2. Open a **new** chat
3. Send: "What skills do you have available?"
4. **Expected**: AI's response mentions `algorithmic-art` among available skills
5. Send: "Use the algorithmic-art skill to create something"
6. **Expected**: AI reads `/mnt/skills/examples/algorithmic-art/SKILL.md` and follows it

### Scenario 3: Create, test, update, and delete a custom skill

**Goal**: Full lifecycle test for user-uploaded skills.

1. Create a test skill ZIP containing `SKILL.md` with unique content (e.g. "test-skill-v1")
2. Upload via mcp-settings-wrapper API
3. Enable for user
4. Open new chat → verify AI sees the skill and can read its SKILL.md
5. Update the skill ZIP with new content ("test-skill-v2")
6. Open new chat → verify AI sees updated content
7. Delete the test skill

### API verification (no browser needed)

```bash
# Check skill mounts for a user
curl "http://localhost:8081/skill-mounts?user_email=user@example.com"

# Check skill list
curl "http://localhost:8081/skill-list?user_email=user@example.com&format=sub_agent"

# Check dynamic system prompt
curl "http://localhost:8081/system-prompt?user_email=user@example.com" | head -50
```
