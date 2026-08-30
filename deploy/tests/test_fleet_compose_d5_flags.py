# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""D5 fleet-compose flag guard (ADR-0030).

Per-chat storage isolation needs TWO compose flags to be non-vacuous:
- control runs with -derive-chat-scope, so it derives + mints a distinct scope
  per (attested owner, chat handle);
- the south filestore runs -claims-bind, so the derived claim actually binds on
  the read/write path (without it the guest's isolated claim is ignored and the
  isolation is a mirage).

These grep the shipped compose file's per-service command block. A future edit
that drops either flag REDs here before it reaches a live J6 run.
"""

import re
from pathlib import Path

import yaml

_COMPOSE = (
    Path(__file__).resolve().parents[1] / "fleet" / "docker-compose.fleet.yml"
)


def _service_argv(service: str) -> list:
    doc = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    svc = doc["services"][service]
    cmd = svc.get("command", [])
    if isinstance(cmd, str):
        return cmd.split()
    return [str(x) for x in cmd]


def test_control_argv_has_derive_chat_scope():
    argv = _service_argv("control")
    joined = " ".join(argv)
    assert "-derive-chat-scope" in joined, (
        "control argv must carry -derive-chat-scope for D5 per-chat isolation; "
        f"got {argv}"
    )
    # The flag ships enabled by default (env-overridable), not turned off.
    flag = next(a for a in argv if a.startswith("-derive-chat-scope"))
    assert re.search(r"-derive-chat-scope=\$\{OCU_DERIVE_CHAT_SCOPE:-true\}", flag), (
        f"-derive-chat-scope must default to true (env-overridable); got {flag!r}"
    )


def test_filestore_argv_has_claims_bind():
    argv = _service_argv("filestore")
    assert "-claims-bind" in argv, (
        "filestore argv must carry -claims-bind so the derived scope claim binds "
        f"on the south path (else D5 isolation is vacuous); got {argv}"
    )


def test_control_base_scope_stays_fs_fleet():
    # The BASE the derivation suffixes is still fs-fleet (filesystem-id on filestore).
    argv = _service_argv("filestore")
    assert any("fs-fleet" in a for a in argv), (
        f"the base filesystem scope fs-fleet must remain in filestore argv; got {argv}"
    )
