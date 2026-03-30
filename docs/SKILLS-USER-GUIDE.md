# Skills User Guide

Skills extend the AI assistant's capabilities. Each skill is a folder with `SKILL.md` instructions and optional scripts that teach the AI to work with a specific domain: creating presentations, processing PDFs, browser automation, etc.

## How Skills Work

1. **System prompt injection** — the server builds an `<available_skills>` XML block listing all skills with names, descriptions, and file paths
2. **Model reads SKILL.md** — before starting a task, the AI reads the relevant skill's instructions via `view` tool
3. **Scripts and references** — skills can include Python/bash helper scripts and reference docs that the AI uses

Skills are mounted read-only into sandbox containers at `/mnt/skills/`.

## Built-in Skills (13 public)

Always available, baked into the Docker image:

| Skill | What it does |
|-------|--------------|
| **docx** | Word documents — create, edit, tracked changes, comments |
| **pdf** | PDF — extract text/tables, create, merge/split, fill forms |
| **pptx** | PowerPoint — create with html2pptx, edit via OOXML |
| **xlsx** | Excel — formulas, formatting, analysis, visualization |
| **sub-agent** | Delegate complex tasks to autonomous Claude Code agent |
| **playwright-cli** | Browser automation — navigate, fill forms, screenshot |
| **describe-image** | Image analysis via Vision AI |
| **frontend-design** | Production-grade UI/web components |
| **webapp-testing** | Test web apps with Playwright |
| **doc-coauthoring** | Structured document co-authoring workflow |
| **test-driven-development** | TDD workflow enforcement |
| **skill-creator** | Guide for creating new skills |
| **gitlab-explorer** | GitLab repo operations via glab CLI |

## Example Skills (14)

Optional, also in the Docker image at `/mnt/skills/examples/`:

web-artifacts-builder, copy-editing, social-content, canvas-design, algorithmic-art, theme-factory, mcp-builder, product-marketing-context, writing-skills, internal-comms, single-cell-rna-qc, slack-gif-creator, skill-creator (example version)

## Creating Your Own Skill

A skill is a folder with `SKILL.md` at the root:

```
my-skill/
├── SKILL.md          # Required — instructions for the AI
├── scripts/          # Optional — helper scripts
│   └── process.py
└── references/       # Optional — reference docs
    └── guide.md
```

### SKILL.md format

```markdown
---
name: my-skill-name
description: Brief description (this is what the AI sees in the skills list)
---

# My Skill Name

Instructions for the AI go here. Be specific about:
- When to use this skill
- Step-by-step workflow
- Which scripts to run and how
- Expected output format
```

See `skills/public/` for real examples.

## Skill Management

In our production setup, we built a **skill registry** (settings-wrapper) where:
- AI manages skills through a dedicated **settings-manager** skill
- Users can enable/disable skills per account
- Custom skills are uploaded as ZIP archives and cached on the server

For community use, we provide a [mock settings-wrapper](../settings-wrapper/README.md) with the API contract. All 13 public skills work out of the box without it.

**Want a public skill management tool?** We'd love to build one that works with your setup. Open a [GitHub Issue](https://github.com/Yambr/openwebui-computer-use-community/issues) and tell us what you use (LiteLLM, Open WebUI standalone, Claude Desktop, etc.) — this helps us prioritize.

## Related Docs

- [SKILLS.md](SKILLS.md) — technical reference for all skills
- [DYNAMIC-SKILLS.md](DYNAMIC-SKILLS.md) — how skill injection works under the hood
- [settings-wrapper/README.md](../settings-wrapper/README.md) — mock skill registry API contract
