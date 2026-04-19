# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Shared helpers for listing + reading files under a chat's uploads directory.

Used by:
  - GET /api/uploads/{chat_id}/list (existing HTTP endpoint).
  - sync_chat_resources / the @mcp.resource handler in mcp_resources.py
    (Tier 6 native MCP surface).

Traversal protection reuses security.safe_path / security.sanitize_chat_id —
no new security logic.
"""

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from security import safe_path, sanitize_chat_id


# Module-level so tests can patch / so app.py re-uses the same value.
BASE_DATA_DIR = Path(os.getenv("BASE_DATA_DIR", "/data"))


@dataclass(frozen=True)
class UploadEntry:
    name: str          # basename — display label
    rel_path: str      # relative to the uploads dir; may contain "/"
    size: int
    modified: float    # st_mtime
    mime_type: str


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def list_chat_uploads(chat_id: str) -> list[UploadEntry]:
    """List files under BASE_DATA_DIR/{chat_id}/uploads/ recursively.

    Returns [] if the directory doesn't exist (newly-created chat).
    Sorted by modification time, newest first — matches the HTTP endpoint's
    existing behavior (app.py:404).
    """
    chat_id = sanitize_chat_id(chat_id)
    uploads_dir = safe_path(BASE_DATA_DIR, chat_id, "uploads")
    if not uploads_dir.exists():
        return []
    entries: list[UploadEntry] = []
    for fp in uploads_dir.rglob("*"):
        if not fp.is_file():
            continue
        rel = fp.relative_to(uploads_dir)
        st = fp.stat()
        entries.append(UploadEntry(
            name=fp.name,
            rel_path=str(rel),
            size=st.st_size,
            modified=st.st_mtime,
            mime_type=_guess_mime(fp),
        ))
    entries.sort(key=lambda e: e.modified, reverse=True)
    return entries


def read_chat_upload(chat_id: str, rel_path: str) -> tuple[bytes, str]:
    """Read a single uploaded file. Returns (bytes, mime_type).

    rel_path is whatever list_chat_uploads reported (may contain "/").
    safe_path enforces traversal protection — no `..`, no absolute paths.
    """
    chat_id = sanitize_chat_id(chat_id)
    uploads_dir = safe_path(BASE_DATA_DIR, chat_id, "uploads")
    # safe_path handles multi-segment join with traversal protection.
    file_path = safe_path(uploads_dir, rel_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"No such upload: {chat_id}/{rel_path}")
    return file_path.read_bytes(), _guess_mime(file_path)
