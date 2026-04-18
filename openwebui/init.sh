#!/bin/bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
# Open WebUI initialization script
# Waits for Open WebUI to be ready, then installs tools, functions, and configures valves.
# Runs once on first startup — skips if already configured.

set -euo pipefail

WEBUI_URL="${WEBUI_URL:-http://localhost:8080}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@open-computer-use.dev}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
ADMIN_NAME="${ADMIN_NAME:-Admin}"
MCP_SERVER_URL="${MCP_SERVER_URL:-http://localhost:8081}"
MCP_SERVER_EXTERNAL_URL="${MCP_SERVER_EXTERNAL_URL:-http://localhost:8081}"
MCP_API_KEY="${MCP_API_KEY:-}"
MARKER_FILE="/app/backend/data/.computer-use-initialized"

# Skip if already initialized
if [ -f "$MARKER_FILE" ]; then
    echo "[init] Already initialized, skipping."
    exit 0
fi

echo "[init] Waiting for Open WebUI to be ready..."
for i in $(seq 1 60); do
    if curl -sf "$WEBUI_URL/api/version" >/dev/null 2>&1; then
        echo "[init] Open WebUI is ready."
        break
    fi
    sleep 2
done

# Check if any users exist
USERS=$(curl -sf "$WEBUI_URL/api/v1/auths/signin" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" 2>/dev/null || echo "")

if echo "$USERS" | python3 -c "import sys,json; json.load(sys.stdin)['token']" 2>/dev/null; then
    TOKEN=$(echo "$USERS" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
    echo "[init] Logged in as existing admin."
else
    # Try to create first user (becomes admin automatically)
    SIGNUP=$(curl -sf "$WEBUI_URL/api/v1/auths/signup" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\",\"name\":\"$ADMIN_NAME\"}" 2>/dev/null || echo "")

    if echo "$SIGNUP" | python3 -c "import sys,json; json.load(sys.stdin)['token']" 2>/dev/null; then
        TOKEN=$(echo "$SIGNUP" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
        echo "[init] Created admin user: $ADMIN_EMAIL"
    else
        echo "[init] WARNING: Could not create or login as admin. Manual setup required."
        echo "[init] Try: email=$ADMIN_EMAIL password=$ADMIN_PASSWORD"
        touch "$MARKER_FILE"
        exit 0
    fi
fi

AUTH="Authorization: Bearer $TOKEN"

# Install tool: computer_use_tools.py
echo "[init] Installing Computer Use tool..."
TOOL_CODE=$(cat /app/init/tools/computer_use_tools.py)
TOOL_PAYLOAD=$(python3 -c "
import json, sys
code = open('/app/init/tools/computer_use_tools.py').read()
print(json.dumps({
    'id': 'ai_computer_use',
    'name': 'Computer Use Tools',
    'content': code,
    'meta': {'description': 'Execute commands, create files, and delegate tasks in isolated Docker containers.'}
}))
")

# Check if tool already exists
EXISTING=$(curl -sf "$WEBUI_URL/api/v1/tools/id/ai_computer_use" -H "$AUTH" 2>/dev/null || echo "")
if [ -n "$EXISTING" ] && echo "$EXISTING" | python3 -c "import sys,json; json.load(sys.stdin)['id']" 2>/dev/null; then
    # Update existing tool
    curl -sf -X POST "$WEBUI_URL/api/v1/tools/id/ai_computer_use/update" \
        -H "$AUTH" -H "Content-Type: application/json" \
        -d "$TOOL_PAYLOAD" >/dev/null
    echo "[init] Tool updated: ai_computer_use"
else
    # Create new tool
    curl -sf -X POST "$WEBUI_URL/api/v1/tools/create" \
        -H "$AUTH" -H "Content-Type: application/json" \
        -d "$TOOL_PAYLOAD" >/dev/null
    echo "[init] Tool created: ai_computer_use"
fi

# Set tool valves
echo "[init] Configuring tool valves..."
curl -sf -X POST "$WEBUI_URL/api/v1/tools/id/ai_computer_use/valves/update" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"FILE_SERVER_URL\": \"$MCP_SERVER_URL\", \"MCP_API_KEY\": \"$MCP_API_KEY\", \"DEBUG_LOGGING\": false}" >/dev/null
echo "[init] Valves set: FILE_SERVER_URL=$MCP_SERVER_URL"

# Make tool public-read so non-admin users can see & call it.
# Open WebUI's UI "Public" toggle writes BOTH group:* and user:* wildcards — we mirror
# that exactly. Without these grants, only the admin who created the tool sees it, so
# a failure here must block the marker file — otherwise the next restart skips init
# and the tool stays admin-only forever.
INIT_FAILED=0
if curl -sf -X POST "$WEBUI_URL/api/v1/tools/id/ai_computer_use/access/update" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d '{"access_grants":[
           {"principal_type":"group","principal_id":"*","permission":"read"},
           {"principal_type":"user","principal_id":"*","permission":"read"}
         ]}' >/dev/null 2>&1; then
    echo "[init] Tool marked public (all users + all groups, read)."
else
    echo "[init] ERROR: Could not set tool public access — tool will remain admin-only. Init will retry on next restart."
    INIT_FAILED=1
fi

# Install function: computer_link_filter.py
echo "[init] Installing Computer Use filter..."
FUNC_PAYLOAD=$(python3 -c "
import json
code = open('/app/init/functions/computer_link_filter.py').read()
print(json.dumps({
    'id': 'computer_use_filter',
    'name': 'Computer Use Filter',
    'content': code,
    'meta': {'description': 'Injects system prompt with file URLs and adds archive download button.'}
}))
")

EXISTING_F=$(curl -sf "$WEBUI_URL/api/v1/functions/id/computer_use_filter" -H "$AUTH" 2>/dev/null || echo "")
if [ -n "$EXISTING_F" ] && echo "$EXISTING_F" | python3 -c "import sys,json; json.load(sys.stdin)['id']" 2>/dev/null; then
    curl -sf -X POST "$WEBUI_URL/api/v1/functions/id/computer_use_filter/update" \
        -H "$AUTH" -H "Content-Type: application/json" \
        -d "$FUNC_PAYLOAD" >/dev/null
    echo "[init] Function updated: computer_use_filter"
else
    curl -sf -X POST "$WEBUI_URL/api/v1/functions/create" \
        -H "$AUTH" -H "Content-Type: application/json" \
        -d "$FUNC_PAYLOAD" >/dev/null
    echo "[init] Function created: computer_use_filter"
fi

# Configure filter valves (FILE_SERVER_URL for links in chat)
echo "[init] Configuring filter valves..."
curl -sf -X POST "$WEBUI_URL/api/v1/functions/id/computer_use_filter/valves/update" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"FILE_SERVER_URL\": \"$MCP_SERVER_EXTERNAL_URL\", \"ARCHIVE_BUTTON\": \"on\", \"INJECT_SYSTEM_PROMPT\": true}" >/dev/null 2>&1 || true
echo "[init] Filter valves set: FILE_SERVER_URL=$MCP_SERVER_EXTERNAL_URL (external/browser URL)"

# Enable filter (is_active=True) and mark it global (is_global=True).
# Open WebUI v0.8.12 has TWO separate endpoints: /toggle flips is_active,
# /toggle/global flips is_global. Active-but-not-global is silently inert —
# the filter loads but is never applied to chats. Query state first and only
# flip when needed so the script stays idempotent on re-runs.
FILTER_STATE=$(curl -sf "$WEBUI_URL/api/v1/functions/id/computer_use_filter" -H "$AUTH" 2>/dev/null || echo "{}")
IS_ACTIVE=$(echo "$FILTER_STATE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('is_active',False))" 2>/dev/null || echo "False")
IS_GLOBAL=$(echo "$FILTER_STATE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('is_global',False))" 2>/dev/null || echo "False")

if [ "$IS_ACTIVE" != "True" ]; then
    if curl -sf -X POST "$WEBUI_URL/api/v1/functions/id/computer_use_filter/toggle" \
        -H "$AUTH" >/dev/null 2>&1; then
        echo "[init] Filter activated."
    else
        echo "[init] ERROR: Could not activate filter — it will stay disabled until the next successful init. Init will retry on next restart."
        INIT_FAILED=1
    fi
else
    echo "[init] Filter already active."
fi

if [ "$IS_GLOBAL" != "True" ]; then
    if curl -sf -X POST "$WEBUI_URL/api/v1/functions/id/computer_use_filter/toggle/global" \
        -H "$AUTH" >/dev/null 2>&1; then
        echo "[init] Filter marked global (applies to all chats)."
    else
        echo "[init] ERROR: Could not mark filter global — it is active but won't apply to chats. Init will retry on next restart."
        INIT_FAILED=1
    fi
else
    echo "[init] Filter already global."
fi

# Set global DEFAULT_MODEL_PARAMS so every model uses Native Function Calling + streaming
# without per-model Advanced Params clicks. The old /api/v1/configs/models/default/update
# endpoint does not exist in Open WebUI v0.8.12 (returns 405) — use POST /api/v1/configs/models
# which takes the full ModelsConfigForm and merges DEFAULT_MODEL_PARAMS. We preserve
# existing fields so we don't clobber DEFAULT_MODELS / DEFAULT_MODEL_METADATA.
echo "[init] Ensuring DEFAULT_MODEL_PARAMS has native function calling + streaming..."
# Fetch current config; pipe its body into Python via stdin so arbitrary content
# (quotes, newlines, triple-quote sequences) cannot break the interpolation.
# Use direct assignment, not setdefault — any prior value for these two fields
# must be overwritten so our "params enforced" log is truthful.
MODELS_CFG=$(curl -sf "$WEBUI_URL/api/v1/configs/models" -H "$AUTH" 2>/dev/null || echo "{}")
MERGED_CFG=$(printf '%s' "$MODELS_CFG" | python3 -c "
import json, sys
raw = sys.stdin.read() or '{}'
cfg = json.loads(raw)
params = cfg.get('DEFAULT_MODEL_PARAMS') or {}
params['function_calling'] = 'native'
params['stream_response'] = True
cfg['DEFAULT_MODEL_PARAMS'] = params
cfg.setdefault('DEFAULT_MODELS', cfg.get('DEFAULT_MODELS') or '')
cfg.setdefault('DEFAULT_PINNED_MODELS', cfg.get('DEFAULT_PINNED_MODELS') or '')
cfg.setdefault('MODEL_ORDER_LIST', cfg.get('MODEL_ORDER_LIST') or [])
cfg.setdefault('DEFAULT_MODEL_METADATA', cfg.get('DEFAULT_MODEL_METADATA') or {})
print(json.dumps(cfg))
" 2>&1) || MERGED_CFG=""

if [ -z "$MERGED_CFG" ] || printf '%s' "$MERGED_CFG" | grep -q '^Traceback'; then
    echo "[init] WARNING: Could not merge DEFAULT_MODEL_PARAMS (Python parse failed)."
    if [ -n "$MERGED_CFG" ]; then
        printf '[init]   %s\n' "$MERGED_CFG" | head -5
    fi
elif curl -sf -X POST "$WEBUI_URL/api/v1/configs/models" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "$MERGED_CFG" >/dev/null 2>&1; then
    echo "[init] DEFAULT_MODEL_PARAMS set (function_calling=native, stream_response=true)."
else
    echo "[init] WARNING: Could not POST DEFAULT_MODEL_PARAMS (endpoint may differ on this Open WebUI version)."
fi

# Also try setting via workspace model (fallback for v0.8.11–0.8.12)
# Get first available model and create a workspace model with native FC
FIRST_MODEL=$(curl -sf "$WEBUI_URL/api/models" -H "$AUTH" 2>/dev/null | python3 -c "
import sys,json
data = json.load(sys.stdin).get('data',[])
for m in data:
    if m.get('id','') != 'arena-model':
        print(m['id'])
        break
" 2>/dev/null || echo "")

if [ -n "$FIRST_MODEL" ]; then
    echo "[init] Creating workspace model for $FIRST_MODEL with native FC..."
    MODEL_PAYLOAD=$(python3 -c "
import json
model_id = '$FIRST_MODEL'
safe_id = model_id.replace('/', '-')
print(json.dumps({
    'id': safe_id,
    'name': model_id.split('/')[-1] + ' (Computer Use)',
    'base_model_id': model_id,
    'meta': {
        'description': 'Model with Computer Use tools enabled and Native Function Calling',
        'toolIds': ['ai_computer_use'],
        'filterIds': ['computer_use_filter']
    },
    'params': {
        'function_calling': 'native',
        'stream_response': True
    }
}))
")
    curl -sf -X POST "$WEBUI_URL/api/v1/models/create" \
        -H "$AUTH" -H "Content-Type: application/json" \
        -d "$MODEL_PAYLOAD" >/dev/null 2>&1 && \
        echo "[init] Workspace model created: $FIRST_MODEL (Computer Use)" || \
        echo "[init] Workspace model creation skipped (may already exist)"
fi

# Mark as initialized — only if every required step succeeded. If INIT_FAILED=1,
# leave the marker off so the next container start retries the failed steps
# (public-access grant, filter toggle, filter global). Without this guard a
# transient failure would be baked in forever.
if [ "$INIT_FAILED" = "0" ]; then
    touch "$MARKER_FILE"
    echo "[init] Done! Open WebUI is ready with Computer Use."
else
    echo "[init] Done with errors — marker NOT written, init will re-run on next restart to retry the failed steps."
fi
echo "[init] Login: $ADMIN_EMAIL / $ADMIN_PASSWORD"
