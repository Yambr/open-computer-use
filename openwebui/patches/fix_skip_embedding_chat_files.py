#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
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

Target: Open WebUI 0.11.0
"""

import os
import sys

_PATCH_TARGET_OVERRIDE = os.environ.get("_PATCH_TARGET_OVERRIDE", "")
RETRIEVAL_PATH = _PATCH_TARGET_OVERRIDE or "/app/backend/open_webui/routers/retrieval.py"

PATCH_MARKER = "skip_processing_chat_files"
NEW_PATCH_MARKER = "FIX_SKIP_EMBEDDING_CHAT_FILES"

# === Patch 1: early return for regular uploads ===
# v0.8.11-0.9.2 uses single quotes: f'file-{file.id}'
# v0.9.5: added `else: await _validate_collection_access(...)` between the two if-blocks.

SEARCH_PATTERN_1 = """            if collection_name is None:
                collection_name = f'file-{file.id}'
            else:
                await _validate_collection_access([collection_name], user, access_type='write')

            if form_data.content:"""

REPLACE_PATTERN_1 = """            if collection_name is None:
                collection_name = f'file-{file.id}'
            else:
                await _validate_collection_access([collection_name], user, access_type='write')

            # PATCH: skip_processing_chat_files -- skip extraction + embedding; FIX_SKIP_EMBEDDING_CHAT_FILES
            # for large files (> 1 MB) during regular uploads (not KB).
            # Small files are processed as before (full context, RAG work).
            # When adding to KB (collection_name is set), processing works normally.
            _file_size = file.meta.get('size', 0)
            if not form_data.collection_name and not form_data.content and _file_size > 1_000_000:
                log.info(f'skip_processing_chat_files: skipping extraction for large file {file.filename} ({_file_size} bytes)')
                # Files.update_file_data_by_id was sync in v0.8.x, async since v0.9.x.
                # process_file() is async, so await is required — otherwise the coroutine
                # is dropped, the DB status stays 'pending', and the frontend polls
                # forever (see issue #96).
                await Files.update_file_data_by_id(file.id, {
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
                        # Storage.get_file is sync I/O; offload to a thread so the
                        # async process_file handler doesn't block the OWUI event
                        # loop while the file is read from the storage backend.
                        _fb_path = await asyncio.to_thread(Storage.get_file, file.path)
                        _fb_loader_config = await get_loader_config()
                        _fb_loader = build_loader_from_config(request, _fb_loader_config)
                        _fb_loader.user = user
                        _fb_loader.metadata = {
                            'file_id': file.id,
                            'file_name': file.filename,
                            'file_content_type': file.meta.get('content_type'),
                        }
                        # aload() is upstream's async wrapper: the underlying load is
                        # sync and CPU/IO-bound (PyMuPDF, Unstructured, Tika, etc.) and
                        # takes minutes on large files, so it offloads via
                        # asyncio.to_thread and keeps the event loop responsive.
                        docs = await _fb_loader.aload(
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
