"""Tests for security utilities: safe_path() and sanitize_chat_id()."""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "computer-use-server"))

from security import safe_path, sanitize_chat_id


class TestSafePath:
    """Tests for safe_path() — path traversal protection."""

    def test_normal_path(self, tmp_path):
        base = tmp_path / "data"
        base.mkdir()
        (base / "file.txt").touch()
        result = safe_path(base, "file.txt")
        assert result == (base / "file.txt").resolve()

    def test_subdirectory_path(self, tmp_path):
        base = tmp_path / "data"
        sub = base / "subdir"
        sub.mkdir(parents=True)
        (sub / "file.txt").touch()
        result = safe_path(base, "subdir", "file.txt")
        assert result == (sub / "file.txt").resolve()

    def test_traversal_dot_dot(self, tmp_path):
        base = tmp_path / "data"
        base.mkdir()
        with pytest.raises(HTTPException) as exc_info:
            safe_path(base, "..", "..", "etc", "passwd")
        assert exc_info.value.status_code == 403

    def test_traversal_in_segment(self, tmp_path):
        base = tmp_path / "data"
        base.mkdir()
        with pytest.raises(HTTPException) as exc_info:
            safe_path(base, "../../etc/passwd")
        assert exc_info.value.status_code == 403

    def test_absolute_path_injection(self, tmp_path):
        base = tmp_path / "data"
        base.mkdir()
        with pytest.raises(HTTPException) as exc_info:
            safe_path(base, "/etc/passwd")
        assert exc_info.value.status_code == 403

    def test_string_prefix_false_positive(self, tmp_path):
        """Base /data should NOT match /data-evil."""
        base = tmp_path / "data"
        base.mkdir()
        evil = tmp_path / "data-evil"
        evil.mkdir()
        (evil / "file.txt").touch()
        with pytest.raises(HTTPException) as exc_info:
            safe_path(base, "..", "data-evil", "file.txt")
        assert exc_info.value.status_code == 403

    def test_nonexistent_file_ok(self, tmp_path):
        """safe_path should work for files that don't exist yet (upload case)."""
        base = tmp_path / "data"
        base.mkdir()
        result = safe_path(base, "newfile.txt")
        assert result == (base / "newfile.txt").resolve()

    def test_symlink_escape(self, tmp_path):
        """Symlink pointing outside base should be rejected."""
        base = tmp_path / "data"
        base.mkdir()
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "key.txt").touch()
        (base / "link").symlink_to(secret)
        with pytest.raises(HTTPException) as exc_info:
            safe_path(base, "link", "key.txt")
        assert exc_info.value.status_code == 403


class TestSanitizeChatId:
    """Tests for sanitize_chat_id() — chat_id validation."""

    def test_valid_uuid(self):
        result = sanitize_chat_id("A1B2C3D4-E5F6-7890-ABCD-EF1234567890")
        assert result == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_default_string(self):
        assert sanitize_chat_id("default") == "default"

    def test_arbitrary_string(self):
        assert sanitize_chat_id("my-session-123") == "my-session-123"

    def test_traversal_dot_dot(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_chat_id("../../etc")
        assert exc_info.value.status_code == 400

    def test_slash(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_chat_id("abc/def")
        assert exc_info.value.status_code == 400

    def test_backslash(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_chat_id("abc\\def")
        assert exc_info.value.status_code == 400

    def test_empty_string(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_chat_id("")
        assert exc_info.value.status_code == 400

    def test_whitespace_only(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_chat_id("   ")
        assert exc_info.value.status_code == 400

    def test_null_byte(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize_chat_id("chat\x00id")
        assert exc_info.value.status_code == 400

    def test_whitespace_trimming(self):
        result = sanitize_chat_id("  my-chat  ")
        assert result == "my-chat"
