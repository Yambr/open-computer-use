"""Tests for path traversal protection in settings-wrapper/app.py."""
import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient


@pytest.fixture
def settings_client(tmp_path):
    """TestClient with patched SKILLS_DIR and disabled auth."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "valid-skill.zip").write_bytes(b"PK\x03\x04fake")

    # Import settings-wrapper/app.py with a unique module name to avoid conflicts
    settings_wrapper_path = Path(__file__).resolve().parent.parent.parent / "settings-wrapper"
    spec = importlib.util.spec_from_file_location(
        "settings_wrapper_app",
        str(settings_wrapper_path / "app.py"),
    )
    settings_app = importlib.util.module_from_spec(spec)
    sys.modules["settings_wrapper_app"] = settings_app
    spec.loader.exec_module(settings_app)

    with patch.object(settings_app, "SKILLS_DIR", skills_dir), \
         patch.object(settings_app, "API_KEY", ""):
        yield TestClient(settings_app.app)


class TestDownloadSkillTraversal:
    def test_dot_dot_in_name_rejected(self, settings_client):
        """Skill name containing '..' should be rejected."""
        resp = settings_client.get(
            "/api/internal/skills/..evil../download"
        )
        assert resp.status_code == 400

    def test_normal_skill(self, settings_client):
        resp = settings_client.get(
            "/api/internal/skills/valid-skill/download"
        )
        assert resp.status_code == 200

    def test_native_skill(self, settings_client):
        resp = settings_client.get(
            "/api/internal/skills/nonexistent-skill/download"
        )
        assert resp.status_code == 200
        assert resp.json()["type"] == "native"
