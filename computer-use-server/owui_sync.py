# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Sync Computer Use output files into Open WebUI native file storage."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import List

import requests


_MANIFEST_NAME = ".owui_sync_manifest.json"


def _manifest_path(outputs_dir: Path) -> Path:
    return outputs_dir / _MANIFEST_NAME


def _load_manifest(outputs_dir: Path) -> dict:
    path = _manifest_path(outputs_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _write_manifest(outputs_dir: Path, manifest: dict) -> None:
    _manifest_path(outputs_dir).write_text(json.dumps(manifest, indent=2, sort_keys=True))


def _md5(path: Path) -> str:
    md5_hash = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def _upload_file(owui_url: str, owui_api_key: str, file_path: Path) -> tuple[str, str]:
    with file_path.open("rb") as handle:
        response = requests.post(
            f"{owui_url.rstrip('/')}/api/v1/files/",
            headers={"Authorization": f"Bearer {owui_api_key}"},
            files={"file": (file_path.name, handle, "application/octet-stream")},
            timeout=30,
        )
    response.raise_for_status()
    payload = response.json()
    file_id = payload["id"]
    return file_id, f"/api/v1/files/{file_id}/content"


def format_sync_summary(output: str, synced_files: List[dict]) -> str:
    if not synced_files:
        return output

    lines = [output.rstrip(), "", "---", "Synced to Open WebUI:"] if output else ["Synced to Open WebUI:"]
    for item in synced_files:
        lines.append(f"- {item['filename']} -> {item['url']}")
    return "\n".join(lines)


def sync_outputs_to_owui(
    chat_id: str,
    outputs_dir: Path,
    owui_url: str,
    owui_api_key: str,
) -> List[dict]:
    del chat_id
    outputs_dir = Path(outputs_dir)
    if not outputs_dir.exists():
        return []

    manifest = _load_manifest(outputs_dir)
    results: list[dict] = []
    updated = False

    for file_path in sorted(outputs_dir.rglob("*")):
        if not file_path.is_file() or file_path.name.startswith("."):
            continue

        digest = _md5(file_path)
        entry = manifest.get(file_path.name)
        if entry and entry.get("md5") == digest and entry.get("file_id"):
            results.append(
                {
                    "filename": file_path.name,
                    "file_id": entry["file_id"],
                    "url": entry["url"],
                }
            )
            continue

        try:
            file_id, url = _upload_file(owui_url, owui_api_key, file_path)
        except Exception:
            continue

        manifest[file_path.name] = {
            "md5": digest,
            "file_id": file_id,
            "url": url,
            "synced_at": time.time(),
        }
        updated = True
        results.append({"filename": file_path.name, "file_id": file_id, "url": url})

    if updated:
        _write_manifest(outputs_dir, manifest)

    return results
