# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Pitfall 1 regression guard — per-CLI auth allowlist isolation.

When SUBAGENT_CLI selects a runtime, only that runtime's passthrough tuple
crosses the orchestrator->sandbox boundary. Other runtimes' auth env vars
must NOT leak into the container's `Env`, even if the operator has them
set on the host (common in mixed-deployment environments).

Also verifies the OPENCODE_CONFIG pin (Plan 06-01 Edit 1c) — when
SUBAGENT_CLI=opencode, extra_env["OPENCODE_CONFIG"] must equal
"/tmp/opencode.json" so docker exec'd subprocesses inherit it and OpenCode
never falls back to ~/.local/share/opencode/auth.json (Pitfall 7 reopen).

Mirrors tests/orchestrator/test_docker_manager.py pattern: monkeypatch.setenv
+ importlib.reload(docker_manager) + mocked docker client + capture
`containers.create(environment=...)` kwargs (the actual sandbox container is
created via `client.containers.create(**config)` — `containers.run` is only
used for the ephemeral directory-setup shim).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make `computer-use-server` importable (project layout puts it as a sibling
# directory, not a Python package on sys.path by default).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVER_DIR = _REPO_ROOT / "computer-use-server"
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))


def _build_mock_docker_client():
    """Mock docker client wired for the _create_container call path.

    Mirrors tests/orchestrator/test_docker_manager.py::_build_mock_docker_client
    so the SUT's exception-tolerant fallbacks (network attach, save_container_meta,
    README write, MCP resource sync, defensive scrub) are all silently satisfied.

    The actual sandbox is created via `client.containers.create(**config)` — that
    is the call we inspect for the `environment` kwarg. `containers.run` is the
    ephemeral mkdir shim and irrelevant to the assertion target.
    """
    client = MagicMock()
    client.containers.run.return_value = None
    fake_container = MagicMock()
    # Defensive scrub call (Plan 06-01 D4) — return a (exit_code, output) tuple
    # so any unpacking in the SUT does not raise.
    fake_container.exec_run = MagicMock(return_value=(0, b""))
    client.containers.create.return_value = fake_container
    client.networks.list.return_value = []
    client.volumes.list.return_value = []
    client.images.get.return_value = MagicMock()
    return client, fake_container


def _clear_phase6_auth_env():
    """Pop every Phase-6 auth env var so the parametrize starts from a clean slate.

    Without this, a stale OPENAI_API_KEY from a sibling test (or the developer's
    shell) would survive `monkeypatch.setenv` only for the keys we explicitly
    set, but the module-level tuples are built at import time from os.getenv —
    `importlib.reload` re-runs them, so the pre-reload os.environ state IS the
    test fixture. Be explicit.
    """
    for key in (
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENROUTER_API_KEY",
        "CODEX_MODEL",
        "OPENCODE_MODEL",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "SUBAGENT_CLI",
    ):
        os.environ.pop(key, None)


@pytest.mark.parametrize(
    "cli,expected_keys,forbidden_keys,expected_opencode_config",
    [
        (
            "claude",
            {"ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"},
            {"OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL", "OPENCODE_CONFIG"},
            None,  # OPENCODE_CONFIG must NOT be set for non-opencode runtimes
        ),
        (
            "codex",
            {"OPENAI_API_KEY", "OPENAI_BASE_URL"},
            {"ANTHROPIC_AUTH_TOKEN", "OPENROUTER_API_KEY", "OPENCODE_CONFIG"},
            None,
        ),
        (
            "opencode",
            {"OPENROUTER_API_KEY", "OPENAI_API_KEY"},
            {"ANTHROPIC_AUTH_TOKEN"},
            "/tmp/opencode.json",  # Plan 06-01 Edit 1c — ROADMAP success #2
        ),
    ],
)
def test_passthrough_isolation(
    cli, expected_keys, forbidden_keys, expected_opencode_config
):
    """With all three host auth env vars set, only the active CLI's allowlist
    crosses into extra_env. Closes Pitfall 1 (auth bleed across CLIs).

    For opencode, additionally verifies OPENCODE_CONFIG=/tmp/opencode.json is
    pinned in the container Env so docker exec subprocesses inherit it
    (Pitfall 7 — entrypoint export alone is insufficient)."""
    overrides = {
        "SUBAGENT_CLI": cli,
        # Set ALL three families of auth env vars on the "host" (test process).
        "ANTHROPIC_AUTH_TOKEN": "sk-ant-stub",
        "ANTHROPIC_BASE_URL": "https://api.anthropic.example",
        "ANTHROPIC_API_KEY": "sk-ant-api-stub",
        "OPENAI_API_KEY": "sk-oai-stub",
        "OPENAI_BASE_URL": "https://gateway.example",
        "OPENROUTER_API_KEY": "sk-or-stub",
    }

    with patch.dict(os.environ, {}, clear=False):
        _clear_phase6_auth_env()
        for k, v in overrides.items():
            os.environ[k] = v

        # Re-import docker_manager so module-level os.getenv() reads (which build
        # _PASSTHROUGH_BY_CLI and SUBAGENT_CLI) pick up the new env.
        import docker_manager
        importlib.reload(docker_manager)

        client, fake_container = _build_mock_docker_client()
        with patch("docker_manager.get_docker_client", return_value=client):
            docker_manager._create_container("test-chat", "owui-chat-test")

        # Capture the environment dict from containers.create kwargs (not .run —
        # `.run` is the ephemeral mkdir shim; the actual sandbox uses .create).
        assert client.containers.create.call_count == 1, (
            "expected exactly one containers.create() invocation"
        )
        env_dict = client.containers.create.call_args.kwargs["environment"]

        # Active allowlist landed.
        for key in expected_keys:
            assert key in env_dict, (
                f"{cli}: expected {key} in extra_env, got keys={sorted(env_dict)}"
            )

        # Other CLIs' allowlists did NOT bleed.
        for key in forbidden_keys:
            assert key not in env_dict, (
                f"{cli}: {key} leaked into extra_env (Pitfall 1 — auth bleed). "
                f"Active allowlist must be _PASSTHROUGH_BY_CLI[{cli!r}] only."
            )

        # SUBAGENT_CLI itself always lands (Phase 4 invariant — Phase 7 .bashrc
        # autostart needs it).
        assert env_dict.get("SUBAGENT_CLI") == cli

        # OPENCODE_CONFIG pin contract (Plan 06-01 Edit 1c — ROADMAP success #2).
        # For opencode: must equal "/tmp/opencode.json" so docker exec subprocesses
        # inherit it. For other runtimes: must be ABSENT (no spurious env).
        if expected_opencode_config is None:
            assert "OPENCODE_CONFIG" not in env_dict, (
                f"{cli}: OPENCODE_CONFIG should not be set for non-opencode "
                f"runtime, got {env_dict.get('OPENCODE_CONFIG')!r}"
            )
        else:
            assert env_dict.get("OPENCODE_CONFIG") == expected_opencode_config, (
                f"{cli}: expected OPENCODE_CONFIG={expected_opencode_config!r} "
                f"(so `docker exec opencode ...` inherits the config path and "
                f"never falls back to ~/.local/share/opencode/auth.json — "
                f"Pitfall 7), got {env_dict.get('OPENCODE_CONFIG')!r}"
            )

        # Defensive scrub of OpenCode auth.json was attempted (Plan 06-01 D4).
        assert fake_container.exec_run.call_count >= 1, (
            "expected the auth.json scrub exec_run call"
        )
        scrub_call_args = [
            call.args[0] for call in fake_container.exec_run.call_args_list
        ]
        assert any(
            "rm -f /home/assistant/.local/share/opencode/auth.json" in arg
            for arg in scrub_call_args
        ), f"defensive scrub call not found in exec_run history: {scrub_call_args}"
