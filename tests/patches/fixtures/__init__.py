# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Fixture package for backend patch tests.

Fixture files (middleware_v0.9.{1,2}.py, retrieval_v0.9.{1,2}.py) are
byte-identical extracts from upstream Open WebUI v0.9.1 / v0.9.2 — DO NOT
modify them. They are not imported as Python modules; they are read as
text by the patch test harness. The v0.9.1 fixtures pin shim regression
coverage; the build itself targets v0.9.2 strictly.
"""
