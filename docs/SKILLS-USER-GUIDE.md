# AI Assistant Skills: User Guide

Skills extend the AI assistant's capabilities. Each skill is a set of instructions and scripts that teaches the assistant to work with a specific domain: creating presentations, processing PDFs, generating visualizations, etc.

## How to Enable Skills

### Step 1. Open the Settings Page

Navigate to **/skills**

### Step 2. Log in with Email

Enter your work email like `name@example.com` and click **Log in**.

### Step 3. Select Skills

Skills are divided into three categories:

| Category | Description | Management |
|----------|-------------|------------|
| **Open Computer Use** (public) | Core skills, enabled for everyone | Cannot be disabled |
| **Examples** | Additional skills for advanced users | Checkbox on/off |
| **User-uploaded** | Uploaded by team members | Checkbox on/off |

Check the desired skills and click **Save settings**.

### Step 4. Open a New Chat

Skills are applied when creating a new chat. Go to **https://example.com**, create a new chat with the Computer Use model, and the assistant will already know about your skills.

> Important: changing skill settings does not affect current chats. You need to create a new chat.

## Built-in Skills List

### Public (always enabled)

| Skill | Description |
|-------|-------------|
| **Sub-agent** | Delegate complex tasks to an autonomous agent: presentations, refactoring, code review, Git |
| **XLSX** | Create and analyze spreadsheets with formulas, formatting, and visualization |
| **PDF** | Extract text and tables, create PDFs, merge/split, work with forms |
| **PDF to Markdown** | Convert PDF to Markdown preserving images via OCR |
| **PPTX** | Create and edit PowerPoint presentations |
| **Describe Images** | Describe charts, diagrams, screenshots using Vision AI |
| **GitLab Explorer** | Work with repositories: clone, code search, merge requests, CI/CD |
| **Skill Creator** | Guide for creating custom skills |
| **DOCX** | Create and edit Word documents |
| **Product Reference** | Information about AI products in Open Computer Use: models, integrations, settings |

### Examples (optional)

| Skill | Description |
|-------|-------------|
| **Algorithmic Art** | Generative art with p5.js: flow fields, particle systems |
| **Artifacts Builder** | HTML artifacts with React, Tailwind CSS, shadcn/ui |
| **Brand Guidelines** | Brand colors and typography for artifacts |
| **Canvas Design** | Posters, illustrations, and visual work in .png and .pdf |
| **Internal Communications** | Templates for status reports, newsletters, FAQs, project updates |
| **MCP Builder** | Create MCP servers in Python (FastMCP) or TypeScript |
| **Single Cell RNA QC** | Quality control for single-cell RNA sequencing data |
| **Slack GIF Creator** | Animated GIFs optimized for Slack |
| **Theme Factory** | 10 ready-made themes with colors and fonts for artifacts |

## How to Create Your Own Skill

### Skill Format

A skill is a ZIP archive containing a `SKILL.md` file at the root. The file starts with YAML frontmatter:

```markdown
---
name: my-skill-name
description: Brief description of the skill (up to 1024 characters)
---

# Skill Name

Main instructions for the assistant go here.

## When to Use

Description of situations where the skill applies.

## How to Use

Step-by-step instructions, examples, scripts.
```

### SKILL.md Requirements

**Required frontmatter fields:**

| Field | Rules |
|-------|-------|
| `name` | Lowercase Latin letters, digits, hyphens. Maximum 64 characters. Examples: `my-skill`, `data-analyzer`, `report-builder` |
| `description` | Text up to 1024 characters. No angle brackets (`<` `>`) |

**Optional fields:** `license`, `allowed-tools`, `metadata`

### ZIP Archive Structure

Minimal:
```
my-skill.zip
└── SKILL.md
```

With additional resources:
```
my-skill.zip
└── my-skill/
    ├── SKILL.md          # Required
    ├── scripts/          # Python/Bash scripts
    │   └── process.py
    └── references/       # Reference materials
        └── guide.md
```

### Limitations

- ZIP archive size: **up to 10 MB**
- Encoding: **UTF-8**
- `SKILL.md` must be at the root of the ZIP or in a single subdirectory

### Minimal Example

Create a file `SKILL.md`:

```markdown
---
name: greeting-skill
description: Skill for greeting users in different languages
---

# Greeting

When a user asks to greet someone, use this skill.

## Format

Greet in the language specified by the user. Default is English.

Examples:
- English: "Welcome, {name}!"
- Deutsch: "Willkommen, {name}!"
- Espanol: "Bienvenido, {name}!"
```

Package into a ZIP:
```bash
zip greeting-skill.zip SKILL.md
```

### Uploading a Skill

1. Go to **/skills**
2. At the bottom of the page, expand the **Upload a new skill** section
3. Select the ZIP file
4. Click **Upload**
5. After uploading, the skill will appear in the **User-uploaded** section
6. Enable it with the checkbox and click **Save settings**

### Updating a Skill

Upload a ZIP with the same `name` in the frontmatter. The system will update the skill automatically (only the author can update their skill).

### Deleting a Skill

In the **Skill Registry** section, find your skill -- user-uploaded skills that you created will have a **Delete** button. Deletion is irreversible.

## API for Developers

Base URL: ``

### List All Skills

```bash
curl /api/skills
```

With search:
```bash
curl "/api/skills?q=pdf"
```

### Upload a Skill (programmatically)

```bash
curl -X POST /api/skills \
  -F "file=@my-skill.zip" \
  -F "author_email=user@example.com"
```

### Delete a Skill

```bash
curl -X DELETE "/api/skills/my-skill?author_email=user@example.com"
```

### User Settings

Get current settings:
```bash
curl /api/user-skills/user@example.com
```

Enable/disable a skill:
```bash
curl -X PATCH /api/user-skills/user@example.com/algorithmic-art \
  -H "Content-Type: application/json" \
  -d '{"is_enabled": true}'
```

Bulk update:
```bash
curl -X PUT /api/user-skills/user@example.com \
  -H "Content-Type: application/json" \
  -d '{"skills": {"algorithmic-art": true, "mcp-builder": false}}'
```

## Architecture (for developers)

```
User
    │
    ▼
┌──────────────────────────────┐
│   │  ← Skill settings (Web UI + API)
│  mcp-settings-wrapper        │     PostgreSQL: mcp_tokens.skills
└──────────────┬───────────────┘     + mcp_tokens.user_skill_settings
               │
               │ GET /api/internal/user-config/{email}
               │ GET /api/internal/skills/{name}/download
               ▼
┌──────────────────────────────┐
│  docker-ai (computer-use-orchestrator)     │  ← Skill cache, Docker containers
│  skill_manager.py            │     /tmp/skills-cache/{name}/
└──────────────┬───────────────┘
               │
               │ bind mount + system prompt injection
               ▼
┌──────────────────────────────┐
│  Docker container            │  ← AI assistant
│  /mnt/skills/public/...      │     Public skills (baked in image)
│  /mnt/skills/examples/...    │     Examples (baked in image)
│  /mnt/skills/user/...        │     User-uploaded (bind mount)
└──────────────────────────────┘
```

Caching:
- User skill list: in-memory, TTL 60 seconds
- ZIP archives: on disk, invalidated by SHA-256 hash
- Fallback: if the API is unavailable, disk cache is used

## Related Documentation

- [DYNAMIC-SKILLS.md](DYNAMIC-SKILLS.md) -- technical architecture of Dynamic Skill Injection
- [SKILLS.md](SKILLS.md) -- reference guide for built-in skills with code examples
