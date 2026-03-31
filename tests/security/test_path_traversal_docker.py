"""Tests for path traversal protection in docker_manager._get_meta_path."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "computer-use-server"))

import docker_manager


VALID_CHAT_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


class TestGetMetaPath:
    def test_traversal_rejected(self, tmp_path):
        with patch.object(docker_manager, "BASE_DATA_DIR", tmp_path):
            with pytest.raises(HTTPException) as exc_info:
                docker_manager._get_meta_path("../../etc")
            assert exc_info.value.status_code == 400

    def test_slash_rejected(self, tmp_path):
        with patch.object(docker_manager, "BASE_DATA_DIR", tmp_path):
            with pytest.raises(HTTPException) as exc_info:
                docker_manager._get_meta_path("abc/def")
            assert exc_info.value.status_code == 400

    def test_normal_chat_id(self, tmp_path):
        with patch.object(docker_manager, "BASE_DATA_DIR", tmp_path):
            result = docker_manager._get_meta_path(VALID_CHAT_ID)
            assert result == tmp_path / VALID_CHAT_ID / ".meta.json"
            assert str(tmp_path) in str(result)
