# Sub-Agent Usage Guide

Detailed templates and reference for sub_agent tool. For basic usage, see SKILL.md.

**Scope reminder:** `sub_agent` is for complex CODE tasks that require 10+ iterative
tool calls (multi-file refactoring with test loops, code review with fixes across
many files, iterative test-fix cycles). Do **not** delegate presentations, research,
documentation writing, or anything completable in under 10 tool calls — handle those
yourself. Only delegate non-code work if the user explicitly asks.

---

## Task Templates

### Refactoring

```
sub_agent(
    task="""
## ROLE
You are a [LANGUAGE] refactoring specialist.

## DIRECTIVE
[Specific operation: rename class, extract method, migrate pattern]

## CONSTRAINTS
- Do NOT modify test assertions content
- Do NOT refactor unrelated code
- Follow existing code style: [formatter]

## PROCESS
1. Find target definition
2. Identify all usages with grep
3. Update definition and all usages
4. Run formatter on changed files

## OUTPUT
- All affected files updated
- Verify: run [test command] - all tests must pass
- Create summary of changed files
""",
    description="[Brief description]",
    max_turns=30
)
```

---

### Code Review

```
sub_agent(
    task="""
## ROLE
You are a security engineer reviewing code for vulnerabilities.

## DIRECTIVE
Review [SCOPE] for [TYPE] issues and create report.

## CONSTRAINTS
- Focus on HIGH confidence issues only
- Do NOT report theoretical vulnerabilities
- Auto-fix only safe issues, report others

## PROCESS
1. Scan codebase for vulnerability patterns
2. Trace data flow from inputs to sensitive operations
3. Categorize findings by severity
4. Create detailed report

## OUTPUT
- Create /mnt/user-data/outputs/security_review.md
- Group by severity (Critical/High/Medium)
- Include file:line references
""",
    description="[Brief description]",
    model="opus",
    max_turns=40
)
```

See `references/security-review.md` for detailed security review guidelines.

---

### Test-Fix Cycle

```
sub_agent(
    task="""
## ROLE
You are a debugging specialist fixing test failures.

## DIRECTIVE
Run tests, analyze failures, fix issues until all pass.

## CONSTRAINTS
- Do NOT modify test assertions without approval
- Fix only failing tests, not warnings
- Max [N] fix attempts before reporting

## PROCESS
1. Run test suite: [command]
2. Analyze failure output
3. Fix identified issue
4. Re-run tests
5. Repeat until pass or max attempts

## OUTPUT
- All tests passing (or report unfixable)
- Summary of fixes applied
""",
    description="[Brief description]",
    max_turns=50
)
```

---

## Anti-Patterns

### Vague Tasks
```
# BAD
task="Fix the tests"
task="Refactor the code"
```

### Missing Output Location
```
# BAD - where to save?
task="Create an analysis report"

# GOOD
## OUTPUT
- Save to /mnt/user-data/outputs/report.md
```

### No Verification
```
# BAD - how to verify?
task="Update all imports"

# GOOD
## OUTPUT
- Verify: run pytest - all tests must pass
```

### Missing Constraints
```
# BAD - what style? what to preserve?
task="Add docstrings to functions"

# GOOD
## CONSTRAINTS
- Use Google-style docstrings
- Only public functions
- Do NOT modify existing docstrings
```

---

## Mode Selection

| Mode | Use When |
|------|----------|
| `act` (default) | Execute immediately with full permissions |
| `plan` | Planning only, no file modifications. Use to understand scope first |

---

## Model Selection

| Model | Use When |
|-------|----------|
| `sonnet` | Default. Fast. Refactoring, file processing, test-fix cycles |
| `opus` | Complex reasoning: debugging, architecture, security analysis |

---

## Max Turns Guide

Single-file or few-file work belongs in the main session — do not delegate
those. The table starts at the smallest size that is still in-scope for
`sub_agent` (multi-file refactors + test loops).

| max_turns | Use Case |
|-----------|----------|
| 25 | (default) Short multi-file refactor with test verification |
| 30-40 | Medium multi-file refactoring (5-10 files + tests) |
| 50-80 | Large multi-file refactoring with test loops, iterative test-fix cycles |
| 100+ | Full codebase refactoring |

---

## Environment

The sub-agent has access to:
- `/home/assistant` - Working directory
- `/home/assistant/task_plan.md` - Task saved here (re-read if context compacts)
- `/mnt/user-data/uploads` - User files (read-only)
- `/mnt/user-data/outputs` - Output files (accessible to user)
- `/mnt/skills/` - All skills documentation
- Full internet access
- All installed tools (Python, Node.js, LibreOffice, etc.)
