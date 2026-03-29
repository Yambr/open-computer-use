---
name: settings-manager
description: "Manage AI assistant settings: check MCP token status (Confluence, Jira, GitLab), view/toggle/publish/install/upload/download skills, get recommendations. Use when user asks about settings, capabilities, skills, tokens; wants to publish, upload, install, enable, disable, or download a skill (.skill file); or when a tool call fails with 'No token found' error."
---

# AI Assistant Settings Manager

## When to Use

- User asks about skills, settings, tokens, or capabilities
- User says "what can you do", "what features are available"
- A Confluence/Jira/GitLab tool call fails with "No token found" — proactively offer to configure the token
- User complains something isn't working (Confluence, Jira) — check tokens

## CLI Utility

The `settings-cli.py` script is located in this skill's directory.

```bash
# Check MCP token status
python /mnt/skills/public/settings-manager/scripts/settings-cli.py check-tokens

# View user's skills (enabled + available)
python /mnt/skills/public/settings-manager/scripts/settings-cli.py my-skills

# Enable a skill (use English name from my-skills output, NOT display_name)
python /mnt/skills/public/settings-manager/scripts/settings-cli.py toggle <skill-name> on

# Disable a skill
python /mnt/skills/public/settings-manager/scripts/settings-cli.py toggle <skill-name> off

# Search skills by description
python /mnt/skills/public/settings-manager/scripts/settings-cli.py search <query>

# Download a skill (user-uploaded only)
python /mnt/skills/public/settings-manager/scripts/settings-cli.py download <skill-name>

# Upload a packaged .skill file (new or update)
python /mnt/skills/public/settings-manager/scripts/settings-cli.py upload <file.skill>
```

## Web UI for Manual Configuration

- Tokens: https://example.com
- Skills: https://example.com

## Getting the Current Skills List

Never use hardcoded skill lists — skills are added frequently. Always fetch live data via CLI:

```bash
# Current user's skills (enabled + available)
python /mnt/skills/public/settings-manager/scripts/settings-cli.py my-skills

# Full catalog of all skills (public + example + user)
python /mnt/skills/public/settings-manager/scripts/settings-cli.py search ""

# Search by keywords
python /mnt/skills/public/settings-manager/scripts/settings-cli.py search <query>
```

`my-skills` output is grouped: always-on → enabled optional → available (disabled, with user count).

## Recommendation Logic

When the user asks "what do you recommend" or describes their work:

1. Run `my-skills` to see what's already enabled and what's available
2. Based on the user's task description, suggest relevant skills from the available (disabled) list
3. Use user count as a popularity indicator — skills with more users are more likely to be relevant

## Creating and Publishing Skills

To create a new skill, use the **skill-creator** skill (always available):

```bash
# Read the skill creation guide
cat /mnt/skills/public/skill-creator/SKILL.md

# Initialize a new skill from template
python /mnt/skills/public/skill-creator/scripts/init_skill.py <skill-name> --path .

# Validate skill structure before publishing
python /mnt/skills/public/skill-creator/scripts/quick_validate.py ./<skill-name>
```

For advanced skill design methodology (TDD, testing with sub-agents, bulletproofing):

```bash
cat /mnt/skills/examples/writing-skills/SKILL.md
```

### Publishing workflow

```bash
# 1. Package skill into .skill file (validates + zips)
python /mnt/skills/public/skill-creator/scripts/package_skill.py ./<skill-name>

# 2. Upload .skill file to registry
python /mnt/skills/public/settings-manager/scripts/settings-cli.py upload ./<skill-name>.skill

# 3. Enable for your future chats
python /mnt/skills/public/settings-manager/scripts/settings-cli.py toggle <skill-name> on
```

If a skill with the same name exists and belongs to you — it gets updated (auto-increments patch version). Otherwise a new skill is created.

### Inspect or fork someone else's skill

```bash
# Download and extract
python /mnt/skills/public/settings-manager/scripts/settings-cli.py download <skill-name>

# Read SKILL.md, modify, re-package and upload under a new name
```

## Proactive Hints

1. **Confluence/Jira failure:** If a tool call returns a token error — immediately tell the user: "It looks like your {service} token is not configured. Let me check." → run `check-tokens`

2. **New user:** If `check-tokens` shows nothing is configured — suggest: "To use Confluence and Jira, you need personal tokens. Configure them here: https://example.com"

3. **Few enabled skills:** If the user has <3 optional skills enabled — gently suggest: "You have {N} additional skills available. Want to see what's there?"

4. **Kubernetes request:** If user asks about pods, deployments, k8s, or cluster management — check if kubectl skill is enabled via `my-skills`. If disabled, suggest: "Enable kubectl skill for Kubernetes access: `toggle kubectl on`"
