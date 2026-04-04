# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
ARG OPENWEBUI_VERSION=0.8.12
FROM ghcr.io/open-webui/open-webui:${OPENWEBUI_VERSION}

# Copy all patches into the image
COPY patches/ /tmp/patches/

# Required: Auto-show artifacts panel when HTML code blocks are detected
RUN python3 /tmp/patches/fix_artifacts_auto_show.py

# Required: Error handling for tool loop — prevents UI hang on MCP/transport errors
RUN python3 /tmp/patches/fix_tool_loop_errors.py

# Required: Auto-detect file preview URLs in messages and show in artifacts panel
ARG COMPUTER_USE_SERVER_URL=computer-use-server:8081
ENV COMPUTER_USE_SERVER_URL=${COMPUTER_USE_SERVER_URL}
RUN python3 /tmp/patches/fix_preview_url_detection.py

# Optional: Truncate large MCP tool results to prevent context window exhaustion.
# Requires fix_tool_loop_errors.py to be applied first.
# Config: TOOL_RESULT_MAX_CHARS (default 50000), TOOL_RESULT_PREVIEW_CHARS (default 2000)
RUN python3 /tmp/patches/fix_large_tool_results.py

# Optional patches below - uncomment if needed:
#
# fix_large_tool_args: Truncates oversized tool call arguments in HTML attributes
# to prevent browser UI freeze on large tool outputs (>10KB).
# RUN python3 /tmp/patches/fix_large_tool_args.py
#
# fix_attached_files_position: Moves file context to end of messages instead of
# prepend, improving prompt cache hit rates with large file attachments.
# RUN python3 /tmp/patches/fix_attached_files_position.py
#
# fix_skip_embedding_chat_files: Skips expensive text extraction and embedding
# for large chat file uploads (>1MB), using knowledge base fallback instead.
# RUN python3 /tmp/patches/fix_skip_embedding_chat_files.py
#
# fix_skip_rag_files_native_fc: Skips RAG pipeline for chat files when
# computer_use tool is enabled, avoiding unnecessary processing.
# RUN python3 /tmp/patches/fix_skip_rag_files_native_fc.py

RUN rm -rf /tmp/patches/

# Copy Computer Use tool, function, and init script into the image
COPY tools/ /app/init/tools/
COPY functions/ /app/init/functions/
COPY init.sh /app/init/init.sh
RUN chmod +x /app/init/init.sh

# Wrap the original entrypoint to run init in the background after startup
RUN mv /app/backend/start.sh /app/backend/start-original.sh && \
    printf '#!/bin/bash\n# Run init script in background (waits for Open WebUI to be ready)\n/app/init/init.sh &\n# Start original Open WebUI\nexec /app/backend/start-original.sh\n' > /app/backend/start.sh && \
    chmod +x /app/backend/start.sh
