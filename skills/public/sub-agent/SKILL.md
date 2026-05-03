---
name: sub-agent
description: "COSTLY: Spawns a separate sub-agent CLI session. Use ONLY for complex CODE tasks requiring 10+ iterative tool calls (multi-file refactoring with tests, code review with fixes, test-fix cycles). IMPORTANT: Always run the model discovery script first before any sub_agent call. Do NOT use for presentations, research, documentation, or any task completable in fewer than 10 tool calls."
---

# Sub-Agent Skill

Delegate complex, multi-step tasks to an autonomous sub-agent that can iterate until completion.

## Before Any sub_agent Call

**ALWAYS run the model discovery script first:**

```bash
bash /mnt/skills/public/sub-agent/scripts/list_subagent_models.sh
```

This script will:
- Detect `SUBAGENT_CLI` (default `claude`)
- Enumerate valid model identifiers via the CLI's native model-listing mechanism (or, for claude, return the canonical alias set: <!-- canonical-example -->`sonnet` / `opus` / `haiku`<!-- /canonical-example -->)
- Output stable JSON with `cli` / `models[]` / `default_model` / `source` fields
- Fail with a structured JSON error to stderr (exit 2 or 3) if the CLI is missing or its command fails — never silently falls back to a stale list

**Why this matters:** Model identifiers differ per CLI. Some CLIs accept short aliases that the CLI resolves internally; others require fully-qualified `<provider>/<model-id>` strings; others accept only concrete fully-qualified ids with no aliases at all. Operators may extend the alias vocabulary for some CLIs via the `OPENCODE_MODEL_ALIASES` env var (JSON object string mapping alias to `<provider>/<model-id>`). The discovery script is the only authoritative source for what works in the current container.

**Default behavior when `model` is omitted:** Run `list-subagent-models` to discover the active default for the current `SUBAGENT_CLI`. The claude runtime has a hardcoded baseline alias <!-- canonical-example -->(`sonnet`)<!-- /canonical-example -->; opencode and codex require explicit configuration via the per-CLI `<CLI>_SUB_AGENT_DEFAULT_MODEL` env var or a caller-passed `model` argument — they raise an actionable error otherwise.

After running the script, pass a concrete model id from the JSON output to `sub_agent(model=...)`. Never assume Claude aliases work for non-claude CLIs.

## When to Use (ONLY complex CODE tasks requiring 10+ iterative tool calls)

WARNING: Each sub_agent call spawns a SEPARATE Claude CLI session consuming significant API resources. Use as a LAST RESORT.

- Multi-file refactoring (5+ files) with test verification loops
- Complex code review with automatic fixes across many files
- Iterative test-fix cycles (run tests → analyze → fix → re-run until pass)

Only delegate non-code tasks (presentations, research) if the user EXPLICITLY asks.

## When NOT to Use

**Precedence:** if the user explicitly asks to delegate any of the items below
(e.g. "please use sub_agent for this presentation"), the user's request wins
and you may delegate. Otherwise treat the list as hard rules.

Do **NOT** delegate if ANY of these apply (and the user has not explicitly
overridden the rule for this specific task):
- Task can be done in fewer than 10 tool calls (even if it seems tedious)
- Creating presentations, documents, spreadsheets (do it yourself)
- Web research or information gathering (use search tools directly)
- Simple code review or analysis (read files and respond)
- Documentation or report writing (create files directly)
- Git operations (commits, merges, rebases)
- Single-file or few-file edits

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
    task="Fix failing tests in the project",
    description="Tests are red"
)
```

Too vague — no test command, no scope, no stop condition. The sub-agent will
thrash over the whole codebase and likely exhaust `max_turns`.

### GOOD
```python
sub_agent(
    task="""
## ROLE
You are a Python debugging specialist fixing a broken test suite after a refactor.

## DIRECTIVE
Run `pytest tests/orchestrator/` and fix every failing test until the suite is green.
The refactor renamed `SkillStore` → `SkillManager`; most failures are stale imports
and fixture mocks that still reference the old name.

## CONSTRAINTS
- Do NOT modify the public test assertions (what they check, not how they set up).
- Do NOT touch tests outside `tests/orchestrator/`.
- Stop after 5 consecutive iterations with no new tests passing; report blockers.

## PROCESS
1. Run the test command, capture the failing set.
2. For each failure, identify root cause (import? mock? behaviour change?).
3. Fix in production code when the refactor is incomplete; fix in fixtures when
   the fixture is pinning the old name.
4. Re-run the suite, repeat until all green or stop condition hit.

## OUTPUT
- All `tests/orchestrator/` tests passing.
- Summary of files changed with one-line rationale per file.
- If any test remains red, explain why and what the blocker is.
""",
    description="Fix post-refactor test suite",
    max_turns=25
)
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `task` | required | Structured task with ROLE/DIRECTIVE/CONSTRAINTS/PROCESS/OUTPUT |
| `description` | required | Why you're delegating this task |
| `mode` | "act" | "act" (execute) or "plan" (plan only, no changes) |
| `model` | "discover via list-subagent-models" | Concrete model id from list-subagent-models output. Pass empty string for the per-CLI default (claude → baseline; opencode/codex → requires env). |
| `max_turns` | 25 | Max iterations (default; raise to 50-80 for large multi-file refactors) |
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
    task="Continue the refactor. Previous progress: 12 of 18 modules migrated, test suite still red.",
    description="Resume interrupted refactor",
    resume_session_id="abc123-session-id"
)
```

## Before You Start

**Read `references/usage.md`** if you need:

- **Task template** for your specific task type (refactoring, code review, test-fix cycles)
- **Anti-patterns** - common mistakes that cause sub-agent to fail
- **Max turns guide** - how to choose the right value (10-20 for simple, 50+ for large refactors)
- **Model selection** - how to pick the right model from `list-subagent-models` output
- **Environment details** - what paths and tools are available
