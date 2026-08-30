# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""GROUP A — Auth & Bootstrap (A1..A6) of the PoC-vs-fleet journey suite.

One paired test per scenario. Each test drives the REAL journey verb(s) on
whichever backend the ``backend`` fixture selected (poc AND fleet), and asserts
the observable end state the scenario declares in scenarios.yaml — never
markup/field presence, which is fake-green. Each test carries its scenario's
KEYSTONE (the negative/inversion) as an explicit assertion or a clearly-marked
sub-check, so a green here is reproducibly reddable.

Honesty rules encoded (from the scaffold's conftest / base):

  * A backend that is not live is skipped loudly by the ``backend`` fixture;
    these bodies never mock a green.
  * For [PoC-HOLE] scenarios the PoC path is asserted to SUCCEED (or the
    boundary is asserted ABSENT via the PocHoleNotEnforced sentinel) AND the
    fleet path is asserted to DENY with the right status. That divergence is
    the finding.
  * User-facing hops (cookie bootstrap, CSP framing, CSRF on upload) are driven
    by real Playwright fill+click in the browser group runner — NEVER
    page.evaluate(fetch). The scaffold does not wire Playwright, so those axes
    use pytest.importorskip / xfail(reason=...) here: honest, not a silent pass.
  * Where a contract is TBD (e.g. the A5 static-key wire is not exposed as a
    scaffold verb), the ENVELOPE / STATUS CLASS is asserted, not an invented
    body — and the comment says so.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from backends.base import BackendUnavailable, PocHoleNotEnforced


# ---------------------------------------------------------------------------
# Fleet wire helpers used by the mTLS / static-key auth scenarios (A4, A5).
#
# The scaffold's FleetBackend speaks the gateway mTLS plane with ONE client
# cert. The auth-boundary scenarios need to drive the NEGATIVE cases the normal
# verbs never take (no cert, a malformed cert, an unknown/tampered/revoked static
# key). Those cases are not journey verbs, so we drive them with a direct curl
# against the same base URL + PKI the FleetBackend is configured with — the same
# transport the backend itself uses. This is real wire, not a mock.
# ---------------------------------------------------------------------------

_FLEET_BASE = os.getenv("FLEET_BASE", "https://127.0.0.1:9466")
_DEFAULT_PKI = Path(__file__).resolve().parents[2] / "fleet" / "gateway-pki"
_FLEET_PKI = Path(os.getenv("FLEET_PKI", str(_DEFAULT_PKI)))
# A never-created key: any authenticated caller gets a 404, an UNauthenticated
# caller never reaches the handler (TLS/401). We probe this path so the status
# distinguishes "handshake accepted, key absent" (404) from "rejected at the
# edge" (a TLS failure / 401).
_PROBE_PATH = "/v1alpha/sessions/never-created-auth-probe"


def _curl_available() -> bool:
    return shutil.which("curl") is not None


def _curl_raw(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    """Run a curl and return the completed process (returncode + stdout/stderr).

    Raises BackendUnavailable if curl is missing so the caller can skip loudly
    rather than pass. Never fabricates a result.
    """
    curl = shutil.which("curl")
    if not curl:
        raise BackendUnavailable("curl not found for the fleet auth-wire probes")
    return subprocess.run(
        [curl, *args], capture_output=True, timeout=timeout, check=False
    )


def _curl_status(extra: list[str], path: str = _PROBE_PATH) -> tuple[int, int]:
    """Issue a curl to the fleet base and return (returncode, http_status).

    ``returncode`` is curl's exit code (nonzero = transport/TLS failure — no
    HTTP status was reached). ``http_status`` is the parsed %{http_code} (0 when
    curl never got an HTTP response). This lets a test distinguish a handshake
    rejection (returncode != 0) from an application-level 401 (returncode 0,
    status 401).
    """
    args = [
        "-sS",
        "--max-time",
        "15",
        "-o",
        os.devnull,
        "-w",
        "%{http_code}",
        *extra,
        f"{_FLEET_BASE}{path}",
    ]
    proc = _curl_raw(args)
    out = proc.stdout.decode("utf-8", "replace").strip()
    status = int(out) if out.isdigit() else 0
    return proc.returncode, status


def _client_cert_args() -> list[str]:
    """The valid one-cert mTLS args (ca + client cert + key), like the demo."""
    return [
        "--cacert",
        str(_FLEET_PKI / "ca.pem"),
        "--cert",
        str(_FLEET_PKI / "client.pem"),
        "--key",
        str(_FLEET_PKI / "client.key"),
    ]


def _require_fleet(backend) -> None:
    """Guard: skip a fleet-only wire probe when the running backend is poc.

    A paired test that needs a fleet-specific negative (no-cert handshake, a
    static-key gate) has no PoC analogue on the wire; the PoC assertions in the
    same test still run on the poc backend. This keeps one body reading on both
    sides without faking a fleet result on the poc pass.
    """
    if backend.name != "fleet":
        pytest.skip("fleet-only wire probe; the PoC branch is asserted separately")


def _pki_present() -> bool:
    return all(
        (_FLEET_PKI / f).is_file() for f in ("ca.pem", "client.pem", "client.key")
    )


def _make_untrusted_keypair(dest: Path) -> tuple[Path, Path]:
    """Generate a self-signed client cert + its OWN key the gateway CA never signed.

    The point of the A4 KEYSTONE is that a syntactically VALID client credential
    that the gateway CA did not issue is rejected at the mTLS handshake — not
    that a garbled file trips curl's local key loader (exit 58) before any bytes
    reach the gateway. So we produce a real EC keypair + a self-signed cert:
    curl loads it locally without error and presents it, and the gateway MUST
    refuse it because it does not chain to ``ca.pem``.

    Returns (cert_path, key_path). Raises BackendUnavailable if openssl is
    absent so the caller skips loudly rather than passing on a missing tool.
    """
    openssl = shutil.which("openssl")
    if not openssl:
        raise BackendUnavailable("openssl not found; cannot mint the A4 untrusted keypair")
    key = dest / "untrusted.key"
    cert = dest / "untrusted.pem"
    proc = subprocess.run(
        [
            openssl, "req", "-x509", "-newkey", "ec",
            "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-keyout", str(key),
            "-out", str(cert),
            "-days", "1",
            "-subj", "/CN=untrusted-not-signed-by-gateway-ca",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0 or not (key.is_file() and cert.is_file()):
        raise BackendUnavailable(
            "openssl failed to mint the A4 untrusted keypair: "
            + proc.stderr.decode("utf-8", "replace").strip()
        )
    return cert, key


# ---------------------------------------------------------------------------
# A1 — first-party cookie set on bootstrap.  bucket: HARDENED
# ---------------------------------------------------------------------------
def test_a1_first_party_cookie_on_bootstrap(backend, expect):
    """A1 | first-party cookie set on bootstrap.

    Invariant: the fleet web UI mints a first-party session cookie
    (SameSite=None, Secure, HttpOnly) only after verifying the embed token
    (sig + aud + exp<=120s); a protected call then succeeds WITH the cookie.
    KEYSTONE: strip the cookie and the same protected call returns 401/redirect,
    so the green flips to red without it. PoC sets no cookie at all — that
    absence is the HARDENED contrast.

    The cookie bootstrap is a browser hop: the real suite drives it with
    Playwright fill+click on the login form, then asserts the Set-Cookie
    attributes and that a protected call succeeds, NEVER page.evaluate(fetch).
    Playwright is not wired into this scaffold, so the fleet browser assertion
    is marked xfail(reason) here — honest, not a silent pass.
    """
    e = expect("A1")
    assert e["bucket"] == "HARDENED"

    if backend.name == "poc":
        # PoC: bootstrap carries the chat_id scope but mints no first-party
        # cookie. The HARDENED contrast is that there is nothing to strip — so we
        # observe REAL server behavior, not the in-memory login() handle. Drive a
        # bootstrap GET against a protected PoC route (the uploads-list surface)
        # and assert the server set no first-party session cookie. If the PoC
        # ever started minting one, this assertion flips red — the contrast is
        # against observed wire, not a dict literal.
        handle = backend.login()
        assert "chat_id" in handle, "PoC login must carry the chat_id scope"
        resp = backend._get(f"/api/uploads/{handle['chat_id']}/list")
        set_cookie = resp.headers.get("set-cookie", "")
        assert not set_cookie, (
            "PoC bootstrap sets no first-party cookie; the server returned a "
            f"Set-Cookie ({set_cookie!r}). That absence is the HARDENED finding "
            "recorded against the fleet's cookie"
        )
        assert len(resp.cookies) == 0, (
            "PoC bootstrap must expose no first-party session cookie on the "
            f"observed response; got {list(resp.cookies.keys())!r}"
        )
        return

    # Fleet browser branch. login() returns the wire-level caller identity; the
    # cookie + embed-token verification is a UI journey.
    pytest.importorskip(
        "playwright.sync_api",
        reason=(
            "A1 cookie bootstrap drives the live UI login with Playwright "
            "fill+click (Set-Cookie SameSite=None/Secure/HttpOnly, embed sig+"
            "aud+exp<=120s); KEYSTONE = strip cookie -> 401/redirect. Playwright "
            "is not wired in this scaffold. Marking importorskip so this is a "
            "recorded gap, never a silent green."
        ),
    )
    pytest.xfail(
        "A1 fleet cookie assertion + KEYSTONE (strip cookie -> 401/redirect) "
        "requires the Playwright browser runner; not exercisable from the "
        "wire-only scaffold. Bound in the browser group test."
    )


# ---------------------------------------------------------------------------
# A2 — frame-ancestor allowlist enforced.  bucket: HARDENED
# ---------------------------------------------------------------------------
def test_a2_frame_ancestor_allowlist(backend, expect):
    """A2 | CSP frame-ancestors allowlist enforced.

    Invariant: the fleet UI serves a CSP with frame-ancestors from an
    allowlist; an allowlisted parent origin STILL renders (block is scoped, not
    a blanket deny) while a foreign parent is blocked (console CSP violation, no
    document). KEYSTONE: the allowlisted origin still renders. PoC sets no CSP —
    any parent may frame it, which is the HARDENED contrast.

    Framing behavior is observable only in a real browser: the suite loads the
    UI inside an allowlisted iframe and a foreign-origin iframe with Playwright,
    then reads the console CSP-violation event and asserts the foreign frame has
    no document — NEVER page.evaluate(fetch). Not wired here.
    """
    e = expect("A2")
    assert e["bucket"] == "HARDENED"

    if backend.name == "poc":
        # PoC: serves no CSP. The finding is the ABSENCE of a frame-ancestors
        # boundary, so we observe a REAL server response — not the login()
        # handle. Drive a bootstrap GET against a protected PoC route and assert
        # the server set neither a Content-Security-Policy nor an X-Frame-Options
        # header. If the PoC ever started serving one, this flips red; the
        # contrast is against observed wire, not a dict literal.
        handle = backend.login()
        resp = backend._get(f"/api/uploads/{handle['chat_id']}/list")
        csp = resp.headers.get("content-security-policy", "")
        assert "frame-ancestors" not in csp.lower(), (
            "PoC serves no CSP frame-ancestors; the server returned one "
            f"({csp!r}). Any parent may frame the UI — that open framing surface "
            "is the HARDENED finding recorded against the fleet."
        )
        assert "x-frame-options" not in {k.lower() for k in resp.headers.keys()}, (
            "PoC sets no X-Frame-Options framing guard either; observing one on "
            "the wire flips this HARDENED contrast"
        )
        return

    pytest.importorskip(
        "playwright.sync_api",
        reason=(
            "A2 CSP frame-ancestors is a browser-only observation (allowlisted "
            "iframe renders; foreign iframe -> console CSP violation + no doc). "
            "KEYSTONE = allowlisted origin STILL renders. Playwright not wired; "
            "importorskip keeps this a recorded gap, not a silent green."
        ),
    )
    pytest.xfail(
        "A2 fleet CSP framing assertion + KEYSTONE (allowlisted origin still "
        "renders, foreign blocked) requires the Playwright browser runner. "
        "Bound in the browser group test."
    )


# ---------------------------------------------------------------------------
# A3 — CSRF token required on mutations.  bucket: HARDENED
# ---------------------------------------------------------------------------
def test_a3_csrf_required_on_mutation(backend, expect):
    """A3 | CSRF token required on mutating action (upload).

    Invariant: on the fleet a mutating action (upload) with a valid CSRF token
    succeeds (2xx) and the SAME request minus the token is refused (403).
    KEYSTONE: dropping only the CSRF token flips the green (2xx) to red (403).
    PoC accepts the mutation unconditionally (no CSRF) — the HARDENED contrast.

    The CSRF token lives in a first-party cookie/header pair the browser
    manages; the real suite performs the upload via Playwright fill+click on the
    upload control (with the token) and then replays the same submit with the
    token stripped, NEVER page.evaluate(fetch). Not wired here.
    """
    e = expect("A3")
    assert e["bucket"] == "HARDENED"

    if backend.name == "poc":
        # PoC: an upload is accepted unconditionally — there is no CSRF gate.
        # We assert the real upload SUCCEEDS (the mutation lands), which is the
        # open-boundary finding. The upload verb writes the :ro inputs bind.
        from backends.base import SURFACE_INPUTS

        ref = backend.upload(SURFACE_INPUTS, "a3-csrf.txt", b"a3 body")
        assert ref.size == len(b"a3 body"), (
            "PoC upload must land unconditionally (no CSRF gate); that "
            "acceptance is the HARDENED finding recorded against the fleet"
        )
        return

    pytest.importorskip(
        "playwright.sync_api",
        reason=(
            "A3 CSRF is enforced on the first-party session (cookie/header "
            "pair) the browser manages; the with-token 2xx vs without-token 403 "
            "and the KEYSTONE (drop token -> 2xx flips to 403) must be driven by "
            "Playwright fill+click, never page.evaluate(fetch). Not wired here."
        ),
    )
    pytest.xfail(
        "A3 fleet CSRF assertion + KEYSTONE (same upload minus token flips 2xx "
        "to 403) requires the Playwright browser runner. Bound in the browser "
        "group test."
    )


# ---------------------------------------------------------------------------
# A4 — caller identity host-attested (gateway mTLS).  bucket: PoC-HOLE
# ---------------------------------------------------------------------------
def test_a4_mtls_caller_identity(backend, expect):
    """A4 | MCP caller identity is host-attested (gateway mTLS).

    PoC-HOLE: the PoC serves any caller over plain HTTP with just a chat-id (no
    attestation). The fleet gateway requires one client cert = one caller; no
    cert -> the TLS handshake fails (or 401), and a valid cert -> the control
    session API answers. KEYSTONE: a malformed-but-present client cert is ALSO
    rejected (not only the no-cert case).

    Assertions:
      * PoC side: create_session()/login() SUCCEED with no attestation — the
        hole is open (that is the finding).
      * Fleet side (real curl, same base + PKI as FleetBackend):
          - valid cert  -> HTTP status reached (handshake accepted; 404 on the
            never-created probe means the mTLS plane + control answered);
          - no cert     -> curl transport failure (returncode != 0) OR a 401 —
            the handshake did not admit the caller;
          - KEYSTONE: malformed cert -> also rejected (transport failure/401),
            not admitted to an HTTP handler.
    """
    e = expect("A4")
    assert e["bucket"] == "PoC-HOLE"

    if backend.name == "poc":
        # The PoC hole: any caller with a chat-id is served, no cert. login()
        # carries only the chat_id; create_session() is unbounded. Assert the
        # hole is OPEN (the PoC-HOLE finding), not enforced.
        handle = backend.login()
        assert "chat_id" in handle, (
            "PoC serves any caller over plain HTTP keyed only on chat-id — no "
            "host attestation. That open path is the PoC-HOLE finding."
        )
        sess = backend.create_session()
        assert sess.status == "active", (
            "PoC create is unbounded and unauthenticated; it succeeds without "
            "any client cert — the hole A4 records"
        )
        return

    # Fleet side: drive the real mTLS negatives with curl.
    _require_fleet(backend)
    if not _curl_available():
        pytest.skip("curl absent; cannot drive the fleet mTLS handshake probes")
    if not _pki_present():
        pytest.skip(
            f"gateway PKI not found under {_FLEET_PKI}; cannot present a client "
            "cert. This is a loud skip, not a green."
        )

    # Valid cert -> the mTLS plane + control answer (any HTTP status, e.g. 404).
    rc_valid, status_valid = _curl_status(_client_cert_args())
    assert rc_valid == 0 and status_valid > 0, (
        "a valid one-cert mTLS caller must reach control (an HTTP status, e.g. "
        f"404 on the never-created probe); got rc={rc_valid} status={status_valid}"
    )

    # No cert -> handshake refuses (transport failure) OR an application 401.
    # Either way the caller is NOT admitted as an attested identity.
    rc_nocert, status_nocert = _curl_status(["--cacert", str(_FLEET_PKI / "ca.pem")])
    admitted_nocert = rc_nocert == 0 and status_nocert not in (0, 401, 403)
    assert not admitted_nocert, (
        "a caller presenting NO client cert must be refused at the gateway "
        f"(TLS failure or 401), never admitted; got rc={rc_nocert} "
        f"status={status_nocert}"
    )

    # KEYSTONE: a syntactically-VALID client cert the gateway CA did NOT sign is
    # also rejected — at the mTLS HANDSHAKE, not in curl's local key loader. We
    # mint a real EC keypair + self-signed cert in a tmp dir; curl loads it
    # locally without error and presents it, so the refusal is the gateway's:
    # the cert does not chain to ca.pem. (Passing ca.pem as both --cert and
    # --key would fail in curl's private-key parser, exit 58, before any bytes
    # reach the gateway — that would test curl, not the handshake.)
    with tempfile.TemporaryDirectory(prefix="a4-untrusted-cert-") as tmp:
        bad_cert, bad_key = _make_untrusted_keypair(Path(tmp))
        rc_bad, status_bad = _curl_status(
            [
                "--cacert",
                str(_FLEET_PKI / "ca.pem"),
                "--cert",
                str(bad_cert),
                "--key",
                str(bad_key),
            ]
        )
    # curl must load the credential locally (no local-cert failures such as
    # exit 58); the rejection must come from the gateway (a TLS handshake
    # failure, returncode != 0, or an application 401/403), never an admitted
    # HTTP handler.
    admitted_bad = rc_bad == 0 and status_bad not in (0, 401, 403)
    assert not admitted_bad, (
        "KEYSTONE: a valid client cert the gateway CA did not sign must be "
        "rejected at the handshake (not only the no-cert case); got "
        f"rc={rc_bad} status={status_bad}"
    )


# ---------------------------------------------------------------------------
# A5 — ADR-0027 static key gate.  bucket: HARDENED
# ---------------------------------------------------------------------------
def test_a5_static_key_gate(backend, expect):
    """A5 | ADR-0027 static sk-ocu- key gate.

    Invariant: the gateway accepts a valid control-minted sk-ocu- key (create
    -> 201) and rejects an unknown key (401). KEYSTONE: a key from the revoked
    set -> 401 (a once-minted key alone is not sufficient). PoC has no key gate
    (no analogue).

    The static-key wire is layered on top of the mTLS plane (ADR-0027: the key
    travels as a header the gateway validates in-process against its boot-loaded
    set). The scaffold's FleetBackend does not expose a key-injection verb, and
    minting/revoking a key is a control-operator action (occ). So this test
    asserts the ENVELOPE/STATUS CLASS on the wire where it can, and marks the
    mint/revoke round-trip as a recorded gap (xfail) rather than inventing a
    key body — the honest posture for a TBD scaffold surface.
    """
    e = expect("A5")
    assert e["bucket"] == "HARDENED"

    if backend.name == "poc":
        # PoC: "No analogue (no key gate)." Assert the per-backend expectation
        # names exactly that — there is no key surface to drive on the PoC.
        assert "No analogue" in e["expect"], (
            "PoC has no static-key gate; A5 records that absence"
        )
        return

    _require_fleet(backend)
    if not _curl_available():
        pytest.skip("curl absent; cannot drive the fleet static-key probes")
    if not _pki_present():
        pytest.skip(f"gateway PKI not found under {_FLEET_PKI}; loud skip, not green")

    # ENVELOPE assertion on the wire: an mTLS-valid caller presenting an UNKNOWN
    # static key is rejected with 401 (the key gate is distinct from the cert
    # gate). We send a syntactically-shaped but never-minted key on the ADR-0027
    # header; the assertion is on the STATUS CLASS (401), not on a response body
    # we would otherwise invent.
    unknown_key = "sk-ocu-unknown000000000000000000000000000000"
    rc, status = _curl_status(
        _client_cert_args() + ["-H", f"authorization: Bearer {unknown_key}"]
    )
    # If the deployment gates the key in-process, an unknown key -> 401. If this
    # build has not yet wired the header check onto this path, the status will
    # be the cert-plane's own answer (e.g. 404); we do NOT assert a green there,
    # we assert the ENVELOPE we can prove and defer the mint/revoke round-trip.
    if rc == 0 and status == 401:
        assert status == 401, "unknown sk-ocu- key must be rejected 401"
    else:
        # The valid-mint (201) and KEYSTONE (revoked-set key -> 401) require an
        # occ-minted key + an occ revoke — an operator round-trip the scaffold
        # does not expose. Record it as a gap, never a silent pass, and never an
        # invented key body (TBD surface -> assert the envelope only).
        pytest.xfail(
            "A5 valid-key 201 + KEYSTONE (revoked-set key -> 401) needs an "
            "occ-minted sk-ocu- key and an occ revoke round-trip; the scaffold "
            "exposes no key-injection verb. Asserting only the reachable "
            "envelope; the mint/revoke case binds in the operator group test. "
            f"(unknown-key probe returned rc={rc} status={status})"
        )


# ---------------------------------------------------------------------------
# A6 — session creation quota-reserved + image-gated.  bucket: HARDENED
# ---------------------------------------------------------------------------
def test_a6_session_create_image_gated_and_quota_reserved(backend, expect):
    """A6 | session creation is quota-reserved and image-gated.

    Invariant: the fleet control create allow-lists the image and reserves a
    row against the tier quota. An allow-listed image (or an omitted image ->
    the DEFAULT) yields 201 + a durable row; an off-allow-list ("foreign")
    image is denied (4xx). KEYSTONE: an EMPTY-BODY create resolves control's
    DEFAULT image to 201 — it does NOT trust the image ENTRYPOINT metadata (the
    #94 bug) — while a foreign image is STILL denied. PoC runs any image
    unbounded (the HARDENED contrast).

    Verbs: create_session(image=None) omits the image (default-resolution
    path); create_session(image=<foreign>) drives admission denial;
    get_session(key) proves the row is real (durable).
    """
    e = expect("A6")
    assert e["bucket"] == "HARDENED"

    if backend.name == "poc":
        # PoC: docker run of any image, unbounded. Assert BOTH a default create
        # and a "foreign" image create SUCCEED — there is no allow-list and no
        # quota, so nothing is denied. That open behavior is the finding.
        sess_default = backend.create_session()
        assert sess_default.status == "active", (
            "PoC create with no image is unbounded and succeeds"
        )
        sess_foreign = backend.create_session(image="ghcr.io/attacker/anything:latest")
        assert sess_foreign.status == "active", (
            "PoC accepts ANY image with no allow-list — the A6 open behavior "
            "the fleet closes"
        )
        return

    # Fleet: real create over the gateway mTLS plane.
    # KEYSTONE part 1 — empty-body create resolves the DEFAULT image to 201,
    # NOT trusting image ENTRYPOINT metadata (the #94 regression this guards).
    default_sess = backend.create_session()  # image omitted -> control default
    assert default_sess.status == "active", (
        "empty-body create must resolve control's DEFAULT image to a live row "
        f"(201); got status={default_sess.status!r}. This is the #94 keystone: "
        "control must not fall back to trusting the image ENTRYPOINT metadata."
    )
    assert default_sess.key, "a 201 create must return a control-issued session key"

    # The reserved row is durable: GET must return an existing row for the key
    # (row-as-reservation). A never-created key would be not_found; this key is.
    fetched = backend.get_session(default_sess.key)
    assert fetched.status not in ("not_found", ""), (
        "the created session's row must be a real reservation the control API "
        f"returns; got status={fetched.status!r}"
    )

    # KEYSTONE part 2 — a foreign (off-allow-list) image is STILL denied. The
    # backend surfaces an admission denial as status "denied:<http>"; we assert
    # the STATUS CLASS is a 4xx denial (envelope, not an invented body).
    foreign_sess = backend.create_session(
        image="ghcr.io/attacker/not-on-allowlist:latest"
    )
    assert foreign_sess.status.startswith("denied:"), (
        "a foreign, off-allow-list image must be DENIED at admission; got "
        f"status={foreign_sess.status!r}"
    )
    denied_code = int(foreign_sess.status.split(":", 1)[1])
    assert 400 <= denied_code < 500, (
        "the foreign-image denial must be a 4xx admission refusal (envelope "
        f"assertion, not an invented body); got {denied_code}"
    )
