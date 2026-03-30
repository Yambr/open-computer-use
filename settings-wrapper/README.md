# Settings Wrapper

Optional skill registry for Open Computer Use. Controls which skills are available to each user.

**Without this service**, all built-in skills are available to everyone (default behavior).
**With this service**, you can control per-user skill access and add custom user-uploaded skills.

## Quick Start

```bash
# Run standalone
cd settings-wrapper
pip install -r requirements.txt
uvicorn app:app --port 8082

# Or with Docker
docker compose up settings-wrapper
```

## API Contract

The Computer Use Server's `skill_manager.py` calls two endpoints:

### GET /api/internal/user-config/{email}

Returns enabled skills for a user.

**Headers:** `X-Internal-Api-Key: <key>`

**Response:**
```json
{
  "email": "user@example.com",
  "enabled_skills": [
    {
      "name": "docx",
      "description": "Word document creation and editing",
      "category": "public",
      "skill_path": "public/docx"
    },
    {
      "name": "my-custom-skill",
      "description": "Does something useful",
      "category": "user",
      "zip_sha256": "e3b0c44298fc1c149afbf4c8996fb..."
    }
  ]
}
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique skill identifier |
| `description` | No | Short description for system prompt |
| `category` | No | `"public"` (built-in), `"example"`, or `"user"` (uploaded). Default: `"user"` |
| `skill_path` | No | Path inside image for native skills (e.g. `"public/docx"`) |
| `zip_sha256` | No | SHA256 of skill ZIP — triggers re-download when changed |

### GET /api/internal/skills/{name}/download

Downloads a user-uploaded skill as ZIP.

**Headers:** `X-Internal-Api-Key: <key>`

**Response:**
- `application/zip` — skill ZIP archive
- `application/json` — native skill (already in Docker image, no download needed)

## Skill ZIP Format

A skill ZIP must contain at minimum:

```
my-skill/
├── SKILL.md          # Required — instructions for the AI
└── scripts/          # Optional — helper scripts
    └── generate.py
```

`SKILL.md` is what the AI reads to understand how to use the skill. See `skills/public/` for examples.

Place ZIP files in the `skills/` directory:
```
settings-wrapper/
├── skills/
│   └── my-custom-skill.zip
├── skills.json
└── app.py
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | _(empty)_ | Auth key (must match `MCP_TOKENS_API_KEY` in computer-use-server) |
| `SKILLS_DIR` | `/app/skills` | Directory with skill ZIP files |
| `CONFIG_PATH` | `/app/skills.json` | Path to skills configuration |

## Connecting to Computer Use Server

Add to your `.env`:
```bash
MCP_TOKENS_URL=http://settings-wrapper:8082
MCP_TOKENS_API_KEY=your-secret-key
```

Or uncomment the service in `docker-compose.yml`.

## Customization

This is a **minimal reference implementation**. Replace it with:
- A database-backed service with admin UI
- S3/GCS storage for skill ZIPs
- Corporate skill registry with RBAC
- Integration with your existing settings system

The only contract is the two API endpoints above.
