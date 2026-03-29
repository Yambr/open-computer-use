# Sub-Agent Usage Guide

Detailed templates and reference for sub_agent tool. For basic usage, see SKILL.md.

---

## Task Templates

### Presentation

```
sub_agent(
    task="""
## ROLE
You are a business presentation specialist creating [TYPE] slides.

## DIRECTIVE
Create a [NUMBER]-slide presentation about [TOPIC] for [AUDIENCE].

## CONSTRAINTS
- Do NOT use more than [N] bullets per slide
- Do NOT use technical jargon if audience is non-technical
- Cite all sources for data claims

## PROCESS
1. Review source materials in /mnt/user-data/uploads/
2. Create slide outline with key messages
3. Build presentation with charts and visuals
4. Add speaker notes for each slide

## OUTPUT
- Save to /mnt/user-data/outputs/[filename].pptx
- Include speaker notes
- Create PDF version
""",
    description="[Brief description]",
    max_turns=50
)
```

---

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

### Research

```
sub_agent(
    task="""
## ROLE
You are a research analyst specializing in [DOMAIN].

## DIRECTIVE
Research [TOPIC] and create [DELIVERABLE].

## CONSTRAINTS
- Use only publicly available sources
- Focus on [YEAR]+ data
- Cite all sources with URLs

## PROCESS
1. Search for relevant information
2. Compile and analyze findings
3. Create structured report
4. Add source citations

## OUTPUT
- Save to /mnt/user-data/outputs/[filename].md
- Include sources section
- Add executive summary
""",
    description="[Brief description]",
    model="opus",
    max_turns=40
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

### Git Operations

```
sub_agent(
    task="""
## ROLE
You are a Git specialist managing repository operations.

## DIRECTIVE
[Git operation: analyze history, rebase, resolve conflicts]

## CONSTRAINTS
- Create backup branch before destructive operations
- Do NOT force push to shared branches
- Preserve commit authorship

## PROCESS
1. Analyze current state with git status/log
2. Create backup if needed
3. Perform operation
4. Verify result

## OUTPUT
- Show git log of result
- Create summary of operations
""",
    description="[Brief description]",
    max_turns=20
)
```

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
task="Create a presentation"
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
| `sonnet` | Default. Fast. Presentations, refactoring, file processing |
| `opus` | Complex reasoning: debugging, architecture, security analysis |

---

## Max Turns Guide

| max_turns | Use Case |
|-----------|----------|
| 10-20 | Simple tasks (single file) |
| 30-40 | Medium (few files) |
| 50 | (default) Presentations 10-15 slides |
| 60-80 | Large presentations 20+ slides, multi-file refactoring |
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
