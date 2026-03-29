# Git Commands for Code Exploration

Commands useful for understanding and exploring codebases.

## Repository Overview

### Directory Structure

```bash
# Tree view (2 levels deep)
tree -L 2

# Tree with file sizes
tree -L 2 -h

# Only directories
tree -L 3 -d

# Exclude patterns
tree -L 2 -I "node_modules|__pycache__|.git"
```

### Find Files

```bash
# Find by name
find . -name "*.py" -type f

# Find by pattern
find . -name "*test*" -type f

# Find recently modified
find . -mtime -7 -type f  # Last 7 days

# Count files by extension
find . -type f -name "*.py" | wc -l
```

## Git History

### View Commits

```bash
# Simple log
git log --oneline -20

# With graph
git log --oneline --graph -20

# All branches
git log --oneline --graph --all -20

# Detailed log
git log -5

# One commit per line with date
git log --format="%h %ad %s" --date=short -20
```

### Filter History

```bash
# By author
git log --author="name" --oneline -20

# By date range
git log --since="2024-01-01" --until="2024-12-31" --oneline

# By file
git log --oneline -- path/to/file

# By message
git log --grep="fix" --oneline -20

# Commits that changed a function
git log -S "function_name" --oneline
```

### View Changes

```bash
# Show specific commit
git show COMMIT_HASH

# Show only file names changed
git show --name-only COMMIT_HASH

# Show stats
git show --stat COMMIT_HASH

# Show specific file at commit
git show COMMIT_HASH:path/to/file
```

## Code Archaeology

### Git Blame

```bash
# Who wrote each line
git blame filename

# Blame specific lines
git blame -L 10,20 filename

# Ignore whitespace
git blame -w filename

# Show email instead of name
git blame -e filename
```

### File History

```bash
# History of a file
git log --oneline -- path/to/file

# History with patches
git log -p -- path/to/file

# When file was created
git log --diff-filter=A -- path/to/file

# When file was deleted
git log --diff-filter=D -- path/to/file
```

### Find When Code Changed

```bash
# Find commits that added/removed string
git log -S "search_string" --oneline

# Find commits that changed regex match count
git log -G "regex_pattern" --oneline

# Show the actual changes
git log -S "search_string" -p
```

## Searching Code

### Git Grep

```bash
# Basic search
git grep "pattern"

# With line numbers
git grep -n "pattern"

# With context
git grep -n -C 3 "pattern"

# Case insensitive
git grep -i "pattern"

# Only filenames
git grep -l "pattern"

# Count matches per file
git grep -c "pattern"

# In specific file types
git grep "pattern" -- "*.py"
git grep "pattern" -- "*.js" "*.ts"

# Exclude paths
git grep "pattern" -- ':!node_modules' ':!vendor'

# Regex search
git grep -E "func[A-Z][a-zA-Z]*\("

# Multiple patterns (AND)
git grep -e "pattern1" --and -e "pattern2"

# Multiple patterns (OR)
git grep -e "pattern1" -e "pattern2"
```

## Comparing Code

### Diff Commands

```bash
# Working directory vs staged
git diff

# Staged vs last commit
git diff --staged

# Between commits
git diff COMMIT1 COMMIT2

# Between branches
git diff main..feature-branch

# Only file names
git diff --name-only main..feature-branch

# Statistics
git diff --stat main..feature-branch

# Specific file
git diff main..feature-branch -- path/to/file
```

### Compare Files

```bash
# File between branches
git diff main:path/to/file feature:path/to/file

# File at different commits
git diff COMMIT1:file COMMIT2:file

# Show file from another branch
git show other-branch:path/to/file
```

## Branch Information

### List Branches

```bash
# Local branches
git branch

# Remote branches
git branch -r

# All branches
git branch -a

# With last commit
git branch -v

# Merged branches
git branch --merged

# Not merged
git branch --no-merged
```

### Branch Comparison

```bash
# Commits in feature not in main
git log main..feature --oneline

# Commits in main not in feature
git log feature..main --oneline

# Files changed between branches
git diff --name-only main..feature
```

## Statistics

### Contributors

```bash
# Top contributors by commits
git shortlog -sn --all | head -10

# Contributors to specific file
git shortlog -sn -- path/to/file

# Contributors in date range
git shortlog -sn --since="2024-01-01"
```

### Code Stats

```bash
# Lines added/removed by author
git log --author="name" --numstat --format="" | awk '{add+=$1; del+=$2} END {print "Added:", add, "Deleted:", del}'

# Repository statistics
git rev-list --count HEAD  # Total commits

# Files in repo
git ls-files | wc -l
```

## Tags and Releases

```bash
# List tags
git tag

# List with messages
git tag -n

# Show tag details
git show v1.0.0

# Commits since tag
git log v1.0.0..HEAD --oneline
```

## Useful Aliases

Add to `~/.gitconfig`:

```ini
[alias]
    lg = log --oneline --graph --all -20
    st = status -sb
    last = log -1 --stat
    who = shortlog -sn --all
    find = "!git ls-files | grep -i"
```

Then use:
```bash
git lg      # Pretty log
git st      # Short status
git last    # Last commit
git who     # Contributors
git find pattern  # Find files
```
