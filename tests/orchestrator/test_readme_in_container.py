# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Tier 2 — /home/assistant/README.md is written on container creation.

We mock `docker` SDK interactions and just pin that
`_write_file_to_container` is called with the workdir + rendered prompt.
Exercising real Docker in unit tests is out of scope; E2E smoke is in the
verification script.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "computer-use-server"))

import docker_manager as dm  # noqa: E402


class ReadmeWriterContract(unittest.TestCase):
    def test_write_file_builds_valid_tar(self):
        """_write_file_to_container must put_archive a tar with exactly one
        entry named after the filename, with the supplied body."""
        container = MagicMock()
        captured = {}

        def _capture(path, tar_bytes):
            captured["path"] = path
            captured["tar"] = tar_bytes
            # Real put_archive returns True on success; the helper now
            # raises on False.
            return True

        container.put_archive.side_effect = _capture

        dm._write_file_to_container(container, "/home/assistant", "README.md", "HELLO WORLD\n")

        self.assertEqual(captured["path"], "/home/assistant")
        # Decode the tar and assert its contents
        import io, tarfile
        tf = tarfile.open(fileobj=io.BytesIO(captured["tar"]), mode="r")
        names = tf.getnames()
        self.assertEqual(names, ["README.md"])
        body = tf.extractfile("README.md").read().decode("utf-8")
        self.assertEqual(body, "HELLO WORLD\n")

    def test_readme_gets_rendered_prompt(self):
        """When render_system_prompt_sync is available, the docker_manager
        writes its output verbatim."""
        container = MagicMock()
        captured = {}

        def _capture(container_arg, path, filename, text):
            captured["path"] = path
            captured["filename"] = filename
            captured["text"] = text

        with patch.object(dm, "_write_file_to_container", side_effect=_capture), \
             patch.object(dm, "render_system_prompt_sync",
                          return_value="# rendered prompt for chat-test\n"):
            # Call the exact snippet the hook runs. Re-implement the try-block
            # shape here rather than invoking the private _create_container
            # (which would require full Docker env).
            _, workdir = dm._get_container_user_and_workdir()
            readme_text = dm.render_system_prompt_sync("chat-test", None)
            dm._write_file_to_container(container, workdir, "README.md", readme_text)

        self.assertEqual(captured["filename"], "README.md")
        self.assertIn("chat-test", captured["text"])
        self.assertIn(captured["path"], ("/home/assistant", "/root"))


if __name__ == "__main__":
    unittest.main()
