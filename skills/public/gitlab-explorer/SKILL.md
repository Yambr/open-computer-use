---
name: gitlab-explorer
description: "Explore GitLab repositories using glab CLI and git commands. Use when user asks to: clone repositories, search projects or code in GitLab, view merge requests, explore project structure, check CI/CD pipelines, work with issues, or analyze git history. IMPORTANT: Always run authentication check script first before any GitLab operation."
---

# GitLab Explorer

This skill enables exploring GitLab repositories, searching code, viewing merge requests, and working with git history.

## Before Any GitLab Operation

**ALWAYS run the authentication check first:**

```bash
bash /mnt/skills/public/gitlab-explorer/scripts/check_gitlab_auth.sh
```

This script will:
- Verify if GitLab token is configured
- Validate the token by calling GitLab API
- Show logged-in user info if valid
- Provide setup instructions if not configured

**DO NOT** try to read or echo `$GITLAB_TOKEN` directly - the script handles validation securely without exposing the token.

If authentication is not configured, inform the user:
> To use GitLab features, please go to  and add your GitLab Personal Access Token. Then start a NEW chat to apply the token.

## Quick Start

### Clone a Repository

```bash
git clone https://gitlab.com/group/project.git
cd project
```

### Search for Projects

```bash
# Search projects by name
glab api "projects?search=keyword" | jq '.[].path_with_namespace'

# List projects in a group
glab api "groups/GROUP_NAME/projects" | jq '.[].name'
```

### Check Current User

```bash
glab api user | jq '{username, email, name}'
```

## Exploring Code

### Repository Structure

```bash
# Show directory tree
tree -L 2

# Find files by pattern
find . -name "*.py" -type f

# Search for text in files
git grep "pattern"
```

### Git History

```bash
# View commit history
git log --oneline -20

# Visual branch history
git log --oneline --graph --all -20

# Who changed what
git blame filename

# Show specific commit
git show COMMIT_HASH

# Changes between branches
git diff main..feature-branch
```

### Top Contributors

```bash
git shortlog -sn --all | head -10
```

## Working with Merge Requests

```bash
# List open MRs
glab mr list

# View specific MR
glab mr view 123

# Show MR diff
glab mr diff 123

# Checkout MR branch locally
glab mr checkout 123
```

## CI/CD Pipelines

```bash
# Current pipeline status
glab ci status

# List recent pipelines
glab ci list

# View pipeline details
glab ci view PIPELINE_ID

# Watch job logs in real-time
glab ci trace
```

## Issues

```bash
# List issues
glab issue list

# View issue details
glab issue view 123

# Create new issue
glab issue create --title "Bug report" --description "Description here"
```

## Reference Materials

For detailed command reference, see:
- `references/glab-commands.md` - Complete glab CLI reference
- `references/git-commands.md` - Git commands for code exploration

## Common Workflows

### Explore Unknown Repository

1. Clone the repo
2. Check README and documentation
3. Explore directory structure with `tree`
4. Find main entry points
5. Use `git log` to understand recent changes
6. Use `git blame` to find who wrote specific code

### Review Merge Request

1. `glab mr view ID` - read description
2. `glab mr diff ID` - review changes
3. `glab mr checkout ID` - test locally if needed
4. Check CI status with `glab ci status`

### Find Code by Pattern

```bash
# Search in all files
git grep "function_name"

# Search with context
git grep -n -C 3 "pattern"

# Search in specific file types
git grep "pattern" -- "*.py"
```
