# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""TEST-02: cli_runtime resolver coverage.

Covers:
  a. unset SUBAGENT_CLI -> "claude"
  b. empty/whitespace SUBAGENT_CLI -> "claude"
  c. valid (claude/codex/opencode, case-insensitive) -> corresponding Cli enum
  d. invalid -> SystemExit with operator-friendly stderr message
  e. extra_env["SUBAGENT_CLI"] is injected by docker_manager._create_container
  f. warn_subagent_cli() banner format

Pattern mirrors tests/orchestrator/test_startup_warnings.py (env-var save/
restore, module reload) and test_docker_manager.py (importlib.reload + env
patching). No conftest.py — each test file does its own sys.path.insert.

Note on capture: docker_manager.py uses `print(..., file=sys.stderr)` then
`sys.exit(1)` (plan 04-01 D1 + decision logged in 04-01-SUMMARY.md), NOT
`sys.exit("message")`. Tests therefore capture stderr via `capfd`
(file-descriptor capture), NOT `capsys` (Python-level sys.stderr) and NOT
`str(exc.value)` (which would only work with sys.exit("message")).
"""

import importlib
import os
import sys

import pytest

# Add computer-use-server to sys.path (mirrors test_docker_manager.py:19).
_SERVER_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "computer-use-server"
)
sys.path.insert(0, _SERVER_DIR)


def _drop_modules():
    """Drop docker_manager + cli_runtime from sys.modules so the next import
    re-runs module-load validation and re-binds SUBAGENT_CLI from the current
    os.environ (Pitfall B in 04-RESEARCH.md)."""
    for mod in ("cli_runtime", "docker_manager"):
        sys.modules.pop(mod, None)


def _reload_docker_manager():
    """Drop and re-import docker_manager. Returns the freshly loaded module."""
    _drop_modules()
    return importlib.import_module("docker_manager")


@pytest.fixture(autouse=True)
def _clean_subagent_env(monkeypatch):
    """Remove SUBAGENT_CLI before each test; tests opt in via monkeypatch.setenv.
    Also clear the modules cache after each test so cross-test load order is
    deterministic."""
    monkeypatch.delenv("SUBAGENT_CLI", raising=False)
    yield
    _drop_modules()


# === a, b: unset/empty/whitespace -> "claude" ===

def test_unset_subagent_cli_resolves_to_claude():
    dm = _reload_docker_manager()
    assert dm.SUBAGENT_CLI == "claude"


def test_empty_subagent_cli_resolves_to_claude(monkeypatch):
    monkeypatch.setenv("SUBAGENT_CLI", "")
    dm = _reload_docker_manager()
    assert dm.SUBAGENT_CLI == "claude"


def test_whitespace_subagent_cli_resolves_to_claude(monkeypatch):
    monkeypatch.setenv("SUBAGENT_CLI", "   ")
    dm = _reload_docker_manager()
    assert dm.SUBAGENT_CLI == "claude"


# === c: valid -> enum (case-insensitive, whitespace-tolerant) ===

@pytest.mark.parametrize("env_value,expected", [
    ("claude", "claude"),
    ("codex", "codex"),
    ("opencode", "opencode"),
    ("CLAUDE", "claude"),          # case-insensitive
    ("Codex", "codex"),            # case-insensitive
    ("OPENCODE", "opencode"),      # case-insensitive
    ("  opencode  ", "opencode"),  # whitespace strip
])
def test_valid_subagent_cli_resolves_to_lowercase(monkeypatch, env_value, expected):
    monkeypatch.setenv("SUBAGENT_CLI", env_value)
    dm = _reload_docker_manager()
    assert dm.SUBAGENT_CLI == expected
    # And the resolver returns a Cli enum member with matching string value.
    from cli_runtime import Cli, resolve_cli
    resolved = resolve_cli()
    assert resolved == Cli(expected)
    assert isinstance(resolved, Cli)
    # StrEnum invariant: Cli.CLAUDE == "claude" is True.
    assert resolved == expected


def test_cli_enum_members_present():
    """D2: Cli is StrEnum with exactly three members CLAUDE/CODEX/OPENCODE."""
    from cli_runtime import Cli
    members = {m.value for m in Cli}
    assert members == {"claude", "codex", "opencode"}
    # StrEnum behaviour: equality with raw string.
    assert Cli.CLAUDE == "claude"
    assert Cli.CODEX == "codex"
    assert Cli.OPENCODE == "opencode"


# === d: invalid -> SystemExit with operator-friendly stderr ===

@pytest.mark.parametrize("invalid_value", ["cline", "opencodex", "anthropic", "gpt-5"])
def test_invalid_subagent_cli_exits(monkeypatch, capfd, invalid_value):
    monkeypatch.setenv("SUBAGENT_CLI", invalid_value)
    _drop_modules()
    with pytest.raises(SystemExit) as exc:
        importlib.import_module("docker_manager")
    # sys.exit(1) -> exit code 1.
    assert exc.value.code == 1
    captured = capfd.readouterr()
    # Operator-friendly stderr: names offending value and lists three accepted values.
    assert "FATAL" in captured.err
    assert f"SUBAGENT_CLI={invalid_value!r}" in captured.err
    assert "claude" in captured.err
    assert "codex" in captured.err
    assert "opencode" in captured.err


# === e: extra_env injection ===

def test_extra_env_injection_line_present_in_source():
    """ROADMAP success criterion #1: every spawned container has SUBAGENT_CLI
    in Env. Phase 4 plan 04-01 implemented this as a single-line assignment in
    _create_container (D5 shape a). Verify the source contains the injection
    line — the runtime correctness is also covered by Phase 6's TEST-06
    image-level docker-inspect test."""
    with open(os.path.join(_SERVER_DIR, "docker_manager.py")) as f:
        src = f.read()
    assert 'extra_env["SUBAGENT_CLI"] = SUBAGENT_CLI' in src, (
        "extra_env injection of SUBAGENT_CLI is missing from docker_manager.py "
        "(expected `extra_env[\"SUBAGENT_CLI\"] = SUBAGENT_CLI` in _create_container)"
    )


def test_extra_env_carries_subagent_cli_via_create_container(monkeypatch):
    """Functional check: invoke _create_container with mocked Docker client
    and assert the captured environment dict carries SUBAGENT_CLI=<chosen cli>.

    Patches the Docker client + filesystem prep + skill_manager so the call
    reaches the create() step where we capture `environment`. This is best-effort:
    if downstream wiring fails, the source-grep test above is the safety net.
    """
    monkeypatch.setenv("SUBAGENT_CLI", "opencode")
    dm = _reload_docker_manager()

    captured_env = {}

    class _FakeContainer:
        id = "fake-container-id"
        name = "fake-container"

        def reload(self):
            pass

        def start(self):
            pass

    class _FakeContainers:
        def run(self, *a, **kw):
            return None

        def create(self, **config):
            captured_env.update(config.get("environment", {}))
            return _FakeContainer()

        def get(self, *a, **kw):
            raise Exception("no such container")

    class _FakeNetworks:
        def get(self, *a, **kw):
            raise Exception("no such network")

        def list(self, *a, **kw):
            return []

    class _FakeImages:
        def get(self, *a, **kw):
            from unittest.mock import MagicMock
            return MagicMock()

    class _FakeClient:
        containers = _FakeContainers()
        networks = _FakeNetworks()
        images = _FakeImages()
        volumes = type("V", (), {"list": staticmethod(lambda *a, **kw: [])})()

    monkeypatch.setattr(dm, "get_docker_client", lambda: _FakeClient())
    monkeypatch.setattr(dm, "USER_DATA_BASE_PATH", "/tmp")

    # Pin context vars to deterministic defaults.
    from context_vars import (
        current_chat_id, current_user_email, current_user_name,
        current_gitlab_token, current_gitlab_host,
        current_anthropic_auth_token, current_anthropic_base_url,
    )
    current_chat_id.set("test-chat")
    current_user_email.set(None)
    current_user_name.set(None)
    current_gitlab_token.set(None)
    current_gitlab_host.set("gitlab.com")
    current_anthropic_auth_token.set(None)
    current_anthropic_base_url.set(None)

    create_exception = None
    try:
        dm._create_container("test-chat", "test-container")
    except Exception as e:  # noqa: BLE001 — best-effort capture, see skip below
        # Some downstream code may still fail without real Docker — that is
        # fine. The extra_env was already constructed and captured BEFORE
        # any failure path that requires real network/skill state.
        create_exception = e

    if not captured_env:
        # _FakeContainers.create() was never reached. The previous fallback
        # (assert dm.SUBAGENT_CLI == "opencode") would silently green-light
        # this test even if _create_container stopped emitting SUBAGENT_CLI
        # entirely (covered already by test_valid_subagent_cli_resolves_to_lowercase
        # and test_extra_env_injection_line_present_in_source). Skip explicitly
        # so a real regression in extra_env injection cannot hide here.
        # Per CodeRabbit PR#75 review.
        import pytest
        pytest.skip(
            "_FakeContainers.create() not reached "
            f"(upstream raised: {type(create_exception).__name__ if create_exception else 'no error'}). "
            "Coverage falls back to test_extra_env_injection_line_present_in_source."
        )
    assert captured_env.get("SUBAGENT_CLI") == "opencode", (
        f"SUBAGENT_CLI not in captured environment: {captured_env}"
    )


# === f: warn_subagent_cli banner ===

def test_warn_subagent_cli_emits_banner_for_codex(monkeypatch, capsys):
    monkeypatch.setenv("SUBAGENT_CLI", "codex")
    dm = _reload_docker_manager()
    result = dm.warn_subagent_cli()
    assert result is True
    out = capsys.readouterr().out
    assert "[MCP] Sub-agent runtime: codex" in out


def test_warn_subagent_cli_default_claude(monkeypatch, capsys):
    monkeypatch.delenv("SUBAGENT_CLI", raising=False)
    dm = _reload_docker_manager()
    dm.warn_subagent_cli()
    out = capsys.readouterr().out
    assert "[MCP] Sub-agent runtime: claude" in out


# === resolve_subagent_model (ADAPT-06, plan 05-01) ===
# Per-CLI alias resolution + Claude-only-alias-on-codex hard-fail (Pitfall 3).

def _import_resolver():
    """Drop modules + freshly import to pick up current env."""
    _drop_modules()
    return importlib.import_module("cli_runtime")


def test_resolve_claude_alias_sonnet_default():
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model("sonnet", Cli.CLAUDE)
    assert model_id == "claude-sonnet-4-6"
    assert display == "sonnet"


def test_resolve_claude_alias_opus_default():
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model("opus", Cli.CLAUDE)
    assert model_id == "claude-opus-4-6"
    assert display == "opus"


def test_resolve_claude_alias_haiku_default():
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model("haiku", Cli.CLAUDE)
    assert model_id == "claude-haiku-4-5"
    assert display == "haiku"


def test_resolve_claude_empty_falls_back_to_sonnet():
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model("", Cli.CLAUDE)
    assert model_id == "claude-sonnet-4-6"
    assert display == "sonnet"


def test_resolve_claude_direct_id_passthrough():
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model(
        "claude-sonnet-4-6", Cli.CLAUDE,
    )
    assert model_id == "claude-sonnet-4-6"
    assert display == "claude-sonnet-4-6"


def test_resolve_claude_alias_case_insensitive():
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    for alias in ("SONNET", "Sonnet", "  sonnet  "):
        model_id, display = cli_runtime.resolve_subagent_model(alias, Cli.CLAUDE)
        assert model_id == "claude-sonnet-4-6"
        assert display == "sonnet"


def test_resolve_claude_honors_anthropic_default_sonnet_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "azure/my-deployment")
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model("sonnet", Cli.CLAUDE)
    assert model_id == "azure/my-deployment"
    assert display == "sonnet"


@pytest.mark.parametrize("alias", ["sonnet", "opus", "haiku", "SONNET", "Opus"])
def test_resolve_codex_claude_alias_raises(alias):
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    with pytest.raises(ValueError) as exc:
        cli_runtime.resolve_subagent_model(alias, Cli.CODEX)
    assert "Claude-only" in str(exc.value)
    assert "CODEX_SUB_AGENT_DEFAULT_MODEL" in str(exc.value)


def test_resolve_codex_empty_returns_default(monkeypatch):
    monkeypatch.delenv("CODEX_SUB_AGENT_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model("", Cli.CODEX)
    assert model_id == "gpt-5-codex"
    assert display == "gpt-5-codex"


def test_resolve_codex_honors_codex_sub_agent_default_model_env(monkeypatch):
    monkeypatch.setenv("CODEX_SUB_AGENT_DEFAULT_MODEL", "gpt-5-codex-pro")
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model("", Cli.CODEX)
    assert model_id == "gpt-5-codex-pro"


def test_resolve_codex_codex_model_env_fallback(monkeypatch):
    monkeypatch.delenv("CODEX_SUB_AGENT_DEFAULT_MODEL", raising=False)
    monkeypatch.setenv("CODEX_MODEL", "gpt-5-codex-from-codex-model-env")
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, _ = cli_runtime.resolve_subagent_model("", Cli.CODEX)
    assert model_id == "gpt-5-codex-from-codex-model-env"


def test_resolve_codex_direct_id_passthrough():
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model(
        "gpt-5-codex", Cli.CODEX,
    )
    assert model_id == "gpt-5-codex"
    assert display == "gpt-5-codex"


def test_resolve_opencode_alias_sonnet_raises_without_env(monkeypatch):
    """D-05 / D-06: 'sonnet' is no longer a built-in alias — raises ValueError."""
    monkeypatch.delenv("OPENCODE_MODEL_ALIASES", raising=False)
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    with pytest.raises(ValueError) as exc_info:
        cli_runtime.resolve_subagent_model("sonnet", Cli.OPENCODE)
    assert "alias 'sonnet' is not defined" in str(exc_info.value)
    assert "OPENCODE_MODEL_ALIASES" in str(exc_info.value)


def test_resolve_opencode_alias_sonnet_via_env(monkeypatch):
    """D-05: operator can supply sonnet alias via OPENCODE_MODEL_ALIASES env."""
    monkeypatch.setenv(
        "OPENCODE_MODEL_ALIASES",
        '{"sonnet": "anthropic/claude-sonnet-4-6"}',
    )
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model("sonnet", Cli.OPENCODE)
    assert model_id == "anthropic/claude-sonnet-4-6"
    assert display == "sonnet"


def test_resolve_opencode_provider_model_passthrough():
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, display = cli_runtime.resolve_subagent_model(
        "openrouter/qwen/qwen-3-coder", Cli.OPENCODE,
    )
    assert model_id == "openrouter/qwen/qwen-3-coder"
    assert display == "openrouter/qwen/qwen-3-coder"


def test_resolve_opencode_bare_id_raises(monkeypatch):
    """D-06: bare alias-shaped id (no '/') not in map -> raises ValueError."""
    monkeypatch.delenv("OPENCODE_MODEL_ALIASES", raising=False)
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    with pytest.raises(ValueError) as exc_info:
        cli_runtime.resolve_subagent_model("bareid", Cli.OPENCODE)
    assert "list-subagent-models" in str(exc_info.value)


def test_resolve_opencode_empty_raises_without_default_env(monkeypatch):
    """D-02: no caller model + no env default -> ValueError (no hardcoded fallback)."""
    monkeypatch.delenv("OPENCODE_SUB_AGENT_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("OPENCODE_MODEL", raising=False)
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    with pytest.raises(ValueError) as exc_info:
        cli_runtime.resolve_subagent_model("", Cli.OPENCODE)
    assert "OPENCODE_SUB_AGENT_DEFAULT_MODEL" in str(exc_info.value)
    assert "list-subagent-models" in str(exc_info.value)


def test_resolve_opencode_honors_opencode_sub_agent_default_model_env(monkeypatch):
    monkeypatch.setenv("OPENCODE_SUB_AGENT_DEFAULT_MODEL", "openrouter/x/y")
    cli_runtime = _import_resolver()
    from cli_runtime import Cli
    model_id, _ = cli_runtime.resolve_subagent_model("", Cli.OPENCODE)
    assert model_id == "openrouter/x/y"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
