#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Patch for Open WebUI: skip all processing (extraction + embedding) for regular file uploads

Problem: When a file is uploaded to chat, full processing occurs:
extraction (UnstructuredExcelLoader, MinerU, etc.) + embedding (chunking + vectorization).
This takes minutes for large files. With native FC, file search
is not triggered anyway, making the processing useless.

Solution:
1. Early return from process_file() for LARGE (> 1 MB) regular uploads.
   The file is simply saved and marked as completed. Small files are processed as before.
2. KB fallback: when a file without extraction is added to a KB, extract from the file
   instead of falling back to empty file.data.content.

When adding a file to a knowledge base (collection_name is set), full processing works.

Target: Open WebUI 0.9.2
"""

import os
import sys

_PATCH_TARGET_OVERRIDE = os.environ.get("_PATCH_TARGET_OVERRIDE", "")
RETRIEVAL_PATH = _PATCH_TARGET_OVERRIDE or "/app/backend/open_webui/routers/retrieval.py"

PATCH_MARKER = "skip_processing_chat_files"
NEW_PATCH_MARKER = "FIX_SKIP_EMBEDDING_CHAT_FILES"

# === Patch 1: early return for regular uploads ===
# v0.8.11-0.9.2 uses single quotes: f'file-{file.id}'

SEARCH_PATTERN_1 = """            if collection_name is None:
                collection_name = f'file-{file.id}'

            if form_data.content:"""

REPLACE_PATTERN_1 = """            if collection_name is None:
                collection_name = f'file-{file.id}'

            # PATCH: skip_processing_chat_files -- skip extraction + embedding; FIX_SKIP_EMBEDDING_CHAT_FILES
            # for large files (> 1 MB) during regular uploads (not KB).
            # Small files are processed as before (full context, RAG work).
            # When adding to KB (collection_name is set), processing works normally.
            _file_size = file.meta.get('size', 0)
            if not form_data.collection_name and not form_data.content and _file_size > 1_000_000:
                log.info(f'skip_processing_chat_files: skipping extraction for large file {file.filename} ({_file_size} bytes)')
                Files.update_file_data_by_id(file.id, {
                    'status': 'completed',
                    'status_description': 'File is too large for automatic processing. Enable the AI Computer Use tool to work with this file.',
                }, db=db)
                return {
                    'status': True,
                    'collection_name': None,
                    'filename': file.filename,
                    'content': '',
                }

            if form_data.content:"""

# === Patch 2: KB fallback -- extract from file when content is empty ===
# When a file was uploaded without extraction (Patch 1) and then added to a KB,
# there are no embeddings and no content. Need to extract from the file.
# v0.8.11-0.9.2: single quotes, text_content = file.data.get('content', '')

SEARCH_PATTERN_2 = """                else:
                    docs = [
                        Document(
                            page_content=file.data.get('content', ''),
                            metadata={
                                **file.meta,
                                'name': file.filename,
                                'created_by': file.user_id,
                                'file_id': file.id,
                                'source': file.filename,
                            },
                        )
                    ]

                text_content = file.data.get('content', '')"""

REPLACE_PATTERN_2 = """                else:
                    # PATCH: skip_processing_chat_files — KB fallback; FIX_SKIP_EMBEDDING_CHAT_FILES
                    # If file was uploaded without extraction (content empty),
                    # do extraction from file instead of using empty content.
                    _fb_content = file.data.get('content', '')
                    if not _fb_content and file.path:
                        log.info(f'KB fallback: extracting content from {file.filename} (was uploaded without extraction)')
                        _fb_path = Storage.get_file(file.path)
                        _fb_loader = Loader(
                            engine=request.app.state.config.CONTENT_EXTRACTION_ENGINE,
                            user=user,
                            DATALAB_MARKER_API_KEY=request.app.state.config.DATALAB_MARKER_API_KEY,
                            DATALAB_MARKER_API_BASE_URL=request.app.state.config.DATALAB_MARKER_API_BASE_URL,
                            DATALAB_MARKER_ADDITIONAL_CONFIG=request.app.state.config.DATALAB_MARKER_ADDITIONAL_CONFIG,
                            DATALAB_MARKER_SKIP_CACHE=request.app.state.config.DATALAB_MARKER_SKIP_CACHE,
                            DATALAB_MARKER_FORCE_OCR=request.app.state.config.DATALAB_MARKER_FORCE_OCR,
                            DATALAB_MARKER_PAGINATE=request.app.state.config.DATALAB_MARKER_PAGINATE,
                            DATALAB_MARKER_STRIP_EXISTING_OCR=request.app.state.config.DATALAB_MARKER_STRIP_EXISTING_OCR,
                            DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION=request.app.state.config.DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION,
                            DATALAB_MARKER_FORMAT_LINES=request.app.state.config.DATALAB_MARKER_FORMAT_LINES,
                            DATALAB_MARKER_USE_LLM=request.app.state.config.DATALAB_MARKER_USE_LLM,
                            DATALAB_MARKER_OUTPUT_FORMAT=request.app.state.config.DATALAB_MARKER_OUTPUT_FORMAT,
                            EXTERNAL_DOCUMENT_LOADER_URL=request.app.state.config.EXTERNAL_DOCUMENT_LOADER_URL,
                            EXTERNAL_DOCUMENT_LOADER_API_KEY=request.app.state.config.EXTERNAL_DOCUMENT_LOADER_API_KEY,
                            TIKA_SERVER_URL=request.app.state.config.TIKA_SERVER_URL,
                            DOCLING_SERVER_URL=request.app.state.config.DOCLING_SERVER_URL,
                            DOCLING_API_KEY=request.app.state.config.DOCLING_API_KEY,
                            DOCLING_PARAMS=request.app.state.config.DOCLING_PARAMS,
                            PDF_EXTRACT_IMAGES=request.app.state.config.PDF_EXTRACT_IMAGES,
                            PDF_LOADER_MODE=request.app.state.config.PDF_LOADER_MODE,
                            DOCUMENT_INTELLIGENCE_ENDPOINT=request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT,
                            DOCUMENT_INTELLIGENCE_KEY=request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
                            DOCUMENT_INTELLIGENCE_MODEL=request.app.state.config.DOCUMENT_INTELLIGENCE_MODEL,
                            MISTRAL_OCR_API_BASE_URL=request.app.state.config.MISTRAL_OCR_API_BASE_URL,
                            MISTRAL_OCR_API_KEY=request.app.state.config.MISTRAL_OCR_API_KEY,
                            MINERU_API_MODE=request.app.state.config.MINERU_API_MODE,
                            MINERU_API_URL=request.app.state.config.MINERU_API_URL,
                            MINERU_API_KEY=request.app.state.config.MINERU_API_KEY,
                            MINERU_API_TIMEOUT=request.app.state.config.MINERU_API_TIMEOUT,
                            MINERU_PARAMS=request.app.state.config.MINERU_PARAMS,
                        )
                        docs = _fb_loader.load(
                            file.filename, file.meta.get('content_type'), _fb_path
                        )
                        docs = [
                            Document(
                                page_content=doc.page_content,
                                metadata={
                                    **filter_metadata(doc.metadata),
                                    'name': file.filename,
                                    'created_by': file.user_id,
                                    'file_id': file.id,
                                    'source': file.filename,
                                },
                            )
                            for doc in docs
                        ]
                    else:
                        docs = [
                            Document(
                                page_content=_fb_content,
                                metadata={
                                    **file.meta,
                                    'name': file.filename,
                                    'created_by': file.user_id,
                                    'file_id': file.id,
                                    'source': file.filename,
                                },
                            )
                        ]

                text_content = ' '.join([doc.page_content for doc in docs])"""


def apply_patch():
    if not os.path.exists(RETRIEVAL_PATH):
        print(
            f"ERROR: fix_skip_embedding_chat_files target file {RETRIEVAL_PATH} not found. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(RETRIEVAL_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if PATCH_MARKER in content or NEW_PATCH_MARKER in content:
        print(f"ALREADY PATCHED: {RETRIEVAL_PATH} contains {PATCH_MARKER}")
        return True

    # Patch 1: early return for regular uploads
    if SEARCH_PATTERN_1 not in content:
        print(
            f"ERROR: fix_skip_embedding_chat_files anchor 1 (collection_name / form_data.content "
            f"block) not found in {RETRIEVAL_PATH} — upstream may have refactored process_file. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)

    content = content.replace(SEARCH_PATTERN_1, REPLACE_PATTERN_1, 1)
    print("  Patch 1 applied: early return for standalone uploads")

    # Patch 2: KB fallback -- extract from file when content is empty (hard-fail on miss at v0.9.1+)
    if SEARCH_PATTERN_2 not in content:
        print(
            f"ERROR: fix_skip_embedding_chat_files anchor 2 (KB fallback else-branch) not found "
            f"in {RETRIEVAL_PATH} — without this, files uploaded via anchor 1 cannot be added "
            "to knowledge bases (data-corruption risk). Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)

    content = content.replace(SEARCH_PATTERN_2, REPLACE_PATTERN_2, 1)
    print("  Patch 2 applied: KB fallback extracts from file when content is empty")

    with open(RETRIEVAL_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("PATCHED: fix_skip_embedding_chat_files applied successfully.")
    print("  Large files (> 1 MB) in chat will skip processing (extraction + embedding)")
    print("  Small files (< 1 MB) in chat are processed normally")
    print("  KB file additions: always processed, fallback extraction if needed")
    return True


if __name__ == "__main__":
    print("Applying skip-processing-for-chat-files patch to Open WebUI...")
    success = apply_patch()
    sys.exit(0 if success else 1)
