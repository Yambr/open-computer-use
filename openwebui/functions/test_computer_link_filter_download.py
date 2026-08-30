# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""Unit tests for the outlet download-marker mint (#191, ADR-0034, item B).

The outlet rewrites the model's [[ocu-download:NAME]] markers into markdown
download links under DOWNLOAD_BASE_URL. Fable's two load-bearing assertions plus
the role-gating and base-unavailable guards.

The link SHAPE is /download/{scope}/{filename} (ADR-0035). Every assertion here
that names a URL names both segments, because an earlier revision of this file
pinned the one-segment form the pane retired: the tests were green, the mint was
wrong, and the only way to notice was to fetch the minted URL. A shape this file
pins is a shape the pane must serve, so `test_never_mints_the_retired_one_segment_form`
states that requirement directly rather than leaving it implied by the others.

Run: python3 -m pytest openwebui/functions/test_computer_link_filter_download.py -v
"""

import importlib.util
import os

import pytest

_FILTER_PATH = os.path.join(os.path.dirname(__file__), "computer_link_filter.py")

# The scope segment the fleet runs with: the base storage handle the portal mints
# into the embed token, which is what the pane's session claim carries.
_SCOPE = "fs-fleet"


def _filter(base: str = "http://localhost:3000", scope: str = _SCOPE):
    spec = importlib.util.spec_from_file_location("clf_download", _FILTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    f = mod.Filter()
    f.valves.DOWNLOAD_BASE_URL = base
    f.valves.DOWNLOAD_SCOPE = scope
    return f


def _assistant(content: str) -> dict:
    return {"messages": [{"role": "assistant", "content": content}]}


def test_exact_mint_roundtrip_and_idempotence():
    """A1: the marker mints an outlet-based link with parens+spaces encoded, and
    a second outlet pass is the identity (marker consumed)."""
    f = _filter()
    out = f.outlet(_assistant("Saved it.\n[[ocu-download:q1 report(final).docx]]"))
    c = out["messages"][0]["content"]
    assert (
        "[q1 report(final).docx](http://localhost:3000/download/fs-fleet/"
        "q1%20report%28final%29.docx)"
    ) in c, c
    assert "[[ocu-download:" not in c
    # idempotent: re-render does not double-decorate
    out2 = f.outlet(_assistant(c))
    assert out2["messages"][0]["content"] == c


def test_never_mints_the_retired_one_segment_form():
    """The shape is the whole point: /download/{scope}/{filename}.

    parseDownloadPath in the pane returns null for anything else, the retired
    /download/{filename} form included, so a one-segment link is a 404 and the
    file never reaches the user. This asserts the scope segment is PRESENT and
    sits between the prefix and the name -- not merely that some scope string
    appears somewhere in the URL, which a link ending
    .../download/report.docx?scope=fs-fleet would also satisfy.
    """
    f = _filter()
    out = f.outlet(_assistant("[[ocu-download:report.docx]]"))
    c = out["messages"][0]["content"]
    assert "/download/fs-fleet/report.docx" in c, c
    assert "/download/report.docx" not in c, f"retired one-segment form minted: {c!r}"


def test_scope_is_percent_encoded_like_the_name():
    """Both segments are selectors the filter writes, so both are encoded.

    An unencoded handle carrying a slash would silently add a path segment and
    change which route matches; one carrying a space would break the markdown
    link. The pane decodes each segment exactly once on the raw-pathname side.
    """
    f = _filter(scope="fs fleet/x")
    out = f.outlet(_assistant("[[ocu-download:report.docx]]"))
    c = out["messages"][0]["content"]
    assert "/download/fs%20fleet%2Fx/report.docx" in c, c


def test_failclosed_traversal_and_never_scrapes_prose():
    """A2: traversal/separator markers drop to no-link, and a filename mentioned
    in prose is NEVER turned into a link (the marker is the only trigger)."""
    f = _filter()
    out = f.outlet(
        _assistant(
            "unlike report.docx which failed\n"
            "[[ocu-download:../../etc/passwd]]\n"
            "[[ocu-download:a/b.txt]]"
        )
    )
    c = out["messages"][0]["content"]
    assert "/download/" not in c, c
    assert "[[ocu-download:" not in c
    assert "](http" not in c  # prose report.docx not linked
    assert "unlike report.docx which failed" in c  # prose byte-preserved


def test_empty_marker_is_consumed_not_left_literal():
    """A2b: an EMPTY marker [[ocu-download:]] must be consumed (no link, no literal
    sentinel), not left in the chat as raw text. Regression: the regex quantifier
    was {1,255}, so the empty marker never matched and leaked the literal sentinel
    to the user -- a parity-breaking artifact. {0,255} makes it match, and the
    fail-closed empty-name branch drops it to plain (empty) text."""
    f = _filter()
    out = f.outlet(_assistant("here is your file [[ocu-download:]] enjoy"))
    c = out["messages"][0]["content"]
    assert "[[ocu-download:" not in c, f"empty marker leaked as literal: {c!r}"
    assert "/download/" not in c, f"empty marker must not mint a link: {c!r}"
    # the surrounding prose survives
    assert "here is your file" in c and "enjoy" in c


def test_user_role_marker_untouched():
    """A3: a marker in a user-role message is not minted (assistant-scoped)."""
    f = _filter()
    body = {"messages": [{"role": "user", "content": "[[ocu-download:report.docx]]"}]}
    out = f.outlet(body)
    assert out["messages"][0]["content"] == "[[ocu-download:report.docx]]"


def test_base_unavailable_degrades_to_bare_filename():
    """A4: with no configured base, the marker degrades to the bare filename as
    plain text (broken links are worse than no links)."""
    f = _filter(base="")
    out = f.outlet(_assistant("[[ocu-download:report.docx]]"))
    assert out["messages"][0]["content"] == "report.docx"


def test_scope_unavailable_degrades_to_bare_filename():
    """The same judgement as an absent base, for the same reason.

    An unset scope cannot be defaulted to a guess: the route compares the path
    scope against the session's signed claim and answers 401 on a mismatch, so a
    wrong handle is not a degraded link but an unauthorized one. Emitting the
    name as plain text says truthfully that the file is in the panel.
    """
    f = _filter(scope="")
    out = f.outlet(_assistant("[[ocu-download:report.docx]]"))
    assert out["messages"][0]["content"] == "report.docx"


def test_outlet_has_no_session_access():
    """Fable's outlet-has-no-session guard: the mint is a pure function of the
    message text + the static base valve. It makes no HTTP/list/content/cookie
    call. We assert it works with NO __user__ and NO __metadata__ (no session
    context available at all) — proving the mint never touches the attested
    plane and cannot regress into a server-side list-and-match."""
    f = _filter()
    out = f.outlet(_assistant("[[ocu-download:report.docx]]"), __user__=None, __metadata__=None)
    c = out["messages"][0]["content"]
    assert "[report.docx](http://localhost:3000/download/fs-fleet/report.docx)" in c


def test_multiple_markers_all_minted():
    """Replace-all: every valid marker in a message is minted independently."""
    f = _filter()
    out = f.outlet(
        _assistant("[[ocu-download:a.txt]] and [[ocu-download:b.pdf]]")
    )
    c = out["messages"][0]["content"]
    assert "[a.txt](http://localhost:3000/download/fs-fleet/a.txt)" in c
    assert "[b.pdf](http://localhost:3000/download/fs-fleet/b.pdf)" in c
    assert "[[ocu-download:" not in c


# --- per-chat scope resolution -------------------------------------------------
#
# The {scope} segment must equal the filesystem_id of THIS chat's pane session.
# Where the deployment derives a per-chat scope that value differs per chat, so a
# single static DOWNLOAD_SCOPE cannot be right for more than one of them. Measured
# on the stand before this landed: the link built from the base scope rendered a
# download page and returned NO BYTES, while the same file under the chat's own
# scope returned them. The GET renders either way — only the byte leg tells them
# apart, which is why these cases assert on the minted SCOPE, not on a 200.


def _filter_with_resolver(scope_or_exc, base="http://localhost:3000"):
    """A filter whose scope resolution is stubbed. Passing an Exception makes the
    resolution FAIL (as an unreachable gateway would); passing "" is the
    deployment that derives no per-chat scope."""
    f = _filter(base=base)
    f.valves.RESOLVE_SCOPE_URL = "http://gateway.invalid/"
    f.valves.RESOLVE_SCOPE_BEARER = "sk-ocu-filter-resolve-only"

    def _stub(chat_id: str):
        if isinstance(scope_or_exc, Exception):
            return None, False
        return (scope_or_exc or None), True

    f._resolve_chat_scope = _stub
    return f


def test_link_carries_the_chats_own_scope_not_the_base():
    """The defect this closes: with per-chat isolation the base scope names a tree
    the chat's file is not in, so the link resolves to nothing."""
    f = _filter_with_resolver("fs-fleet-94e885c52f5eb171")
    out = f.outlet(
        _assistant("[[ocu-download:ONLY-THIS-CHAT.txt]]"),
        __metadata__={"chat_id": "chat-a"},
    )
    c = out["messages"][0]["content"]
    assert "/download/fs-fleet-94e885c52f5eb171/ONLY-THIS-CHAT.txt" in c, c
    assert "/download/fs-fleet/ONLY-THIS-CHAT.txt" not in c, c


def test_two_chats_get_two_different_scopes():
    """Isolation means the same filename in two chats mints two different links.
    A build that resolved once and reused it would pass the case above."""
    seen = []
    for chat, scope in (("chat-a", "fs-fleet-aaa"), ("chat-b", "fs-fleet-bbb")):
        f = _filter_with_resolver(scope)
        out = f.outlet(
            _assistant("[[ocu-download:same-name.txt]]"),
            __metadata__={"chat_id": chat},
        )
        seen.append(out["messages"][0]["content"])
    assert "/download/fs-fleet-aaa/same-name.txt" in seen[0], seen[0]
    assert "/download/fs-fleet-bbb/same-name.txt" in seen[1], seen[1]


def test_no_per_chat_scope_falls_back_to_the_base_valve():
    """Known-positive control: where the deployment derives no per-chat scope the
    gateway answers with an empty effective_scope and the static valve IS correct.
    Without this, a change that always required resolution would break the
    non-isolated deployment."""
    f = _filter_with_resolver("")
    out = f.outlet(
        _assistant("[[ocu-download:report.docx]]"),
        __metadata__={"chat_id": "chat-a"},
    )
    assert "/download/fs-fleet/report.docx" in out["messages"][0]["content"]


def test_failed_resolution_mints_no_link_at_all():
    """Fail-closed: a scope we could not confirm must not be guessed from the base.
    A link with the wrong scope renders a download page and returns no bytes, which
    reads to the user as success — worse than a bare filename."""
    f = _filter_with_resolver(RuntimeError("gateway unreachable"))
    out = f.outlet(
        _assistant("[[ocu-download:report.docx]]"),
        __metadata__={"chat_id": "chat-a"},
    )
    c = out["messages"][0]["content"]
    assert "/download/" not in c, c
    assert "[[ocu-download:" not in c, c
    assert "report.docx" in c, c


def test_resolver_unconfigured_keeps_the_previous_behaviour():
    """Known-positive control: with no RESOLVE_SCOPE_URL the filter must behave
    exactly as it did before — the static valve, no resolution attempted."""
    f = _filter()  # RESOLVE_SCOPE_URL left empty
    out = f.outlet(
        _assistant("[[ocu-download:report.docx]]"),
        __metadata__={"chat_id": "chat-a"},
    )
    assert "/download/fs-fleet/report.docx" in out["messages"][0]["content"]
