#!/bin/bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
# Open WebUI initialization script
#
# Waits for Open WebUI to be ready, then installs tools, functions, and
# configures Valves from env. Guarded by a marker file — runs once, skips on
# subsequent container starts so user edits in the Open WebUI admin UI are
# never clobbered on restart.
#
# Valves are env-seeded on FIRST boot only. The only env that propagates into
# Valves is ORCHESTRATOR_URL (internal URL, consumed by both the tool and the
# filter). PUBLIC_BASE_URL lives on the computer-use-server container and
# requires a server restart, not a Valve re-seed. To force a Valve re-seed
# (e.g. after changing ORCHESTRATOR_URL in .env), delete the marker file and
# restart this container:
#
#   docker compose -f docker-compose.webui.yml exec open-webui \
#       rm /app/backend/data/.computer-use-initialized
#   docker compose -f docker-compose.webui.yml restart open-webui

set -euo pipefail

WEBUI_URL="${WEBUI_URL:-http://localhost:8080}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@open-computer-use.dev}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
ADMIN_NAME="${ADMIN_NAME:-Admin}"
# ORCHESTRATOR_URL: internal URL of computer-use-server, reachable from inside
# the open-webui container. Seeded into both Tool and Filter Valves. The public
# URL (browser-facing) is NOT set here — it lives only on the server as the
# PUBLIC_BASE_URL env var and is delivered to the filter via response header.
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://computer-use-server:8081}"
MCP_API_KEY="${MCP_API_KEY:-}"
# OCU_FILESYSTEM_ID: the BASE attested storage scope chat attachments are written
# under (X-OCU-Filesystem-Id). Compose-driven so the deploy pins one base; with
# control's -derive-chat-scope on, the tool resolves a per-chat "<base>-<hex>"
# scope from the status verb and writes under that, keeping the base available.
# Seeded into the Tool Valve so the base is not a dead code-default (D5).
OCU_FILESYSTEM_ID="${OCU_FILESYSTEM_ID:-fs-fleet}"
# OCU_DOWNLOAD_BASE_URL: browser-facing base of the File Pane origin that serves
# /download/{scope}/{filename} (#191, ADR-0034, shape per ADR-0035). The filter's
# outlet rewrites the model's [[ocu-download:NAME]] markers into a link under this
# base; the download authorizes on the same attested pane session (SSO), so this
# must be the SAME origin the pane is embedded under - a different spelling of the
# same address (127.0.0.1 vs localhost) is a different cookie jar and answers 401.
# On the stand the pane is on :3000; a real deploy sets the customer pane origin.
# Empty -> markers degrade to the bare filename (broken links are worse than none).
OCU_DOWNLOAD_BASE_URL="${OCU_DOWNLOAD_BASE_URL:-http://localhost:3000}"
MARKER_FILE="/app/backend/data/.computer-use-initialized"

# Sanity checks — run EVERY start (before marker-gate), so stale-default
# warnings resurface on each restart until the user fixes them.
if [[ "$ADMIN_PASSWORD" == "admin" || "$ADMIN_PASSWORD" == "change-me" ]]; then
    echo "[init] WARNING: ADMIN_PASSWORD is still the default (\"$ADMIN_PASSWORD\") — change it for anything beyond local dev."
fi
if [[ -z "$MCP_API_KEY" ]]; then
    echo "[init] WARNING: MCP_API_KEY is empty — /mcp endpoints accept any caller. Fine for local dev, unsafe for public deploys."
fi

# Skip if already initialized
if [ -f "$MARKER_FILE" ]; then
    echo "[init] Already initialized, skipping."
    echo "[init] To re-seed Valves from env, delete $MARKER_FILE and restart the container."

    # One exception, and it is narrow on purpose. The marker exists so a restart
    # cannot overwrite valves an operator edited in the admin UI, and that stays
    # true: this only FILLS a valve that is absent or empty, and only the two the
    # per-chat download link needs. It never overwrites a value that is set.
    #
    # Without it, upgrading an existing deployment leaves RESOLVE_SCOPE_URL unset,
    # the filter falls back to the base scope, and every chat download link
    # renders its page and returns no bytes — a failure that reads as success.
    # A version of this guard that required deleting the marker would leave that
    # state one forgotten step away.
    if [ -n "${OCU_RESOLVE_SCOPE_URL:-}" ]; then
        for i in $(seq 1 30); do
            curl -sf "$WEBUI_URL/health" >/dev/null 2>&1 && break
            sleep 2
        done
        RTOKEN=$(curl -sf "$WEBUI_URL/api/v1/auths/signin" -H "Content-Type: application/json" \
            -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" 2>/dev/null \
            | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])" 2>/dev/null || echo "")
        if [ -z "$RTOKEN" ]; then
            echo "[init] Could not sign in to reconcile the resolve-scope valves; leaving them as they are."
            exit 0
        fi
        RBEARER="${OCU_RESOLVE_SCOPE_BEARER:-}"
        if [ -n "${OCU_RESOLVE_SCOPE_BEARER_FILE:-}" ] && [ -r "${OCU_RESOLVE_SCOPE_BEARER_FILE}" ]; then
            RBEARER="$(tr -d '\r\n' < "$OCU_RESOLVE_SCOPE_BEARER_FILE")"
        fi
        CURRENT=$(curl -sf "$WEBUI_URL/api/v1/functions/id/computer_use_filter/valves" \
            -H "Authorization: Bearer $RTOKEN" 2>/dev/null || echo "")
        MERGED=$(printf '%s' "$CURRENT" | OCU_R_URL="${OCU_RESOLVE_SCOPE_URL:-}" OCU_R_BEARER="$RBEARER" python3 -c '
import json, os, sys
try:
    v = json.load(sys.stdin)
except Exception:
    sys.exit(1)
changed = False
for key, val in (("RESOLVE_SCOPE_URL", os.environ["OCU_R_URL"]),
                 ("RESOLVE_SCOPE_BEARER", os.environ["OCU_R_BEARER"])):
    if not v.get(key) and val:
        v[key] = val
        changed = True
if not changed:
    sys.exit(2)  # already set — leave the operator every value they chose
json.dump(v, sys.stdout)
' 2>/dev/null) && {
            if curl -sf -X POST "$WEBUI_URL/api/v1/functions/id/computer_use_filter/valves/update" \
                -H "Authorization: Bearer $RTOKEN" -H "Content-Type: application/json" \
                -d "$MERGED" >/dev/null 2>&1; then
                echo "[init] Filled the absent resolve-scope valves (RESOLVE_SCOPE_URL=${OCU_RESOLVE_SCOPE_URL:-}); per-chat download links stay correct across this upgrade."
            else
                echo "[init] WARNING: could not write the resolve-scope valves; chat download links will use the base scope."
            fi
        }
    fi
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
    -d "{\"ORCHESTRATOR_URL\": \"$ORCHESTRATOR_URL\", \"MCP_API_KEY\": \"$MCP_API_KEY\", \"OCU_FILESYSTEM_ID\": \"$OCU_FILESYSTEM_ID\", \"DEBUG_LOGGING\": false}" >/dev/null
echo "[init] Tool valves set: ORCHESTRATOR_URL=$ORCHESTRATOR_URL OCU_FILESYSTEM_ID=$OCU_FILESYSTEM_ID"

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

# Configure filter valves. ORCHESTRATOR_URL is the internal URL used for
# server→server fetch of /system-prompt. In next/v1 there is no orchestrator
# prompt service (#191, ADR-0034): the system prompt is config-baked into
# DEFAULT_MODEL_PARAMS.system (below), so INJECT_SYSTEM_PROMPT is false — the
# dead fetch stays off. DOWNLOAD_BASE_URL is the browser-facing pane base the
# outlet mints [[ocu-download:NAME]] markers into, and DOWNLOAD_SCOPE is the
# {scope} segment of that link: the pane serves /download/{scope}/{filename} and
# binds the path scope against the session's filesystem_id claim, so the value
# here is the SAME OCU_FILESYSTEM_ID the portal mints into the embed token.
# ARCHIVE_BUTTON is off (the legacy archive link used the retired capability-URL
# cache).
#
# DOWNLOAD_SCOPE is the FALLBACK only. Where the deployment derives a per-chat
# scope, the pane session's filesystem_id is <base>-<hex> and differs per chat,
# so no single value here can be right for more than one of them: a link built
# from the base renders its download page and returns no bytes. The filter asks
# the session's owner instead, through the gateway's resolve_scope, and falls
# back to this value only when the answer is empty (no derivation configured).
# Seeding both valves here is what stops a later init run from dropping them and
# silently restoring the base-scope link.
OCU_RESOLVE_SCOPE_URL="${OCU_RESOLVE_SCOPE_URL:-}"
OCU_RESOLVE_SCOPE_BEARER="${OCU_RESOLVE_SCOPE_BEARER:-}"
if [ -n "${OCU_RESOLVE_SCOPE_BEARER_FILE:-}" ] && [ -r "${OCU_RESOLVE_SCOPE_BEARER_FILE}" ]; then
    # Prefer a path over an environment value: a container's environment is
    # readable by anything that can inspect it.
    OCU_RESOLVE_SCOPE_BEARER="$(tr -d '\r\n' < "$OCU_RESOLVE_SCOPE_BEARER_FILE")"
fi
if [ -n "$OCU_RESOLVE_SCOPE_URL" ] && [ -z "$OCU_RESOLVE_SCOPE_BEARER" ]; then
    echo "[init] WARNING: OCU_RESOLVE_SCOPE_URL is set but no bearer was supplied;" \
         "per-chat download links will degrade to plain filenames"
fi
# The valve write REPLACES the stored object, so every key the filter owns has to
# appear here. Listing only the ones this change cares about silently dropped
# PREVIEW_MODE and both label valves, and with no PREVIEW_MODE the outlet appends
# no preview link at all — the panel stops offering it and nothing says why.
OCU_PREVIEW_MODE="${OCU_PREVIEW_MODE:-button}"
OCU_PREVIEW_BUTTON_TEXT="${OCU_PREVIEW_BUTTON_TEXT:-🖥️ Open preview}"
OCU_ARCHIVE_BUTTON_TEXT="${OCU_ARCHIVE_BUTTON_TEXT:-📦 Download all files as archive}"
echo "[init] Configuring filter valves..."
if curl -sf -X POST "$WEBUI_URL/api/v1/functions/id/computer_use_filter/valves/update" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"ORCHESTRATOR_URL\": \"$ORCHESTRATOR_URL\", \"ARCHIVE_BUTTON\": \"off\", \"INJECT_SYSTEM_PROMPT\": false, \"DOWNLOAD_BASE_URL\": \"$OCU_DOWNLOAD_BASE_URL\", \"DOWNLOAD_SCOPE\": \"$OCU_FILESYSTEM_ID\", \"RESOLVE_SCOPE_URL\": \"$OCU_RESOLVE_SCOPE_URL\", \"RESOLVE_SCOPE_BEARER\": \"$OCU_RESOLVE_SCOPE_BEARER\", \"PREVIEW_MODE\": \"$OCU_PREVIEW_MODE\", \"PREVIEW_BUTTON_TEXT\": \"$OCU_PREVIEW_BUTTON_TEXT\", \"ARCHIVE_BUTTON_TEXT\": \"$OCU_ARCHIVE_BUTTON_TEXT\"}" >/dev/null 2>&1; then
    echo "[init] Filter valves set: ORCHESTRATOR_URL=$ORCHESTRATOR_URL DOWNLOAD_BASE_URL=$OCU_DOWNLOAD_BASE_URL DOWNLOAD_SCOPE=$OCU_FILESYSTEM_ID RESOLVE_SCOPE_URL=${OCU_RESOLVE_SCOPE_URL:-<unset>}"
else
    echo "[init] ERROR: Could not seed filter valves — ORCHESTRATOR_URL will fall back to the code default until the next successful init. Init will retry on next restart."
    INIT_FAILED=1
fi

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

# Model surface for the demo: keep ONLY the Qwen family + DeepSeek "flash"
# (owner directive) out of the ~350-model OpenRouter catalog, bind the Computer
# Use tool + native function-calling onto EVERY surviving model so any chat a
# user opens has the tool live (all Qwen/DeepSeek-flash models advertise
# function-calling), and default a fresh chat to DeepSeek flash.
#
# OCU_DEMO_ALLOW_REGEX selects the base models to keep (default: qwen* or a
# deepseek *flash*). OCU_DEMO_DEFAULT_MODEL is the fresh-chat default.
OCU_DEMO_ALLOW_REGEX="${OCU_DEMO_ALLOW_REGEX:-^qwen/|^deepseek/.*flash}"
OCU_DEMO_DEFAULT_MODEL="${OCU_DEMO_DEFAULT_MODEL:-deepseek/deepseek-v4-flash}"

echo "[init] Filtering model catalog to /$OCU_DEMO_ALLOW_REGEX/ and binding Computer Use + native FC to each..."
CATALOG=$(curl -sf "$WEBUI_URL/api/models" -H "$AUTH" 2>/dev/null || echo '{"data":[]}')

# 1) Restrict the OpenRouter connection's visible catalog to the allow-set via
#    OPENAI_API_CONFIGS[<idx>].model_ids (OpenWebUI hides everything else).
OAI_CFG=$(curl -sf "$WEBUI_URL/openai/config" -H "$AUTH" 2>/dev/null || echo "{}")
FILTER_PAYLOAD=$(printf '%s\n---SPLIT---\n%s' "$CATALOG" "$OAI_CFG" | python3 -c "
import sys, json, re
cat_raw, oai_raw = sys.stdin.read().split('---SPLIT---')
allow = re.compile('$OCU_DEMO_ALLOW_REGEX')
ids = [m['id'] for m in json.loads(cat_raw).get('data', []) if allow.search(m.get('id',''))]
oai = json.loads(oai_raw)
cfgs = oai.get('OPENAI_API_CONFIGS') or {}
# one OpenRouter connection at idx '0'; pin its visible model_ids to the allow-set
cfgs.setdefault('0', {})
cfgs['0']['model_ids'] = ids
oai['OPENAI_API_CONFIGS'] = cfgs
print(json.dumps({'kept': ids, 'oai': oai}))
" 2>/dev/null)
KEPT_IDS=$(printf '%s' "$FILTER_PAYLOAD" | python3 -c "import sys,json;print('\n'.join(json.load(sys.stdin)['kept']))" 2>/dev/null)
OAI_NEW=$(printf '%s' "$FILTER_PAYLOAD" | python3 -c "import sys,json;print(json.dumps(json.load(sys.stdin)['oai']))" 2>/dev/null)
if [ -n "$OAI_NEW" ]; then
    curl -sf -X POST "$WEBUI_URL/openai/config/update" \
        -H "$AUTH" -H "Content-Type: application/json" -d "$OAI_NEW" >/dev/null 2>&1 \
        && echo "[init] Catalog filtered to $(printf '%s' "$KEPT_IDS" | grep -c . ) models (Qwen + DeepSeek flash)." \
        || echo "[init] WARNING: catalog filter POST failed (endpoint may differ)."
fi

# 2) Bind Computer Use tool + native FC + the sandbox system prompt onto EVERY
#    surviving base model, so the tool is live and the model knows the filesystem
#    map in every chat regardless of which model the user picks.
#
#    The system prompt rides params.system on the model record. The
#    computer_use_filter's /system-prompt fetch degrades silently here: its
#    ORCHESTRATOR_URL points at the MCP gateway, which (correctly) serves no
#    such route - the gateway fronts tools/call only. Without params.system the
#    model gets ZERO path guidance and writes to read-only paths blind.
#
#    CRITICAL: base_model_id MUST be null (not the model's own id). Open WebUI's
#    get_all_models merge has two paths (utils/models.py): a workspace record
#    with base_model_id=None is applied as a DIRECT OVERRIDE onto the base model
#    that shares its id (so meta.toolIds surfaces into the resolved catalog the
#    chat reads); a record whose base_model_id is set is treated as a DERIVED
#    model, and if its id already exists as a base model the merge hits
#    `continue` and SKIPS it entirely — meta.toolIds never attaches and the tool
#    never reaches the model in chat. A self-referential base_model_id==id lands
#    on that skip path, which is why the tool was absent in a fresh default chat.
# The sandbox system prompt every bound model gets (params.system). It is a data
# artifact shipped next to this script (COPY system_prompt.txt in the Dockerfile)
# and read verbatim - it carries the skills-first protocol, the <available_skills>
# block, the filesystem map (uploads RO + outputs RW), the self-verify and
# file-sharing instructions. Kept out-of-line so its content never has to survive
# heredoc/JSON quoting and so the contract test can load the exact same bytes.
#
# Fail loud: if the file is missing, seeding a blank system prompt would leave
# every model with ZERO path guidance (the failure mode this whole step exists to
# prevent). Abort the run instead of shipping an empty prompt.
PROMPT_FILE="$(dirname "$0")/system_prompt.txt"
if [ ! -s "$PROMPT_FILE" ]; then
    echo "[init] FATAL: system prompt file missing or empty: $PROMPT_FILE" >&2
    echo "[init]        refusing to seed models with an empty params.system." >&2
    exit 1
fi
OCU_SYSTEM_PROMPT="$(cat "$PROMPT_FILE")"
export OCU_SYSTEM_PROMPT

if [ -n "$KEPT_IDS" ]; then
    printf '%s\n' "$KEPT_IDS" | while IFS= read -r model_id; do
        [ -z "$model_id" ] && continue
        MODEL_PAYLOAD=$(model_id="$model_id" python3 -c "
import json, os
mid = os.environ['model_id']
print(json.dumps({
    'id': mid,
    'name': mid,
    'base_model_id': None,
    'meta': {
        'description': 'Computer Use tools enabled (native function calling).',
        'toolIds': ['ai_computer_use'],
        'filterIds': ['computer_use_filter']
    },
    'params': {
        'function_calling': 'native',
        'stream_response': True,
        'system': os.environ.get('OCU_SYSTEM_PROMPT', '')
    },
    # Public read grants, mirroring the tool's own grants above. A seeded model
    # record with empty access_grants is dropped by get_filtered_models for any
    # non-admin user (they would see zero models), so grant read to all users
    # and groups — the model catalog is meant to be visible to everyone here.
    'access_grants': [
        {'principal_type': 'group', 'principal_id': '*', 'permission': 'read'},
        {'principal_type': 'user', 'principal_id': '*', 'permission': 'read'}
    ]
}))
")
        # create, or update if it already exists (idempotent re-seed). The create
        # endpoint rejects an already-registered id, so fall through to update.
        curl -sf -X POST "$WEBUI_URL/api/v1/models/create" \
            -H "$AUTH" -H "Content-Type: application/json" -d "$MODEL_PAYLOAD" >/dev/null 2>&1 \
        || curl -sf -X POST "$WEBUI_URL/api/v1/models/model/update?id=$model_id" \
            -H "$AUTH" -H "Content-Type: application/json" -d "$MODEL_PAYLOAD" >/dev/null 2>&1
    done
    echo "[init] Computer Use tool + native FC bound to every kept model."

    # 2b) Repair LEGACY workspace records. Earlier seeder generations left
    #     derived records (unique id, base_model_id set — e.g. an "ocu-*" alias
    #     of a kept base). The loop above never touches them because it walks
    #     base-catalog ids only, so such a record keeps stale params forever —
    #     and if it is the fresh-chat default, every new chat runs with NO
    #     system prompt while all directly-seeded models carry one.
    #
    #     The list endpoint returns the RESOLVED catalog, which reports
    #     base_model_id as null even for derived records — only the raw
    #     single-record GET (/api/v1/models/model?id=) exposes the stored
    #     base_model_id. So: take list ids outside the kept set, fetch each
    #     raw record, and re-bind tool + FC + prompt onto every record whose
    #     base points into the kept set, preserving its id/base pair.
    WORKSPACE=$(curl -sf "$WEBUI_URL/api/v1/models" -H "$AUTH" 2>/dev/null || echo '[]')
    CANDIDATE_IDS=$(printf '%s\n---SPLIT---\n%s' "$WORKSPACE" "$KEPT_IDS" | python3 -c "
import sys, json
raw, kept_raw = sys.stdin.read().split('---SPLIT---')
kept = set(l.strip() for l in kept_raw.splitlines() if l.strip())
recs = json.loads(raw)
if isinstance(recs, dict): recs = recs.get('data', [])
for r in recs:
    if r.get('id') and r['id'] not in kept:
        print(r['id'])
" 2>/dev/null)
    if [ -n "$CANDIDATE_IDS" ]; then
        printf '%s\n' "$CANDIDATE_IDS" | while IFS= read -r legacy_id; do
            [ -z "$legacy_id" ] && continue
            ENC_ID=$(legacy_id="$legacy_id" python3 -c "import os,urllib.parse;print(urllib.parse.quote(os.environ['legacy_id'], safe=''))")
            RAW_RECORD=$(curl -sf "$WEBUI_URL/api/v1/models/model?id=$ENC_ID" -H "$AUTH" 2>/dev/null || echo '{}')
            legacy_base=$(printf '%s\n---SPLIT---\n%s' "$RAW_RECORD" "$KEPT_IDS" | python3 -c "
import sys, json
raw, kept_raw = sys.stdin.read().split('---SPLIT---')
kept = set(l.strip() for l in kept_raw.splitlines() if l.strip())
base = (json.loads(raw) or {}).get('base_model_id')
print(base if base in kept else '')
" 2>/dev/null)
            [ -z "$legacy_base" ] && continue
            LEGACY_PAYLOAD=$(model_id="$legacy_id" base_id="$legacy_base" python3 -c "
import json, os
print(json.dumps({
    'id': os.environ['model_id'],
    'name': os.environ['model_id'],
    'base_model_id': os.environ['base_id'],
    'meta': {
        'description': 'Computer Use tools enabled (native function calling).',
        'toolIds': ['ai_computer_use'],
        'filterIds': ['computer_use_filter']
    },
    'params': {
        'function_calling': 'native',
        'stream_response': True,
        'system': os.environ.get('OCU_SYSTEM_PROMPT', '')
    },
    'access_grants': [
        {'principal_type': 'group', 'principal_id': '*', 'permission': 'read'},
        {'principal_type': 'user', 'principal_id': '*', 'permission': 'read'}
    ]
}))
")
            curl -sf -X POST "$WEBUI_URL/api/v1/models/model/update?id=$ENC_ID" \
                -H "$AUTH" -H "Content-Type: application/json" -d "$LEGACY_PAYLOAD" >/dev/null 2>&1 \
                && echo "[init] Repaired legacy model record: $legacy_id (base $legacy_base)." \
                || echo "[init] WARNING: could not repair legacy record $legacy_id."
        done
    fi
fi

# 3) Default a fresh chat to DeepSeek flash (with the tool already bound).
DEFAULT_CFG=$(curl -sf "$WEBUI_URL/api/v1/configs/models" -H "$AUTH" 2>/dev/null || echo "{}")
DEFAULT_NEW=$(DM="$OCU_DEMO_DEFAULT_MODEL" printf '%s' "$DEFAULT_CFG" | DM="$OCU_DEMO_DEFAULT_MODEL" python3 -c "
import sys, json, os
cfg = json.loads(sys.stdin.read() or '{}')
cfg['DEFAULT_MODELS'] = os.environ['DM']
print(json.dumps(cfg))
" 2>/dev/null)
if [ -n "$DEFAULT_NEW" ]; then
    curl -sf -X POST "$WEBUI_URL/api/v1/configs/models" \
        -H "$AUTH" -H "Content-Type: application/json" -d "$DEFAULT_NEW" >/dev/null 2>&1 \
        && echo "[init] Default model set to $OCU_DEMO_DEFAULT_MODEL." \
        || echo "[init] WARNING: could not set DEFAULT_MODELS."
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
