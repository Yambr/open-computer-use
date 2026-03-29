# glab CLI Command Reference

Complete reference for GitLab CLI (glab) commands.

## Authentication

glab uses `GITLAB_TOKEN` environment variable automatically. No manual auth needed if token is set.

```bash
# Check current auth status
glab auth status

# Manual login (if needed)
glab auth login --hostname gitlab.com
```

## Projects / Repositories

### Search Projects

```bash
# Search by name
glab api "projects?search=KEYWORD" | jq '.[].path_with_namespace'

# Search with pagination
glab api "projects?search=KEYWORD&per_page=50" | jq '.[].path_with_namespace'

# Full-text search across GitLab
glab api "search?scope=projects&search=KEYWORD" | jq '.[].path_with_namespace'
```

### List Projects

```bash
# Projects in a group
glab api "groups/GROUP_NAME/projects" | jq '.[] | {name, path_with_namespace}'

# Your projects
glab api "users/USERNAME/projects" | jq '.[].path_with_namespace'

# All accessible projects (paginated)
glab api "projects?membership=true&per_page=100" | jq '.[].path_with_namespace'
```

### Clone Repository

```bash
glab repo clone group/project
# or
git clone https://gitlab.com/group/project.git
```

### View Repository Info

```bash
glab repo view group/project
```

## Merge Requests

### List MRs

```bash
# Open MRs in current repo
glab mr list

# All MRs (including closed)
glab mr list --all

# Your MRs
glab mr list --author=@me

# MRs assigned to you
glab mr list --assignee=@me

# Filter by state
glab mr list --state=merged
glab mr list --state=closed
```

### View MR Details

```bash
# View MR
glab mr view 123

# View in web browser
glab mr view 123 --web

# Show MR diff
glab mr diff 123

# Show MR with comments
glab mr view 123 --comments
```

### Work with MRs

```bash
# Checkout MR branch
glab mr checkout 123

# Approve MR
glab mr approve 123

# Merge MR
glab mr merge 123

# Create MR
glab mr create --title "Feature" --description "Description"
glab mr create --fill  # Auto-fill from commits
```

## Issues

### List Issues

```bash
# Open issues
glab issue list

# All issues
glab issue list --all

# Your issues
glab issue list --author=@me

# Assigned to you
glab issue list --assignee=@me

# By label
glab issue list --label="bug"
```

### Work with Issues

```bash
# View issue
glab issue view 123

# Create issue
glab issue create --title "Bug" --description "Details"

# Close issue
glab issue close 123

# Reopen issue
glab issue reopen 123

# Add comment
glab issue note 123 --message "Comment text"
```

## CI/CD Pipelines

### View Pipelines

```bash
# Current pipeline status
glab ci status

# List recent pipelines
glab ci list

# View specific pipeline
glab ci view PIPELINE_ID

# View pipeline in browser
glab ci view --web
```

### Pipeline Jobs

```bash
# List jobs
glab ci list --jobs

# View job logs
glab ci trace JOB_ID

# Retry failed pipeline
glab ci retry PIPELINE_ID

# Cancel pipeline
glab ci cancel PIPELINE_ID
```

### Trigger Pipeline

```bash
# Run pipeline on current branch
glab ci run

# Run on specific branch
glab ci run --branch main
```

## Releases

```bash
# List releases
glab release list

# View release
glab release view v1.0.0

# Create release
glab release create v1.0.0 --notes "Release notes"
```

## Generic API Access

For any GitLab API endpoint not covered by specific commands:

```bash
# GET request
glab api "endpoint"

# With query parameters
glab api "projects?search=test&per_page=10"

# POST request
glab api -X POST "projects/123/issues" -f title="New issue"

# PUT request
glab api -X PUT "projects/123/issues/1" -f state_event="close"

# DELETE request
glab api -X DELETE "projects/123/issues/1"
```

### Useful API Endpoints

```bash
# Current user
glab api user

# Project details
glab api "projects/GROUP%2FPROJECT"  # URL-encoded path

# Project members
glab api "projects/123/members"

# Project branches
glab api "projects/123/repository/branches"

# Project files
glab api "projects/123/repository/tree"

# File content
glab api "projects/123/repository/files/path%2Fto%2Ffile/raw?ref=main"

# Commits
glab api "projects/123/repository/commits?per_page=20"

# Groups
glab api groups

# Group members
glab api "groups/123/members"
```

## Output Formatting

glab outputs JSON by default. Use `jq` for formatting:

```bash
# Pretty print
glab api user | jq .

# Select fields
glab api user | jq '{username, email}'

# Array operations
glab api "projects?search=test" | jq '.[].name'

# Filter
glab api "projects?search=test" | jq '.[] | select(.name | contains("api"))'

# Count results
glab api "projects?search=test" | jq 'length'
```
