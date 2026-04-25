# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Shared pytest fixtures for backend patch tests.

Provides byte-identical v0.9.1 upstream source as test fixtures for
patch-apply / idempotency / fail-loud coverage.
"""
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MIDDLEWARE_V091 = FIXTURES_DIR / "middleware_v0.9.1.py"
RETRIEVAL_V091 = FIXTURES_DIR / "retrieval_v0.9.1.py"
MIDDLEWARE_V092 = FIXTURES_DIR / "middleware_v0.9.2.py"
RETRIEVAL_V092 = FIXTURES_DIR / "retrieval_v0.9.2.py"


def load_middleware_v091() -> str:
    return MIDDLEWARE_V091.read_text(encoding="utf-8")


def load_retrieval_v091() -> str:
    return RETRIEVAL_V091.read_text(encoding="utf-8")


def load_middleware_v092() -> str:
    return MIDDLEWARE_V092.read_text(encoding="utf-8")


def load_retrieval_v092() -> str:
    return RETRIEVAL_V092.read_text(encoding="utf-8")
