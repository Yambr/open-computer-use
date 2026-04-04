# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Regression guard for security-critical dependency versions.

Ensures that patched CVE versions from PR #22 are not accidentally downgraded.

Run: python -m pytest tests/test_requirements.py -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _parse_version(req_path: Path, package: str):
    """Return pinned version as int tuple, e.g. (12, 1, 1). Returns None if not found."""
    pattern = re.compile(rf'^{re.escape(package)}==(.+)$', re.IGNORECASE)
    for line in req_path.read_text().splitlines():
        m = pattern.match(line.strip())
        if m:
            return tuple(int(x) for x in m.group(1).split("."))
    return None


class TestSandboxDependencyVersions(unittest.TestCase):
    """Security-patched versions in requirements.txt (sandbox / Dockerfile)."""

    REQ = ROOT / "requirements.txt"

    def _assert_at_least(self, package, min_version):
        found = _parse_version(self.REQ, package)
        self.assertIsNotNone(found, f"{package} not found in {self.REQ}")
        self.assertGreaterEqual(
            found,
            min_version,
            f"{package}=={'.'.join(map(str, found))} is below required "
            f">={'.'.join(map(str, min_version))} (CVE patch)",
        )

    def test_pillow_at_least_12_1_1(self):
        """CVE: PSD out-of-bounds write. Pillow 12 also changed Image.LANCZOS API."""
        self._assert_at_least("pillow", (12, 1, 1))

    def test_urllib3_at_least_2_6_3(self):
        """CVE: decompression bomb + redirect bypass."""
        self._assert_at_least("urllib3", (2, 6, 3))

    def test_cryptography_at_least_46_0_6(self):
        """CVE: SECT curves subgroup attack."""
        self._assert_at_least("cryptography", (46, 0, 6))

    def test_pyjwt_at_least_2_12_1(self):
        """CVE: critical header extensions bypass."""
        self._assert_at_least("PyJWT", (2, 12, 1))

    def test_pdfminer_six_at_least_20251230(self):
        """CVE: pickle deserialization RCE. Version is a date integer."""
        found = _parse_version(self.REQ, "pdfminer.six")
        self.assertIsNotNone(found, f"pdfminer.six not found in {self.REQ}")
        # Version is a single date integer like 20251230
        self.assertGreaterEqual(
            found[0],
            20251230,
            f"pdfminer.six=={found[0]} is below required >=20251230 (CVE patch)",
        )

    def test_pdfplumber_at_least_0_11_9(self):
        """Bumped to satisfy pdfminer.six constraint."""
        self._assert_at_least("pdfplumber", (0, 11, 9))


class TestOrchestratorDependencyVersions(unittest.TestCase):
    """Security-patched versions in computer-use-server/requirements.txt."""

    REQ = ROOT / "computer-use-server" / "requirements.txt"

    def test_python_multipart_at_least_0_0_22(self):
        """CVE patch for python-multipart."""
        found = _parse_version(self.REQ, "python-multipart")
        self.assertIsNotNone(found, f"python-multipart not found in {self.REQ}")
        self.assertGreaterEqual(
            found,
            (0, 0, 22),
            f"python-multipart=={'.'.join(map(str, found))} is below required >=0.0.22",
        )


if __name__ == "__main__":
    unittest.main()
