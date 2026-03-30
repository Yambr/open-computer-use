"""
Settings Wrapper — mock skill registry for Open Computer Use.

Serves user skill configurations and skill ZIP downloads.
Replace with your own implementation (database, S3, corporate registry, etc.).
"""

import hashlib
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse

app = FastAPI(title="Settings Wrapper", version="0.1.0")

API_KEY = os.getenv("API_KEY", "")
_app_dir = Path(__file__).parent
SKILLS_DIR = Path(os.getenv("SKILLS_DIR", str(_app_dir / "skills")))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", str(_app_dir / "skills.json")))


def _check_auth(api_key: str = Header(None, alias="X-Internal-Api-Key")):
    if API_KEY and api_key != API_KEY:
        raise HTTPException(401, "Invalid API key")


def _load_config() -> dict:
    """Load skills config. Re-reads on every call (no caching for simplicity)."""
    if not CONFIG_PATH.exists():
        return {"users": {}, "default_skills": []}
    return json.loads(CONFIG_PATH.read_text())


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/internal/user-config/{email}")
def get_user_config(
    email: str,
    api_key: str = Header(None, alias="X-Internal-Api-Key"),
):
    """
    Return enabled skills for a user.

    skill_manager.py expects:
    {
      "email": "user@example.com",
      "enabled_skills": [
        {"name": "...", "description": "...", "category": "public|user", "skill_path": "...", "zip_sha256": "..."}
      ]
    }
    """
    _check_auth(api_key)
    config = _load_config()

    # User-specific overrides
    user_skills = config.get("users", {}).get(email)
    if user_skills is not None:
        skills = user_skills
    else:
        # Default: all skills for everyone
        skills = config.get("default_skills", [])

    # Auto-compute zip_sha256 for user skills that have a ZIP on disk
    for skill in skills:
        if skill.get("category") == "user" and not skill.get("zip_sha256"):
            zip_path = SKILLS_DIR / f"{skill['name']}.zip"
            if zip_path.exists():
                skill["zip_sha256"] = hashlib.sha256(zip_path.read_bytes()).hexdigest()

    return {"email": email, "enabled_skills": skills}


@app.get("/api/internal/skills/{name}/download")
def download_skill(
    name: str,
    api_key: str = Header(None, alias="X-Internal-Api-Key"),
):
    """
    Download a skill as ZIP.

    - If ZIP exists in SKILLS_DIR → return it
    - If skill is native (public/example) → return JSON (skill_manager skips download)
    """
    _check_auth(api_key)

    zip_path = SKILLS_DIR / f"{name}.zip"
    if zip_path.exists():
        return FileResponse(zip_path, media_type="application/zip", filename=f"{name}.zip")

    # Native skill — no ZIP needed
    return {"name": name, "type": "native", "message": "Skill is built into the Docker image"}
