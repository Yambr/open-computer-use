"""Tests for security utilities: safe_path() and sanitize_chat_id()."""
import inspect
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "computer-use-server"))

import security
from security import safe_path, sanitize_chat_id


class TestSafePathImplementation:
    """Verify safe_path() uses os.path pattern that CodeQL natively recognizes.

    CodeQL py/path-injection does NOT recognize pathlib.Path.resolve() + is_relative_to()
    as a containment check barrier (codeql issue #17226). It DOES natively recognize
    os.path.realpath() + startswith() as a sanitizer without any model extensions.
    """

    def test_uses_os_path_realpath_not_pathlib_resolve(self):
        """safe_path() must use os.path.realpath — CodeQL recognizes this as sanitizer."""
        source = inspect.getsource(security.safe_path)
        assert "os.path.realpath" in source, (
            "safe_path() must use os.path.realpath() for CodeQL to suppress "
            "py/path-injection false positives. pathlib.Path.resolve() + "
            "is_relative_to() is NOT recognized by CodeQL as a containment barrier."
        )

    def test_uses_startswith_containment_check(self):
        """safe_path() must use startswith() containment check — the CodeQL-recognized pattern."""
        source = inspect.getsource(security.safe_path)
        assert "startswith" in source, (
            "safe_path() must use startswith() for the containment check. "
            "is_relative_to() is not recognized by CodeQL py/path-injection."
        )

    def test_does_not_use_is_relative_to(self):
        """safe_path() must NOT use is_relative_to() — CodeQL does not recognise it."""
        source = inspect.getsource(security.safe_path)
        assert "is_relative_to" not in source, (
            "safe_path() uses pathlib is_relative_to() which CodeQL does not "
            "recognise as a path containment sanitizer. Use os.path.realpath + startswith."
        )


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
