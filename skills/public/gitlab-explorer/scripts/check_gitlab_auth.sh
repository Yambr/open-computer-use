#!/bin/bash
# GitLab Authentication Check Script
#
# This script checks if GitLab authentication is configured and valid.
# It does NOT output the token itself - only the validation result.
#
# Usage: bash check_gitlab_auth.sh

# Check if GITLAB_TOKEN is set
if [ -z "$GITLAB_TOKEN" ]; then
    echo "============================================"
    echo "  GitLab Authentication NOT Configured"
    echo "============================================"
    echo ""
    echo "To enable GitLab features, please:"
    echo ""
    echo "  1. Go to "
    echo "  2. Log in with your corporate account"
    echo "  3. Add your GitLab Personal Access Token"
    echo "  4. Start a NEW chat (token is injected at container start)"
    echo ""
    echo "--------------------------------------------"
    echo "How to get GitLab Personal Access Token:"
    echo "--------------------------------------------"
    echo "  1. Go to GitLab -> Settings -> Access Tokens"
    echo "  2. Create token with scopes: api, read_repository"
    echo "  3. Copy the token and paste it in llm-keys"
    echo ""
    echo "After setup, you'll be able to:"
    echo "  - Clone private repositories"
    echo "  - Search projects and code"
    echo "  - View merge requests and issues"
    echo "  - Check CI/CD pipelines"
    echo ""
    exit 1
fi

# Token exists - validate it by calling GitLab API
echo "Checking GitLab authentication..."
echo ""

RESULT=$(glab api user 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    # Check if jq is available
    if ! command -v jq &> /dev/null; then
        echo "============================================"
        echo "  GitLab Authentication VALID"
        echo "============================================"
        echo ""
        echo "(jq not installed - cannot parse user details)"
        echo ""
        echo "You can now use glab and git commands."
        echo ""
        exit 0
    fi

    # Check if RESULT is valid JSON
    if ! echo "$RESULT" | jq empty 2>/dev/null; then
        echo "============================================"
        echo "  GitLab Authentication VALID"
        echo "============================================"
        echo ""
        echo "(Could not parse API response)"
        echo ""
        echo "You can now use glab and git commands."
        echo ""
        exit 0
    fi

    # Parse user info from JSON response
    USERNAME=$(echo "$RESULT" | jq -r '.username // "unknown"')
    EMAIL=$(echo "$RESULT" | jq -r '.email // "unknown"')
    NAME=$(echo "$RESULT" | jq -r '.name // "unknown"')

    echo "============================================"
    echo "  GitLab Authentication VALID"
    echo "============================================"
    echo ""
    echo "Logged in as:"
    echo "  Name:     $NAME"
    echo "  Username: $USERNAME"
    echo "  Email:    $EMAIL"
    echo ""
    echo "You can now use glab and git commands."
    echo "All operations will be performed as this user."
    echo ""
    exit 0
else
    echo "============================================"
    echo "  GitLab Token INVALID or EXPIRED"
    echo "============================================"
    echo ""
    echo "Your token is present but could not be validated."
    echo ""
    echo "Possible reasons:"
    echo "  - Token has expired"
    echo "  - Token was revoked"
    echo "  - Token doesn't have required scopes"
    echo "  - Network connectivity issues"
    echo ""
    echo "To fix this:"
    echo "  1. Go to "
    echo "  2. Update your GitLab Personal Access Token"
    echo "  3. Start a NEW chat to apply the updated token"
    echo ""
    exit 1
fi
