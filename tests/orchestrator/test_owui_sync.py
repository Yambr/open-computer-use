# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for syncing Computer Use outputs into Open WebUI native file storage.

Run:
  python -m pytest tests/orchestrator/test_owui_sync.py -v
"""

import cgi
import hashlib
import json
import os
import socket
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "computer-use-server"))


class _OWUIUploadHandler(BaseHTTPRequestHandler):
    uploads = []
    response_status = 200

    def do_POST(self):
        if self.path != "/api/v1/files/":
            self.send_response(404)
            self.end_headers()
            return

        if self.response_status != 200:
            self.send_response(self.response_status)
            self.end_headers()
            return

        ctype, pdict = cgi.parse_header(self.headers.get("content-type", ""))
        if ctype != "multipart/form-data":
            self.send_response(400)
            self.end_headers()
            return

        pdict["boundary"] = pdict["boundary"].encode()
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST"},
            keep_blank_values=True,
        )
        file_item = form["file"]
        content = file_item.file.read()
        file_id = f"file-{len(self.uploads) + 1}"
        self.uploads.append(
            {
                "filename": file_item.filename,
                "content": content,
                "auth": self.headers.get("Authorization"),
                "file_id": file_id,
            }
        )

        payload = json.dumps({"id": file_id, "filename": file_item.filename}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


class _OWUIServer:
    def __init__(self, status=200):
        self._server = HTTPServer(("127.0.0.1", 0), _OWUIUploadHandler)
        self._server.RequestHandlerClass.uploads = []
        self._server.RequestHandlerClass.response_status = status
        self.thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self):
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    @property
    def uploads(self):
        return self._server.RequestHandlerClass.uploads

    def start(self):
        self.thread.start()

    def stop(self):
        self._server.shutdown()
        self.thread.join(timeout=5)
        self._server.server_close()


class OutputSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.outputs_dir = Path(self.temp_dir.name) / "chat-1" / "outputs"
        self.outputs_dir.mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sync_outputs_uploads_files_and_writes_manifest(self):
        from owui_sync import sync_outputs_to_owui

        (self.outputs_dir / "hello.txt").write_text("hello sandbox")
        server = _OWUIServer()
        server.start()
        try:
            result = sync_outputs_to_owui(
                chat_id="chat-1",
                outputs_dir=self.outputs_dir,
                owui_url=server.base_url,
                owui_api_key="secret-key",
            )
        finally:
            server.stop()

        self.assertEqual(len(server.uploads), 1)
        self.assertEqual(server.uploads[0]["filename"], "hello.txt")
        self.assertEqual(server.uploads[0]["content"], b"hello sandbox")
        self.assertEqual(server.uploads[0]["auth"], "Bearer secret-key")
        self.assertEqual(
            result,
            [
                {
                    "filename": "hello.txt",
                    "file_id": "file-1",
                    "url": "/api/v1/files/file-1/content",
                }
            ],
        )

        manifest = json.loads((self.outputs_dir / ".owui_sync_manifest.json").read_text())
        self.assertIn("hello.txt", manifest)
        self.assertEqual(manifest["hello.txt"]["file_id"], "file-1")
        self.assertEqual(
            manifest["hello.txt"]["md5"],
            hashlib.md5(b"hello sandbox").hexdigest(),
        )

    def test_sync_outputs_skips_unchanged_files_using_manifest(self):
        from owui_sync import sync_outputs_to_owui

        (self.outputs_dir / "hello.txt").write_text("hello sandbox")
        server = _OWUIServer()
        server.start()
        try:
            first = sync_outputs_to_owui(
                chat_id="chat-1",
                outputs_dir=self.outputs_dir,
                owui_url=server.base_url,
                owui_api_key="secret-key",
            )
            second = sync_outputs_to_owui(
                chat_id="chat-1",
                outputs_dir=self.outputs_dir,
                owui_url=server.base_url,
                owui_api_key="secret-key",
            )
        finally:
            server.stop()

        self.assertEqual(len(server.uploads), 1)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, first)

    def test_format_sync_summary_appends_relative_file_links(self):
        from owui_sync import format_sync_summary

        result = format_sync_summary(
            "done",
            [
                {
                    "filename": "hello.txt",
                    "file_id": "file-1",
                    "url": "/api/v1/files/file-1/content",
                }
            ],
        )

        self.assertIn("done", result)
        self.assertIn("Synced to Open WebUI", result)
        self.assertIn("hello.txt", result)
        self.assertIn("/api/v1/files/file-1/content", result)

    def test_server_dockerfile_copies_owui_sync_module(self):
        dockerfile = (ROOT / "computer-use-server" / "Dockerfile").read_text()
        self.assertIn("COPY ./owui_sync.py .", dockerfile)

    def test_prompt_mentions_openwebui_relative_file_paths_when_sync_enabled(self):
        fake_skill_manager = types.SimpleNamespace(
            get_user_skills=None,
            ensure_skill_cached=None,
            build_available_skills_xml=None,
        )
        fake_docker_manager = types.SimpleNamespace(
            PUBLIC_BASE_URL="http://localhost:8081",
            OWUI_INTERNAL_URL="http://open-webui:8080",
        )
        with patch.dict(sys.modules, {
            "skill_manager": fake_skill_manager,
            "docker_manager": fake_docker_manager,
        }):
            import importlib
            system_prompt_module = importlib.import_module("system_prompt")
            system_prompt_module._render_cache.clear()
            body = system_prompt_module.render_system_prompt_sync("abc123", None)

        self.assertIn("/api/v1/files/<id>/content", body)
        self.assertIn("prefer the Open WebUI file paths returned in tool results", body)

    def test_sync_outputs_returns_empty_when_upload_fails(self):
        from owui_sync import sync_outputs_to_owui

        (self.outputs_dir / "hello.txt").write_text("hello sandbox")
        server = _OWUIServer(status=500)
        server.start()
        try:
            result = sync_outputs_to_owui(
                chat_id="chat-1",
                outputs_dir=self.outputs_dir,
                owui_url=server.base_url,
                owui_api_key="secret-key",
            )
        finally:
            server.stop()

        self.assertEqual(result, [])
        self.assertFalse((self.outputs_dir / ".owui_sync_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
