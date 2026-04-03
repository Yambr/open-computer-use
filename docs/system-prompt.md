# System Prompt Reference

The Computer Use Server uses a dynamic system prompt that teaches AI models how to interact with the sandbox environment — tools, skills, file handling, output sharing, and more.

## Dynamic API Endpoints

Instead of hardcoding the system prompt, MCP clients should fetch it dynamically from the server to get up-to-date skills, correct file URLs, and the latest instructions.

### GET /system-prompt

Returns the full system prompt as plain text.

| Parameter | Description | Required |
|-----------|-------------|----------|
| `chat_id` | Session ID — server constructs file download URLs from this | Recommended |
| `user_email` | If provided, returns a prompt with user-specific skills | No |

```bash
curl "http://localhost:8081/system-prompt?chat_id=my-session&user_email=user@example.com"
```

When `user_email` is provided, the server fetches the user's enabled skills from the settings wrapper and injects them into the `<available_skills>` block. Without it, the server returns a fallback prompt with the default 13 public skills.

### GET /skill-list

Returns available skills as formatted text (for sub-agent delegation prompts).

| Parameter | Description | Required |
|-----------|-------------|----------|
| `user_email` | If provided, returns user-specific skills | No |

```bash
curl "http://localhost:8081/skill-list?user_email=user@example.com"
```

### GET /mcp-info

Returns MCP endpoint metadata as JSON: available tools, required headers, endpoint URL.

```bash
curl "http://localhost:8081/mcp-info" \
  -H "Authorization: Bearer $MCP_API_KEY"
```

## Best Practices for MCP Clients

1. **Fetch the system prompt dynamically** via `GET /system-prompt?chat_id={id}` at session start — this ensures the AI model gets the correct file URLs and the latest skill set
2. **Pass `user_email`** if your platform supports per-user skill configuration
3. **Use `/mcp-info`** to discover available tools and required headers programmatically
4. **Do not hardcode** the system prompt — it evolves with new skills and features

## System Prompt Structure

The prompt is built from three parts (defined in `computer-use-server/system_prompt.py`):

1. **Before Skills** — core instructions:
   - Skill usage workflow (read SKILL.md before acting)
   - File creation triggers
   - Assistant identity
   - Tool usage tips (prefer `view` over `cat`, `str_replace` over `sed`)
   - Error handling guidelines
   - Web search instructions
   - Sub-agent delegation rules
   - File handling (uploads in `/mnt/user-data/uploads`, outputs in `/mnt/user-data/outputs`)
   - Context window protection (large file safeguards)
   - Output sharing (HTTP links, image markdown syntax)
   - Artifact creation (HTML, React, Mermaid, SVG)
   - Package management (`pip --break-system-packages`, npm paths)

2. **Available Skills XML** — dynamic block listing enabled skills:
   - `docx` — Word document creation and editing
   - `pdf` — PDF manipulation, form filling, text extraction
   - `pptx` — Presentation creation and editing
   - `xlsx` — Spreadsheet creation, formulas, data analysis
   - `playwright-cli` — Browser automation, screenshots, web testing
   - `sub-agent` — Delegate complex tasks to autonomous Claude Code
   - `describe-image` — Vision AI for image description
   - `frontend-design` — Production-grade web UI creation
   - `doc-coauthoring` — Structured document co-authoring workflow
   - `webapp-testing` — Local web app testing with Playwright
   - `test-driven-development` — TDD workflow
   - `skill-creator` — Guide for creating new skills
   - `gitlab-explorer` — GitLab repository exploration

3. **After Skills** — filesystem configuration (read-only mount points)
