# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
ARG OPENWEBUI_VERSION=0.9.5
FROM ghcr.io/open-webui/open-webui:${OPENWEBUI_VERSION}

# Copy all patches into the image
COPY patches/ /tmp/patches/

# Required: Auto-show artifacts panel when HTML code blocks are detected
RUN python3 /tmp/patches/fix_artifacts_auto_show.py

# Required: Error handling for tool loop — prevents UI hang on MCP/transport errors
RUN python3 /tmp/patches/fix_tool_loop_errors.py

# Required: Auto-detect file preview URLs in messages and show in artifacts panel
RUN python3 /tmp/patches/fix_preview_url_detection.py

# Optional: Truncate large MCP tool results to prevent context window exhaustion.
# Requires fix_tool_loop_errors.py to be applied first.
# Config: TOOL_RESULT_MAX_CHARS (default 50000), TOOL_RESULT_PREVIEW_CHARS (default 2000)
RUN python3 /tmp/patches/fix_large_tool_results.py

# Enabled backend patches:
#
# fix_large_tool_args: Truncates oversized tool call arguments in HTML attributes
# to prevent browser UI freeze on large tool outputs (>10KB).
RUN python3 /tmp/patches/fix_large_tool_args.py
#
# fix_attached_files_position: Moves file context to end of messages instead of
# prepend, improving prompt cache hit rates with large file attachments.
RUN python3 /tmp/patches/fix_attached_files_position.py
#
# fix_skip_embedding_chat_files: Skips expensive text extraction and embedding
# for large chat file uploads (>1MB), using knowledge base fallback instead.
RUN python3 /tmp/patches/fix_skip_embedding_chat_files.py
#
# fix_skip_rag_files_native_fc: Skips RAG pipeline for chat files when
# computer_use tool is enabled, avoiding unnecessary processing.
RUN python3 /tmp/patches/fix_skip_rag_files_native_fc.py

# The File Pane, in the chat, on the right. The pane's session cookie is minted
# on the pane's own origin by the portal's embed-token exchange; a user who only
# opens the chat never performs it, so a download link the model emitted answered
# 401 and no preview could appear. The panel embeds the portal, the portal embeds
# the pane as it already does, and the session exists because the pane is really
# running in the page. Point OCU_FILE_PANE_PORTAL_URL at the browser-facing
# portal origin -- it is a browser URL, not a service name.
ARG OCU_FILE_PANE_PORTAL_URL=http://localhost:3003
ARG OCU_FILE_PANE_WIDTH=420
RUN OCU_FILE_PANE_PORTAL_URL="${OCU_FILE_PANE_PORTAL_URL}" \
    OCU_FILE_PANE_WIDTH="${OCU_FILE_PANE_WIDTH}" \
    python3 /tmp/patches/add_file_pane_panel.py

# The shell carries every patch above, so it must not be served without freshness
# information: a browser then caches it heuristically and a returning visitor
# keeps the pre-patch shell. Measured: same URL, 15413 bytes fresh vs 11028 bytes
# from cache -- the panel was absent on / and present on /?anything.
RUN python3 /tmp/patches/revalidate_app_shell.py

RUN rm -rf /tmp/patches/

# Copy Computer Use tool, function, init script, and the system prompt into the
# image. system_prompt.txt sits next to init.sh (dirname "$0") so init.sh reads
# it and seeds it verbatim as every model's params.system.
COPY tools/ /app/init/tools/
COPY functions/ /app/init/functions/
COPY init.sh /app/init/init.sh
COPY system_prompt.txt /app/init/system_prompt.txt
RUN chmod +x /app/init/init.sh

# Wrap the original entrypoint to run init in the background after startup
RUN mv /app/backend/start.sh /app/backend/start-original.sh && \
    printf '#!/bin/bash\n# Run init script in background (waits for Open WebUI to be ready)\n/app/init/init.sh &\n# Start original Open WebUI\nexec /app/backend/start-original.sh\n' > /app/backend/start.sh && \
    chmod +x /app/backend/start.sh
