# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Unit tests for opencode adapter error event mapping (REQ-MCP-03).

These tests verify that the opencode adapter correctly handles
{"type":"error","data":{...}} events in the NDJSON event stream,
even when the subprocess exits with rc=0.
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "computer-use-server"))

import pytest
from cli_adapters.opencode import OpenCodeAdapter


@pytest.fixture
def adapter():
    return OpenCodeAdapter()


def make_ndjson(*events):
    """Encode a list of event dicts as NDJSON."""
    return "\n".join(json.dumps(e) for e in events) + "\n"


class TestErrorEventMapping:
    """Test that et == 'error' events promote is_error and surface the message."""

    def test_error_event_with_message_rc0(self, adapter):
        """NDJSON with error event + rc=0 -> is_error=True, message surfaced."""
        ndjson = make_ndjson({"type": "error", "data": {"message": "OAuth expired"}})
        result = adapter.parse_result(stdout=ndjson, stderr="", returncode=0)
        assert result.is_error is True, f"is_error should be True, got {result.is_error}"
        assert "opencode error: OAuth expired" in result.text, (
            f"text should contain 'opencode error: OAuth expired', got: {result.text!r}"
        )

    def test_error_event_raw_ndjson_not_in_text(self, adapter):
        """When error event is present, raw NDJSON must not appear in result text."""
        ndjson = make_ndjson({"type": "error", "data": {"message": "OAuth expired"}})
        result = adapter.parse_result(stdout=ndjson, stderr="", returncode=0)
        # Result text must not be the raw NDJSON dump
        assert result.text != ndjson.strip(), (
            f"result.text must not be raw NDJSON, got: {result.text!r}"
        )
        # Must not contain '{"type"' (raw event structure)
        assert '{"type": "error"' not in result.text, (
            f"raw NDJSON event should not appear in result text: {result.text!r}"
        )

    def test_error_event_data_null(self, adapter):
        """NDJSON with error event and data=null -> is_error=True, no exception."""
        ndjson = make_ndjson({"type": "error", "data": None})
        result = adapter.parse_result(stdout=ndjson, stderr="", returncode=0)
        assert result.is_error is True, f"is_error should be True, got {result.is_error}"
        # Must not raise; text should contain something sensible
        assert "opencode error:" in result.text, (
            f"text should start with 'opencode error:', got: {result.text!r}"
        )

    def test_error_event_no_data_key(self, adapter):
        """NDJSON with error event and no 'data' key -> is_error=True, fallback to str({})."""
        ndjson = make_ndjson({"type": "error"})
        result = adapter.parse_result(stdout=ndjson, stderr="", returncode=0)
        assert result.is_error is True, f"is_error should be True, got {result.is_error}"
        assert "opencode error:" in result.text, (
            f"text should start with 'opencode error:', got: {result.text!r}"
        )

    def test_error_event_data_no_message_key(self, adapter):
        """NDJSON with error event and data with no 'message' key -> str(data) fallback."""
        ndjson = make_ndjson({"type": "error", "data": {"code": 429}})
        result = adapter.parse_result(stdout=ndjson, stderr="", returncode=0)
        assert result.is_error is True, f"is_error should be True, got {result.is_error}"
        assert "opencode error:" in result.text, (
            f"text should start with 'opencode error:', got: {result.text!r}"
        )
        # Should include the code value via str() fallback
        assert "429" in result.text, (
            f"str fallback should include code 429, got: {result.text!r}"
        )

    def test_no_error_events_rc0(self, adapter):
        """NDJSON with no error events + rc=0 -> is_error=False (existing behavior preserved)."""
        ndjson = make_ndjson(
            {"type": "message-completed", "text": "Done successfully"}
        )
        result = adapter.parse_result(stdout=ndjson, stderr="", returncode=0)
        assert result.is_error is False, (
            f"is_error should be False for success path, got {result.is_error}"
        )
        assert result.text == "Done successfully", (
            f"text should be the success message, got: {result.text!r}"
        )

    def test_no_events_rc1_still_error(self, adapter):
        """NDJSON with no events + rc=1 -> is_error=True (rc-based init still works)."""
        result = adapter.parse_result(stdout="", stderr="some error", returncode=1)
        assert result.is_error is True, (
            f"is_error should be True for rc=1, got {result.is_error}"
        )


class TestErrorEventDoesNotCorruptSuccessPath:
    """Verify that adding the error branch does not break existing event handlers."""

    def test_step_finish_cost_extraction_still_works(self, adapter):
        """step-finish cost extraction unaffected by error branch addition."""
        ndjson = make_ndjson(
            {"type": "step-finish", "text": "Step done", "cost": 0.005},
        )
        result = adapter.parse_result(stdout=ndjson, stderr="", returncode=0)
        assert result.cost_usd == pytest.approx(0.005), (
            f"cost_usd should be 0.005, got {result.cost_usd}"
        )

    def test_assistant_message_completed_text_extraction(self, adapter):
        """assistant-message-completed text extraction unaffected."""
        ndjson = make_ndjson(
            {"type": "assistant-message-completed", "text": "Final answer"}
        )
        result = adapter.parse_result(stdout=ndjson, stderr="", returncode=0)
        assert result.text == "Final answer", (
            f"text should be 'Final answer', got: {result.text!r}"
        )
        assert result.is_error is False
