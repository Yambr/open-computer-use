"""Tests for path traversal protection in computer-use-server/app.py endpoints.

Note: FastAPI/Starlette normalizes `..` in URL paths at the HTTP level,
so path traversal via `../../` in URL segments is blocked before reaching handlers.
These tests verify that:
1. sanitize_chat_id() rejects malicious chat_id values
2. safe_path() provides defense-in-depth at the application level
3. Normal operations continue to work correctly
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "computer-use-server"))

from fastapi.testclient import TestClient


VALID_CHAT_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


@pytest.fixture
def tmp_data(tmp_path):
    """Create temporary data directory with test files."""
    chat_dir = tmp_path / VALID_CHAT_ID
    outputs = chat_dir / "outputs"
    uploads = chat_dir / "uploads"
    outputs.mkdir(parents=True)
    uploads.mkdir(parents=True)
    (outputs / "test.txt").write_text("hello")
    (uploads / "uploaded.txt").write_text("world")
    return tmp_path


@pytest.fixture
def client(tmp_data):
    """TestClient with patched BASE_DATA_DIR."""
    import app as app_module
    with patch.object(app_module, "BASE_DATA_DIR", tmp_data):
        yield TestClient(app_module.app)


class TestChatIdValidation:
    """Test that endpoints reject malicious chat_id values."""

    def test_upload_rejects_dot_dot_chat_id(self, client):
        resp = client.post(
            "/api/uploads/..test../file.txt",
            files={"file": ("test.txt", b"content")},
        )
        assert resp.status_code == 400

    def test_download_rejects_dot_dot_chat_id(self, client):
        resp = client.get("/files/..test../somefile")
        assert resp.status_code == 400

    def test_archive_rejects_dot_dot_chat_id(self, client):
        resp = client.get("/files/..test../archive")
        assert resp.status_code == 400

    def test_outputs_rejects_dot_dot_chat_id(self, client):
        resp = client.get("/api/outputs/..test..")
        assert resp.status_code == 400

    def test_manifest_rejects_dot_dot_chat_id(self, client):
        resp = client.get("/api/uploads/..test../manifest")
        assert resp.status_code == 400

    def test_uploads_list_rejects_dot_dot_chat_id(self, client):
        resp = client.get("/api/uploads/..test../list")
        assert resp.status_code == 400


class TestNormalOperations:
    """Test that legitimate operations continue to work."""

    def test_upload_normal(self, client):
        resp = client.post(
            f"/api/uploads/{VALID_CHAT_ID}/newfile.txt",
            files={"file": ("newfile.txt", b"content")},
        )
        assert resp.status_code == 200

    def test_download_normal(self, client):
        resp = client.get(f"/files/{VALID_CHAT_ID}/test.txt")
        assert resp.status_code == 200
        assert resp.text == "hello"

    def test_archive_normal(self, client):
        resp = client.get(f"/files/{VALID_CHAT_ID}/archive")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

    def test_outputs_normal(self, client):
        resp = client.get(f"/api/outputs/{VALID_CHAT_ID}")
        assert resp.status_code == 200

    def test_manifest_normal(self, client):
        resp = client.get(f"/api/uploads/{VALID_CHAT_ID}/manifest")
        assert resp.status_code == 200

    def test_uploads_list_normal(self, client):
        resp = client.get(f"/api/uploads/{VALID_CHAT_ID}/list")
        assert resp.status_code == 200

    def test_default_chat_id(self, client, tmp_data):
        """chat_id='default' should be accepted."""
        (tmp_data / "default" / "outputs").mkdir(parents=True)
        resp = client.get("/api/outputs/default")
        assert resp.status_code == 200


class TestSafePathDirectly:
    """Direct unit tests for safe_path integration — defense-in-depth."""

    def test_safe_path_blocks_traversal(self, tmp_data):
        from security import safe_path
        from fastapi import HTTPException
        base = tmp_data / VALID_CHAT_ID / "outputs"
        with pytest.raises(HTTPException) as exc:
            safe_path(base, "../../etc/passwd")
        assert exc.value.status_code == 403

    def test_safe_path_allows_subdirs(self, tmp_data):
        from security import safe_path
        base = tmp_data / VALID_CHAT_ID / "outputs"
        result = safe_path(base, "subdir/file.txt")
        assert str(result).startswith(str(base.resolve()))
