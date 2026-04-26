# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Phase 9.1 — Adapter-level real-CLI smoke tests against a mock LLM.

Closes audit concern #1 from `.planning/milestones/v0.9.2.1-AUDIT.md`:

    "tests/orchestrator/test_sub_agent_dispatch.py mocks cli_runtime.dispatch
     as AsyncMock... No real subprocess fork, no real CLI binary invoked."

This file does the opposite. For each of the three supported CLIs
(claude, codex, opencode) it:

  1. Spins up the workspace Docker image (the one that ships the binary).
  2. Starts a sidecar container running tests/orchestrator/mock_llm_server.py
     so the CLI hits a deterministic local endpoint instead of api.* .
  3. Executes the real CLI with the argv the adapter would build, capturing
     stdout/stderr/returncode.
  4. Feeds the captured stream into the adapter's parse_result() and asserts
     the SubAgentResult shape (text non-empty, is_error False, rc 0).

Gating: skipped unless RUN_LIVE_CLI=1 is exported. This is intentional —
the suite needs Docker, pulls/builds a 9 GB image, and takes ~30s/CLI.
The audit explicitly recommended "Optional CI nightly via RUN_LIVE_CLI=1"
(see audit "Recommended follow-up phases" table).

Other env knobs:
  WORKSPACE_IMAGE  Docker image with claude/codex/opencode on PATH
                   (default: open-computer-use:phase7-test)
  MOCK_PORT        Port the sidecar exposes inside the docker network
                   (default: 18080)

Run locally:
  RUN_LIVE_CLI=1 pytest tests/orchestrator/test_cli_adapters_live.py -v -s
"""

import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------

RUN_LIVE = os.environ.get("RUN_LIVE_CLI", "").strip() in ("1", "true", "yes")
WORKSPACE_IMAGE = os.environ.get("WORKSPACE_IMAGE", "open-computer-use:phase7-test")
MOCK_PORT_DEFAULT = int(os.environ.get("MOCK_PORT", "18080"))

pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="Live CLI smoke is opt-in; export RUN_LIVE_CLI=1 to enable.",
)


# ---------------------------------------------------------------------------
# Adapter import (re-uses the production adapters as the parser SUT)
# ---------------------------------------------------------------------------

_SERVER_DIR = Path(__file__).resolve().parent.parent.parent / "computer-use-server"
sys.path.insert(0, str(_SERVER_DIR))


# ---------------------------------------------------------------------------
# Docker plumbing
# ---------------------------------------------------------------------------

NETWORK_NAME = f"ocu-livecli-{uuid.uuid4().hex[:8]}"
MOCK_NAME = f"ocu-mock-llm-{uuid.uuid4().hex[:8]}"
MOCK_HOSTNAME = "mock-llm"  # name CLIs reach inside the docker network


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _docker(*args: str, check: bool = True, capture: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )


def _image_exists(image: str) -> bool:
    res = _docker("image", "inspect", image, check=False)
    return res.returncode == 0


def _wait_mock_healthy(port: int, timeout_s: float = 15.0) -> None:
    """Wait for the sidecar's /healthz to respond from the host."""
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except OSError as e:
            last_err = e
            time.sleep(0.3)
    raise RuntimeError(f"mock-llm did not become reachable on 127.0.0.1:{port}: {last_err}")


@pytest.fixture(scope="module")
def docker_env() -> dict:
    """Create a docker network + start the mock LLM sidecar inside it.

    Yields a dict with `network`, `mock_host` (the DNS name CLIs use), and
    `mock_port_internal` (the port inside the network).

    Tears everything down on exit.
    """
    if not _have("docker"):
        pytest.skip("docker not installed")
    if not _image_exists(WORKSPACE_IMAGE):
        pytest.skip(
            f"workspace image '{WORKSPACE_IMAGE}' not present locally; "
            "set WORKSPACE_IMAGE=<tag> or build with "
            "`docker build --platform linux/amd64 -t open-computer-use:phase7-test .`"
        )

    # Free a host port for the readiness probe (sidecar publishes mock port).
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host_probe_port = sock.getsockname()[1]
    sock.close()

    mock_src = Path(__file__).resolve().parent / "mock_llm_server.py"
    assert mock_src.is_file(), f"mock server source missing: {mock_src}"

    _docker("network", "create", NETWORK_NAME)

    try:
        _docker(
            "run", "-d", "--rm",
            "--platform", "linux/amd64",
            "--name", MOCK_NAME,
            "--hostname", MOCK_HOSTNAME,
            "--network", NETWORK_NAME,
            "-p", f"{host_probe_port}:{MOCK_PORT_DEFAULT}",
            "-v", f"{mock_src}:/srv/mock_llm_server.py:ro",
            "python:3.12-slim",
            "python3", "/srv/mock_llm_server.py",
            "--host", "0.0.0.0", "--port", str(MOCK_PORT_DEFAULT),
            timeout=120,  # image pull on first run
        )
        _wait_mock_healthy(host_probe_port)
        yield {
            "network": NETWORK_NAME,
            "mock_host": MOCK_HOSTNAME,
            "mock_port_internal": MOCK_PORT_DEFAULT,
            "mock_url": f"http://{MOCK_HOSTNAME}:{MOCK_PORT_DEFAULT}",
        }
    finally:
        # Capture mock logs on failure for postmortem.
        logs = _docker("logs", MOCK_NAME, check=False)
        if logs.stdout or logs.stderr:
            print("--- mock-llm container logs ---", file=sys.stderr)
            print(logs.stdout, file=sys.stderr)
            print(logs.stderr, file=sys.stderr)
        _docker("rm", "-f", MOCK_NAME, check=False)
        _docker("network", "rm", NETWORK_NAME, check=False)


def _run_cli_in_workspace(
    *,
    network: str,
    image: str,
    env: dict[str, str],
    setup_script: str,
    argv: list[str],
    timeout_s: int = 90,
) -> tuple[str, str, int]:
    """Run a CLI inside a fresh workspace container.

    setup_script: shell snippet executed before argv (e.g. render config).
    argv:        the CLI argv list (will be shell-quoted).

    Returns (stdout, stderr, returncode) as captured by the outer subprocess.
    """
    env_args: list[str] = []
    for k, v in env.items():
        env_args += ["-e", f"{k}={v}"]

    quoted_cli = " ".join(shlex.quote(part) for part in argv)
    full_script = f"set -e\n{setup_script}\nexec {quoted_cli}\n"

    res = subprocess.run(
        [
            "docker", "run", "--rm",
            "--platform", "linux/amd64",
            "--network", network,
            "--user", "assistant",
            "--entrypoint", "bash",
            *env_args,
            image,
            "-lc", full_script,
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return res.stdout, res.stderr, res.returncode


# ---------------------------------------------------------------------------
# Per-CLI live smoke
# ---------------------------------------------------------------------------

def _shared_assertions(result, *, cli_name: str) -> None:
    """Common SubAgentResult invariants every adapter must satisfy."""
    assert result.returncode == 0, (
        f"{cli_name}: non-zero rc {result.returncode!r}, "
        f"text={result.text!r}"
    )
    assert result.is_error is False, f"{cli_name}: is_error=True, text={result.text!r}"
    assert result.text and result.text.strip(), f"{cli_name}: empty text"


def test_claude_live_against_mock(docker_env):
    """claude --print hits mock /v1/messages, parser surfaces the completion."""
    from cli_adapters.claude import ClaudeAdapter

    adapter = ClaudeAdapter()
    argv = adapter.build_argv(
        task="Say hello.",
        system_prompt="You are a test stub.",
        model="claude-sonnet-4-6",
        max_turns=1,
        timeout_s=60,
    )

    stdout, stderr, rc = _run_cli_in_workspace(
        network=docker_env["network"],
        image=WORKSPACE_IMAGE,
        env={
            "ANTHROPIC_BASE_URL": docker_env["mock_url"],
            "ANTHROPIC_API_KEY": "sk-mock",
            "ANTHROPIC_AUTH_TOKEN": "sk-mock",
        },
        setup_script="",  # no config file needed; env is enough
        argv=argv,
        timeout_s=60,
    )

    print(f"[claude] rc={rc}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}", file=sys.stderr)
    result = adapter.parse_result(stdout, stderr, rc)
    _shared_assertions(result, cli_name="claude")
    assert "Hello from mock LLM" in result.text, (
        f"claude: completion text not surfaced through parser: {result.text!r}"
    )


def test_codex_live_against_mock(docker_env):
    """codex exec hits mock /v1/responses (wire_api='responses')."""
    from cli_adapters.codex import CodexAdapter

    adapter = CodexAdapter()
    argv = adapter.build_argv(
        task="Say hello.",
        system_prompt="You are a test stub.",
        model="gpt-5-codex",
        max_turns=1,
        timeout_s=60,
    )

    # Render ~/.codex/config.toml. Two changes vs the production entrypoint:
    #   - Top-level `model_provider = "mock-gateway"` so codex actually USES
    #     the custom provider (the entrypoint heredoc declares the block but
    #     never selects it; the production assumption is that operators flip
    #     it themselves — fine for real api.openai.com gateways, NOT fine for
    #     a hermetic mock). This gap is now flagged in the audit.
    #   - Same [model_providers.<name>] shape as production.
    config_toml = (
        'model_provider = "mock-gateway"\n'
        '\n'
        '[model_providers.mock-gateway]\n'
        'name = "mock-gateway"\n'
        f'base_url = "{docker_env["mock_url"]}/v1"\n'
        'env_key = "OPENAI_API_KEY"\n'
        'wire_api = "responses"\n'
        'requires_openai_auth = true\n'
    )

    # codex needs the --cd workdir to exist. The argv from the adapter
    # already injects /tmp/codex-agents-<uuid> via --cd; create it here.
    # Extract the workdir from argv to keep the test in lockstep with the
    # adapter shape rather than guessing.
    cd_idx = argv.index("--cd")
    workdir = argv[cd_idx + 1]

    setup = (
        f"mkdir -p ~/.codex {shlex.quote(workdir)}\n"
        f"cat > ~/.codex/config.toml <<'CFGEOF'\n{config_toml}CFGEOF\n"
    )

    # No argv mutation — provider selection lives in config.toml above.
    argv_with_provider = list(argv)

    stdout, stderr, rc = _run_cli_in_workspace(
        network=docker_env["network"],
        image=WORKSPACE_IMAGE,
        env={
            "OPENAI_API_KEY": "sk-mock",
            "OPENAI_BASE_URL": f"{docker_env['mock_url']}/v1",
        },
        setup_script=setup,
        argv=argv_with_provider,
        timeout_s=90,
    )

    print(f"[codex] rc={rc}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}", file=sys.stderr)
    result = adapter.parse_result(stdout, stderr, rc)
    _shared_assertions(result, cli_name="codex")
    assert "Hello from mock LLM" in result.text, (
        f"codex: completion text not surfaced through parser: {result.text!r}"
    )
    # Codex always renders cost as None per Pitfall 4 — guard the contract.
    assert result.cost_usd is None, f"codex: cost_usd should be None, got {result.cost_usd!r}"


def test_opencode_live_against_mock(docker_env):
    """opencode run hits mock /v1/chat/completions via custom openai-compat provider."""
    from cli_adapters.opencode import OpenCodeAdapter

    adapter = OpenCodeAdapter()
    # provider/model — the resolver expands aliases before reaching the
    # adapter, but here we pass a fully-qualified id directly.
    argv = adapter.build_argv(
        task="Say hello.",
        system_prompt="You are a test stub.",
        model="mock/mock-chat",
        max_turns=1,
        timeout_s=60,
    )

    # opencode 1.14.25 schema: top-level key is `provider` (singular).
    # Production Dockerfile writes `providers` (plural) — that is BROKEN
    # against the current opencode version and is now flagged in the audit
    # as a real config bug, not just "minimal viable".
    opencode_cfg = json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "mock": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Mock OpenAI-compatible gateway",
                "options": {
                    "baseURL": f"{docker_env['mock_url']}/v1",
                    "apiKey": "sk-mock",
                },
                "models": {
                    "mock-chat": {"name": "Mock Chat"},
                },
            },
        },
        "model": "mock/mock-chat",
    }, indent=2)

    setup = (
        "cat > /tmp/opencode.json <<'CFGEOF'\n"
        f"{opencode_cfg}\n"
        "CFGEOF\n"
        "export OPENCODE_CONFIG=/tmp/opencode.json\n"
    )

    stdout, stderr, rc = _run_cli_in_workspace(
        network=docker_env["network"],
        image=WORKSPACE_IMAGE,
        env={
            "OPENAI_API_KEY": "sk-mock",
        },
        setup_script=setup,
        argv=argv,
        timeout_s=90,
    )

    print(f"[opencode] rc={rc}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}", file=sys.stderr)
    result = adapter.parse_result(stdout, stderr, rc)
    _shared_assertions(result, cli_name="opencode")
    assert "Hello from mock LLM" in result.text, (
        f"opencode: completion text not surfaced through parser: {result.text!r}"
    )


# ---------------------------------------------------------------------------
# Regression guards for the Dockerfile-rendered configs (Phase 9.2 fixes)
# ---------------------------------------------------------------------------
#
# The three tests above use TEST-SIDE hand-rolled configs, so they pass even
# when the production Dockerfile heredoc is broken. The two tests below run
# the actual `/home/assistant/.entrypoint.sh` and then assert the rendered
# files are syntactically valid for the CLI version that ships in the image.
#
# These caught the two bugs Phase 9.2 fixed:
#   - opencode 1.14.25 schema requires top-level "provider" (singular);
#     the heredoc used to write "providers" -> CLI rejected on load.
#   - codex never set top-level `model_provider = "custom"` -> the
#     [model_providers.custom] block was dead config; OPENAI_BASE_URL
#     traffic still went to api.openai.com.

def test_opencode_entrypoint_renders_valid_config():
    """Run the production entrypoint with SUBAGENT_CLI=opencode, then assert
    `opencode --help` succeeds (which it doesn't if the config schema is
    rejected — schema validation runs on every invocation)."""
    if not _have("docker"):
        pytest.skip("docker not installed")
    if not _image_exists(WORKSPACE_IMAGE):
        pytest.skip(f"workspace image '{WORKSPACE_IMAGE}' not present locally")

    res = subprocess.run(
        [
            "docker", "run", "--rm",
            "--platform", "linux/amd64",
            "-e", "SUBAGENT_CLI=opencode",
            "-e", "OPENROUTER_API_KEY=sk-or-stub",
            "-e", "OPENAI_API_KEY=sk-stub",
            "-e", "ANTHROPIC_API_KEY=sk-stub",
            "--entrypoint", "bash",
            "--user", "assistant",
            WORKSPACE_IMAGE,
            "-lc",
            # Run the real entrypoint to render /tmp/opencode.json. Note:
            # the entrypoint marker-gate writes /tmp/opencode.json only
            # when SUBAGENT_CLI=opencode AND the marker is absent (both
            # true here). Then ask opencode to load+validate the config —
            # `opencode --help` triggers config schema validation on every
            # invocation, so an invalid rendered config will exit non-zero
            # with "Configuration is invalid" / "Unrecognized key".
            #
            # CRITICAL: no pipes (would mask exit code) and no `head` (same).
            # Capture combined stdout+stderr by redirecting 2>&1 inside the
            # script so subprocess.run sees the real opencode rc.
            "set -e; "
            "/home/assistant/.entrypoint.sh true >/tmp/entrypoint.log 2>&1 || "
            "  { echo 'ENTRYPOINT FAILED'; cat /tmp/entrypoint.log; exit 1; }; "
            "export OPENCODE_CONFIG=/tmp/opencode.json; "
            "echo '--- rendered config ---'; cat /tmp/opencode.json; "
            "echo '--- opencode --help ---'; "
            "opencode --help 2>&1; "
            "echo \"--- opencode rc=$? ---\"",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(
        f"[opencode-entrypoint] rc={res.returncode}\nOUT:\n{res.stdout}\n"
        f"ERR:\n{res.stderr}",
        file=sys.stderr,
    )
    assert res.returncode == 0, (
        f"docker run failed (rc={res.returncode}); stderr:\n{res.stderr}"
    )
    assert "command not found" not in res.stdout, (
        f"opencode binary not on PATH inside test shell:\n{res.stdout}"
    )
    assert "ENTRYPOINT FAILED" not in res.stdout, (
        f"entrypoint script failed:\n{res.stdout}"
    )
    assert "Unrecognized key" not in res.stdout, (
        f"opencode rejected the rendered config:\n{res.stdout}"
    )
    assert "Configuration is invalid" not in res.stdout, (
        f"opencode reported invalid config:\n{res.stdout}"
    )
    # Positive assertion: --help only prints its banner if config loaded.
    assert "opencode run" in res.stdout, (
        f"opencode --help did not produce its usage banner:\n{res.stdout}"
    )


def test_codex_entrypoint_selects_custom_provider():
    """Run the production entrypoint with OPENAI_BASE_URL set, then assert
    the rendered config has top-level `model_provider = "custom"` so the
    custom block is actually used (not dead config)."""
    if not _have("docker"):
        pytest.skip("docker not installed")
    if not _image_exists(WORKSPACE_IMAGE):
        pytest.skip(f"workspace image '{WORKSPACE_IMAGE}' not present locally")

    res = subprocess.run(
        [
            "docker", "run", "--rm",
            "--platform", "linux/amd64",
            "-e", "SUBAGENT_CLI=codex",
            "-e", "OPENAI_API_KEY=sk-stub",
            "-e", "OPENAI_BASE_URL=http://example.invalid/v1",
            "--entrypoint", "bash",
            "--user", "assistant",
            WORKSPACE_IMAGE,
            "-lc",
            # Use && so a failing entrypoint short-circuits the cat — otherwise
            # an empty config.toml would still pass the rc==0 check below.
            # Stderr is captured (not redirected to /dev/null) so the assertion
            # message can surface entrypoint diagnostics on failure.
            "/home/assistant/.entrypoint.sh true >/dev/null && "
            "cat /home/assistant/.codex/config.toml",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(
        f"[codex-entrypoint] rc={res.returncode}\nOUT:\n{res.stdout}\nERR:\n{res.stderr}",
        file=sys.stderr,
    )
    assert res.returncode == 0, (
        f"entrypoint+cat failed (rc={res.returncode}):\nSTDERR:\n{res.stderr}"
    )
    assert 'model_provider = "custom"' in res.stdout, (
        "Dockerfile heredoc must set top-level model_provider so the custom "
        "block is actually selected. Without it, OPENAI_BASE_URL traffic still "
        "goes to api.openai.com.\nRendered config:\n" + res.stdout
    )
    assert "[model_providers.custom]" in res.stdout, (
        "Custom provider block missing from rendered config:\n" + res.stdout
    )
