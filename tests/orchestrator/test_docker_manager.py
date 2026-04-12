# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Tests for docker_manager._create_container env-injection behaviour.

Covers the three operator paths from Phase 3 (GATEWAY-05) plus the
ANTHROPIC_CUSTOM_HEADERS regression guard (GATEWAY-07) and the
current_anthropic_base_url ContextVar default (GATEWAY-01).

Run: cd computer-use-server && python -m pytest ../tests/orchestrator/test_docker_manager.py -v
"""

import os
import sys
import unittest
import importlib
import contextvars
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'computer-use-server'))

from context_vars import (
    current_chat_id,
    current_user_email,
    current_user_name,
    current_gitlab_token,
    current_gitlab_host,
    current_anthropic_auth_token,
    current_anthropic_base_url,
)


# Ten gateway model/flag vars injected via CLAUDE_CODE_PASSTHROUGH_ENVS
GATEWAY_VAR_NAMES = (
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS",
    "DISABLE_PROMPT_CACHING",
    "DISABLE_PROMPT_CACHING_SONNET",
    "DISABLE_PROMPT_CACHING_OPUS",
    "DISABLE_PROMPT_CACHING_HAIKU",
)
# The full set that a clean path-A env must not contain (12 keys total)
ALL_GATEWAY_ENV_KEYS = GATEWAY_VAR_NAMES + ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


def _build_mock_docker_client():
    """Return a MagicMock wired to satisfy the _create_container call path.

    _create_container uses:
      - client.containers.run(...)     — for the directory-setup ephemeral container
      - client.containers.create(...)  — for the actual sandbox container (the assertion target)
      - client.networks.get(...)       — for the compose-network attach (guarded by try/except)
      - client.containers.get(...)     — for the ORCHESTRATOR_CONTAINER_NAME lookup (compose net)
    """
    client = MagicMock()
    client.containers.run.return_value = None
    client.containers.create.return_value = MagicMock()
    # networks.list / volumes.list are not called by _create_container but harmless as defaults
    client.networks.list.return_value = []
    client.volumes.list.return_value = []
    client.images.get.return_value = MagicMock()
    return client


def _reset_context_vars():
    """Pin every ContextVar to a deterministic value to suppress cross-test leakage."""
    current_chat_id.set("test-chat")
    current_user_email.set(None)
    current_user_name.set(None)
    current_gitlab_token.set(None)
    current_gitlab_host.set("gitlab.com")
    current_anthropic_auth_token.set(None)
    current_anthropic_base_url.set(None)


def _clear_gateway_env():
    """Pop every gateway-related env var from os.environ."""
    for k in ALL_GATEWAY_ENV_KEYS:
        os.environ.pop(k, None)


class TestDockerManagerEnvInjection(unittest.TestCase):
    """Three-path env-injection matrix + empty-string guard + ANTHROPIC_CUSTOM_HEADERS regression."""

    def _reload_docker_manager(self, overrides):
        """Apply a clean env matrix (clear gateway vars, apply overrides) and reload the module.

        Returns the reloaded docker_manager module. Caller is responsible for using the
        patch.dict context manager that wraps this method.
        """
        _clear_gateway_env()
        for k, v in overrides.items():
            os.environ[k] = v
        import docker_manager
        importlib.reload(docker_manager)
        return docker_manager

    def _run_isolated(self, body):
        """Run `body` inside a fresh contextvars.Context so .set() calls do not leak to sibling tests.

        `body` is a callable that takes no args and performs the test steps. Any ContextVar
        mutations (e.g. current_chat_id.set("test-chat")) are confined to this Context copy.
        """
        fresh_ctx = contextvars.Context()
        return fresh_ctx.run(body)

    def test_path_a_zero_config_injects_no_gateway_vars(self):
        """Path A: no ANTHROPIC_*/CLAUDE_CODE_* env vars on host -> no such keys in extra_env."""
        def body():
            with patch.dict(os.environ, {}, clear=False):
                docker_manager = self._reload_docker_manager({})
                _reset_context_vars()
                client = _build_mock_docker_client()
                with patch("docker_manager.get_docker_client", return_value=client):
                    docker_manager._create_container("test-chat", "owui-chat-test")

                env_dict = client.containers.create.call_args.kwargs["environment"]
                for key in ALL_GATEWAY_ENV_KEYS:
                    self.assertNotIn(key, env_dict, f"{key} leaked into zero-config path")
        self._run_isolated(body)

    def test_path_b_auth_only_injects_token_and_default_base_url(self):
        """Path B: ANTHROPIC_AUTH_TOKEN only -> token + default https://api.anthropic.com base URL."""
        def body():
            with patch.dict(os.environ, {}, clear=False):
                docker_manager = self._reload_docker_manager(
                    {"ANTHROPIC_AUTH_TOKEN": "sk-EXAMPLE-path-b"}
                )
                _reset_context_vars()
                client = _build_mock_docker_client()
                with patch("docker_manager.get_docker_client", return_value=client):
                    docker_manager._create_container("test-chat", "owui-chat-test")

                env_dict = client.containers.create.call_args.kwargs["environment"]
                self.assertEqual(env_dict["ANTHROPIC_AUTH_TOKEN"], "sk-EXAMPLE-path-b")
                self.assertEqual(env_dict["ANTHROPIC_BASE_URL"], "https://api.anthropic.com")
                for name in GATEWAY_VAR_NAMES:
                    self.assertNotIn(name, env_dict, f"{name} leaked into auth-only path B")
        self._run_isolated(body)

    def test_path_c_custom_gateway_injects_all_twelve_keys(self):
        """Path C: token + base URL + all ten gateway vars -> all twelve keys present with exact values."""
        def body():
            overrides = {
                "ANTHROPIC_AUTH_TOKEN": "sk-EXAMPLE-path-c",
                "ANTHROPIC_BASE_URL": "https://litellm.internal/",
            }
            for name in GATEWAY_VAR_NAMES:
                overrides[name] = f"TEST_{name}"

            with patch.dict(os.environ, {}, clear=False):
                docker_manager = self._reload_docker_manager(overrides)
                _reset_context_vars()
                client = _build_mock_docker_client()
                with patch("docker_manager.get_docker_client", return_value=client):
                    docker_manager._create_container("test-chat", "owui-chat-test")

                env_dict = client.containers.create.call_args.kwargs["environment"]
                self.assertEqual(env_dict["ANTHROPIC_AUTH_TOKEN"], "sk-EXAMPLE-path-c")
                self.assertEqual(env_dict["ANTHROPIC_BASE_URL"], "https://litellm.internal/")
                for name in GATEWAY_VAR_NAMES:
                    self.assertEqual(
                        env_dict[name],
                        f"TEST_{name}",
                        f"{name} value mismatch in custom-gateway path",
                    )
        self._run_isolated(body)

    def test_empty_string_env_vars_are_not_injected(self):
        """Empty-string env vars must be skipped by the `if _value:` guard."""
        def body():
            overrides = {
                "ANTHROPIC_AUTH_TOKEN": "sk-EXAMPLE-empty-guard",
                "ANTHROPIC_MODEL": "",  # explicit empty string
            }
            with patch.dict(os.environ, {}, clear=False):
                docker_manager = self._reload_docker_manager(overrides)
                _reset_context_vars()
                client = _build_mock_docker_client()
                with patch("docker_manager.get_docker_client", return_value=client):
                    docker_manager._create_container("test-chat", "owui-chat-test")

                env_dict = client.containers.create.call_args.kwargs["environment"]
                self.assertNotIn("ANTHROPIC_MODEL", env_dict)
                # other nine gateway names also absent — none were set
                for name in GATEWAY_VAR_NAMES:
                    self.assertNotIn(name, env_dict, f"{name} unexpectedly present")
        self._run_isolated(body)

    def test_anthropic_custom_headers_injection_regression_guard(self):
        """current_user_email set -> ANTHROPIC_CUSTOM_HEADERS + GIT_* vars land unchanged."""
        def body():
            with patch.dict(os.environ, {}, clear=False):
                docker_manager = self._reload_docker_manager(
                    {"ANTHROPIC_AUTH_TOKEN": "sk-EXAMPLE-headers"}
                )
                _reset_context_vars()
                current_user_email.set("alice@example.com")
                client = _build_mock_docker_client()
                with patch("docker_manager.get_docker_client", return_value=client):
                    docker_manager._create_container("test-chat", "owui-chat-test")

                env_dict = client.containers.create.call_args.kwargs["environment"]
                self.assertEqual(
                    env_dict["ANTHROPIC_CUSTOM_HEADERS"],
                    "x-openwebui-user-email: alice@example.com",
                )
                self.assertEqual(env_dict["GIT_AUTHOR_EMAIL"], "alice@example.com")
                self.assertEqual(env_dict["GIT_COMMITTER_EMAIL"], "alice@example.com")
        self._run_isolated(body)


class TestContextVarAnthropicBaseUrlDefault(unittest.TestCase):
    """GATEWAY-01 unit test: ContextVar default must be None so the `or` fallback fires."""

    def test_current_anthropic_base_url_default_is_none_after_reload(self):
        """ContextVar must declare default=None so .get() returns None when unset.

        We do NOT reload context_vars here — reloading creates a new ContextVar
        singleton that other already-loaded modules no longer reference, which
        pollutes sibling test files. Instead, we run the .get() inside a fresh
        copy_context() so any prior .set() from other tests does not leak in,
        then assert the declared default is None.
        """
        import contextvars
        import context_vars as cv_mod

        # Inspect the default directly without touching live context state.
        # This avoids cross-test pollution from any prior .set() calls.
        fresh_ctx = contextvars.Context()
        value = fresh_ctx.run(cv_mod.current_anthropic_base_url.get)
        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
