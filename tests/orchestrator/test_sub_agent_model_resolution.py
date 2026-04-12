# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for mcp_tools.sub_agent model alias resolution (Phase 3 GATEWAY-06).

Seven cases cover the D4 matrix:
  1. alias "sonnet" -> claude-sonnet-4-6 when ANTHROPIC_DEFAULT_SONNET_MODEL unset
  2. alias "opus"   -> claude-opus-4-6   when ANTHROPIC_DEFAULT_OPUS_MODEL unset
  3. alias "haiku"  -> claude-haiku-4-5  when ANTHROPIC_DEFAULT_HAIKU_MODEL unset
  4. direct ID "claude-sonnet-4-6" passes through unchanged
  5. LiteLLM-style "anthropic/claude-sonnet-4-6" passes through unchanged
  6. empty/None model falls back to claude-sonnet-4-6
  7. alias "sonnet" honours ANTHROPIC_DEFAULT_SONNET_MODEL="azure/my-deployment"

PATCH TARGET: mcp_tools._execute_bash.

Rationale: sub_agent() builds a `claude_command` string containing `--model <MODEL_ID>`
and runs it via `asyncio.to_thread(_execute_bash, container, claude_command, ...)`.
Patching _execute_bash lets us capture the exact command string (and therefore the
resolved model ID that landed on the CLI) without spawning anything. Returning a
synthetic Claude JSON result line keeps _format_sub_agent_result happy so sub_agent
returns a formatted string we can also inspect for model_display.

Run: cd computer-use-server && python -m pytest ../tests/orchestrator/test_sub_agent_model_resolution.py -v
"""

import os
import sys
import unittest
import importlib
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'computer-use-server'))

from context_vars import (
    current_chat_id,
    current_user_email,
    current_user_name,
    current_gitlab_token,
    current_anthropic_auth_token,
    current_anthropic_base_url,
    current_mcp_servers,
)


# Env vars that drive alias resolution; cleared between tests to avoid leakage
MODEL_ENV_VARS = (
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
)


def _mock_container():
    """Mock Docker container (mirrors helper in test_mcp_tools.py / test_single_user_mode.py)."""
    c = MagicMock()
    c.id = "mock-container-id"
    c.name = "owui-chat-test"
    c.status = "running"
    return c


def _reset_context_vars_for_sub_agent():
    """Pin ContextVars used by sub_agent so its code path runs deterministically."""
    current_chat_id.set("test-chat")
    current_user_email.set(None)
    current_user_name.set(None)
    current_gitlab_token.set(None)
    current_anthropic_auth_token.set(None)
    current_anthropic_base_url.set(None)
    current_mcp_servers.set("")


def _fake_execute_bash_factory(captured):
    """Build a fake _execute_bash that records the (last) claude-command string.

    The first calls from sub_agent are for plan-file writes and marker touches; we
    only care about the call that carries '--model '. We record every claude-tagged
    command so the test can inspect the argv that reached the CLI, and we return a
    valid Claude-like JSON result line so _format_sub_agent_result parses cleanly.
    """
    def fake_execute_bash(container, cmd, timeout):
        if " claude " in cmd or cmd.startswith("claude ") or "claude -p " in cmd:
            captured["claude_cmd"] = cmd
            return {
                "output": '{"type": "result", "result": "ok", "total_cost_usd": 0.0, '
                          '"num_turns": 1, "is_error": false, "session_id": "sess-test"}',
                "exit_code": 0,
                "success": True,
            }
        # Plan-file write / marker touch / MCP config write — ignored, return neutral success
        return {"output": "", "exit_code": 0, "success": True}
    return fake_execute_bash


class TestSubAgentModelResolution(unittest.IsolatedAsyncioTestCase):
    """Seven alias-resolution cases exercising sub_agent's post-03-01 resolution block."""

    def _setup_env(self, overrides):
        """Clear model env vars, apply overrides, then reload docker_manager + mcp_tools.

        The reload order matters — mcp_tools imports ANTHROPIC_DEFAULT_*_MODEL from
        docker_manager at module scope, so docker_manager must pick up the new env
        values first.
        """
        for k in MODEL_ENV_VARS:
            os.environ.pop(k, None)
        for k, v in overrides.items():
            os.environ[k] = v
        import docker_manager
        importlib.reload(docker_manager)
        import mcp_tools
        importlib.reload(mcp_tools)
        return mcp_tools

    async def _run_sub_agent_and_capture(self, requested_model, env_overrides=None):
        """Invoke sub_agent with mocked dependencies; return (captured_cmd, result_str)."""
        env_overrides = env_overrides or {}
        with patch.dict(os.environ, {}, clear=False):
            mcp_tools = self._setup_env(env_overrides)
            _reset_context_vars_for_sub_agent()

            captured = {}
            fake_exec = _fake_execute_bash_factory(captured)

            ctx = MagicMock()
            ctx.report_progress = AsyncMock()

            with patch.object(mcp_tools, "_ensure_gitlab_token", new_callable=AsyncMock), \
                 patch.object(mcp_tools, "_get_or_create_container", return_value=_mock_container()), \
                 patch.object(mcp_tools, "_execute_bash", side_effect=fake_exec):
                result = await mcp_tools.sub_agent(
                    task="test task",
                    description="test description",
                    ctx=ctx,
                    model=requested_model,
                )

        return captured.get("claude_cmd", ""), result

    async def test_alias_sonnet_default(self):
        """sub_agent(model="sonnet") resolves to claude-sonnet-4-6 when no env override."""
        cmd, result = await self._run_sub_agent_and_capture("sonnet")
        self.assertIn("--model claude-sonnet-4-6", cmd)
        self.assertIn("**Model:** sonnet", result)

    async def test_alias_opus_default(self):
        """sub_agent(model="opus") resolves to claude-opus-4-6 when no env override."""
        cmd, result = await self._run_sub_agent_and_capture("opus")
        self.assertIn("--model claude-opus-4-6", cmd)
        self.assertIn("**Model:** opus", result)

    async def test_alias_haiku_default(self):
        """sub_agent(model="haiku") resolves to claude-haiku-4-5 when no env override."""
        cmd, result = await self._run_sub_agent_and_capture("haiku")
        self.assertIn("--model claude-haiku-4-5", cmd)
        self.assertIn("**Model:** haiku", result)

    async def test_direct_model_id_passes_through(self):
        """A direct Anthropic model ID must pass through unchanged (no silent reset)."""
        cmd, result = await self._run_sub_agent_and_capture("claude-sonnet-4-6")
        self.assertIn("--model claude-sonnet-4-6", cmd)
        self.assertIn("**Model:** claude-sonnet-4-6", result)

    async def test_litellm_style_model_id_passes_through(self):
        """LiteLLM-prefixed IDs (anthropic/..., azure/..., etc.) pass through unchanged."""
        cmd, result = await self._run_sub_agent_and_capture("anthropic/claude-sonnet-4-6")
        self.assertIn("--model anthropic/claude-sonnet-4-6", cmd)
        self.assertIn("**Model:** anthropic/claude-sonnet-4-6", result)

    async def test_empty_model_falls_back_to_sonnet(self):
        """Empty model falls back to claude-sonnet-4-6 with model_display='sonnet'.

        Note: sub_agent substitutes empty model with SUB_AGENT_DEFAULT_MODEL ("sonnet")
        before the alias resolution runs, so the end state is the same: claude-sonnet-4-6
        on the CLI and 'sonnet' in the display line.
        """
        cmd, result = await self._run_sub_agent_and_capture("")
        self.assertIn("--model claude-sonnet-4-6", cmd)
        self.assertIn("**Model:** sonnet", result)

    async def test_sonnet_alias_honours_env_override(self):
        """ANTHROPIC_DEFAULT_SONNET_MODEL env var redirects the 'sonnet' alias."""
        cmd, result = await self._run_sub_agent_and_capture(
            "sonnet",
            env_overrides={"ANTHROPIC_DEFAULT_SONNET_MODEL": "azure/my-deployment"},
        )
        self.assertIn("--model azure/my-deployment", cmd)
        # Must NOT contain the hardcoded default as a standalone --model token
        self.assertNotIn("--model claude-sonnet-4-6", cmd)
        self.assertIn("**Model:** sonnet", result)


if __name__ == "__main__":
    unittest.main()
