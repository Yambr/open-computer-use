---
name: sub-agent
description: "Delegate complex tasks to autonomous sub-agent. Use for: creating presentations, multi-file refactoring, code review, Git operations, research, documentation. Works like a powerful assistant within isolated environment."
---

# Sub-Agent Skill

Delegate complex, multi-step tasks to an autonomous sub-agent that can iterate until completion.

## When to Use

- Creating presentations (10+ slides)
- Multi-file refactoring
- Iterative test-fix cycles
- Research and reports
- Code review with fixes
- Complex Git operations

## When NOT to Use

Do **NOT** delegate if you can do it directly in 1-2 tool calls:
- Simple file reads/writes
- Single bash command
- Quick edits to one file

## MANDATORY: Task Structure

Every `task` MUST include these 5 sections:

```
## ROLE
"You are a [role] specializing in [domain]"

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
```

## Example: Bad vs Good

### BAD
```
sub_agent(
    task="Create a presentation about AI trends",
    description="User needs presentation"
)
```

### GOOD
```
sub_agent(
    task="""
## ROLE
You are a business presentation specialist.

## DIRECTIVE
Create a 12-slide presentation on AI adoption trends for executives.

## CONSTRAINTS
- Do NOT use technical jargon
- Do NOT include more than 5 bullets per slide
- Cite all sources

## PROCESS
1. Research current AI adoption statistics
2. Create slide outline with key messages
3. Build presentation with charts
4. Add speaker notes

## OUTPUT
- Save to /mnt/user-data/outputs/ai_trends.pptx
- Create executive_summary.pdf
""",
    description="AI presentation for board meeting",
    max_turns=50
)
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `task` | required | Structured task with ROLE/DIRECTIVE/CONSTRAINTS/PROCESS/OUTPUT |
| `description` | required | Why you're delegating this task |
| `mode` | "act" | "act" (execute) or "plan" (plan only, no changes) |
| `model` | "sonnet" | "sonnet" (fast) or "opus" (complex reasoning) |
| `max_turns` | 50 | Max iterations (50 for 15+ slides, 80+ for large refactoring) |
| `working_directory` | /home/assistant | Agent's working directory |
| `resume_session_id` | "" | Session ID to resume (from previous result) |

## Session Management

Session logs are stored at:
```
~/.claude/projects/-home-assistant/<session-id>.jsonl
```

### Finding sessions
```bash
find ~/.claude/projects -name "*.jsonl" -mmin -30
```

### Reading session history
```bash
tail -100 ~/.claude/projects/-home-assistant/<session-id>.jsonl
```

### Resuming a session (if max_turns was reached)
```bash
claude --resume <session-id>
```

The `session_id` is returned in sub_agent result JSON.

### When to resume:
- Sub-agent hit max_turns limit
- Task partially completed
- Need to continue work with same context

### How to resume via sub_agent tool:
```python
sub_agent(
    task="Continue the task. Previous progress: slide 8 of 15 completed.",
    description="Resume interrupted presentation",
    resume_session_id="abc123-session-id"
)
```

## Before You Start

**Read `references/usage.md`** if you need:

- **Task template** for your specific task type (presentation, refactoring, code review, research, git, test-fix)
- **Anti-patterns** - common mistakes that cause sub-agent to fail
- **Max turns guide** - how to choose the right value (10-20 for simple, 50+ for presentations)
- **Model selection** - when to use `opus` instead of `sonnet`
- **Environment details** - what paths and tools are available
