"""Centralized security utilities for path validation and input sanitization."""
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

    Uses resolve() + is_relative_to() for robust traversal protection.
    Raises HTTPException(403) on traversal attempt.
    Returns the resolved absolute path.
    """
    constructed = base_dir
    for seg in segments:
        constructed = constructed / seg
    resolved = constructed.resolve()
    base_resolved = base_dir.resolve()
    if not resolved.is_relative_to(base_resolved):
        raise HTTPException(
            status_code=403, detail="Access denied: path traversal detected"
        )
    return resolved
