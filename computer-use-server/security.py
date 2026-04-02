"""Centralized security utilities for path validation and input sanitization."""
import os
from pathlib import Path

from fastapi import HTTPException


def sanitize_chat_id(chat_id: str) -> str:
    """Validate chat_id — reject path traversal characters.

    chat_id can be any string (UUID, "default", etc.),
    but must NOT contain: '..', '/', '\\', null-bytes.
    """
    normalized = chat_id.strip().lower()
    if (
        not normalized
        or ".." in normalized
        or "/" in normalized
        or "\\" in normalized
        or "\x00" in normalized
    ):
        raise HTTPException(status_code=400, detail="Invalid chat_id")
    return normalized


def safe_path(base_dir: Path, *segments: str) -> Path:
    """Construct a path from untrusted segments and verify it stays within base_dir.

    Uses os.path.realpath + startswith — pattern natively recognized by CodeQL
    as a containment check barrier for py/path-injection (pathlib Path.resolve
    is not modeled as a sanitizer by CodeQL).
    Resolves symlinks via realpath to prevent symlink escape attacks.
    Raises HTTPException(403) on traversal attempt.
    Returns the resolved absolute path.
    """
    constructed = str(base_dir)
    for seg in segments:
        constructed = os.path.join(constructed, seg)

    resolved_str = os.path.realpath(constructed)
    base_str = os.path.realpath(str(base_dir))

    # os.sep suffix prevents prefix collision: /data should NOT match /data-evil
    if resolved_str != base_str and not resolved_str.startswith(base_str + os.sep):
        raise HTTPException(
            status_code=403, detail="Access denied: path traversal detected"
        )
    return Path(resolved_str)
