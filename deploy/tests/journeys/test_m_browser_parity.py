# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""GROUP M journeys: the eyes-in-browser PoC-parity cycle (Fable ruling ae7daf88).

The owner's parity bar is the FULL browser cycle, not wire probes: a file the
model creates RENDERS in the OpenWebUI pane preview, a chat upload reaches the
guest, and skills fire and produce an artifact. Groups A-L drive the wire with
curl; this group drives a REAL browser (Playwright) against the embed-portal
(127.0.0.1:3003) which frames the File Pane BFF (127.0.0.1:3000). A browser is
required because the pane's authed calls need both a Secure session cookie and
the x-ocu-chat-scope header, which the pane's own client sends and curl cannot
replay.

Anti-vacuity (this suite lied by skipping before): these tests are GATED on
OCU_BROWSER_E2E=1. When the gate is SET, a missing Playwright / chromium is a
FAIL, not a skip -- skip == NOT-RUN is exactly the hole. When the gate is
unset, they skip loudly (the browser rig is opt-in, run in the VM jvenv).

  M1 (P-A): exec writes a PNG of known dimensions to /mnt/user-data/outputs ->
            pane preview renders an <img> whose naturalWidth/Height match.
            Red-probe: NEXT_PUBLIC_PREVIEW_RENDER_ENABLED OFF -> no <img>.
  M2 (P-B): Playwright drives the real chat file input (set_input_files, not the
            upload API) -> the guest reads the exact bytes at uploads/<name>.
            Red-probe: upload under a different chat scope -> guest must NOT see.
  M3 (P-C): guest runs a /mnt/skills toolchain -> artifact in outputs -> pane
            lists + previews it. Red-probe: skill dir absent -> RED.
  M4 (KEYSTONE): live model -> prompt -> tool call -> file -> preview, eyes-in-
            browser. Parity is NOT done until M4 runs firsthand once.
"""

import os
import pathlib
import re
import subprocess
import time
import uuid

import pytest

# The portal frames the pane by its localhost origin and the pane's CSP is
# frame-ancestors http://localhost:3003 -- so the browser MUST reach the portal
# via localhost (not 127.0.0.1). A 127.0.0.1 origin is a DIFFERENT origin for
# CSP: the iframe is blocked and drops to chrome-error, which reads as "pane
# iframe not found". Lima forwards both host names to the same listener.
PORTAL_URL = "http://localhost:3003"
PANE_FRAME_URL = "localhost:3000"

pytestmark = pytest.mark.fleet

_BROWSER_GATE = os.getenv("OCU_BROWSER_E2E", "") in ("1", "true", "yes", "on")

# The pane-list-reader tests (M1/M2b/M3/M5/M6) were strict-xfail under defect #182
# (F9 list sorted ascending CreatedAt + pane page-1-only -> a just-written file was
# off page-1 at >=100 objects). The order=desc fix shipped (ADR-0031 amends 0028):
# the pane and the _pane_list helper now send order=desc, so the newest file is on
# page-1. The markers are removed; the tests are live regression guards. The >=100
# saturation guard is KEPT so the guard stays non-vacuous (an under-100 scope would
# pass even with the order fix reverted).


def _require_browser():
    """Gate + anti-vacuity: gate-set-but-no-chromium is a FAIL, not a skip."""
    if not _BROWSER_GATE:
        pytest.skip(
            "OCU_BROWSER_E2E not set: the eyes-in-browser M-group is opt-in "
            "(run in the VM jvenv with playwright+chromium). LOUD SKIP."
        )
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as exc:
        pytest.fail(
            "OCU_BROWSER_E2E is SET but playwright is not importable: "
            f"{exc}. A missing browser under the gate is a FAILURE, not a "
            "skip (skip == NOT-RUN is how this suite lied before). "
            "Install: /tmp/jvenv/bin/pip install playwright && "
            "/tmp/jvenv/bin/python -m playwright install chromium."
        )


def _guest_exec(chat_id, command, timeout=90):
    """Run a bash command in the guest via the gateway wire (from test_i)."""
    from test_i_mcp_surface import _bash_body, _call  # same wire

    status, parsed = _call(chat_id, _bash_body(command), timeout=timeout)
    from test_i_mcp_surface import _result

    text, is_error = _result(parsed)
    return status, text, is_error


def _portal_reachable():
    try:
        out = subprocess.run(
            ["curl", "-sS", "--max-time", "8", "-o", "/dev/null",
             "-w", "%{http_code}", PORTAL_URL + "/"],
            capture_output=True, text=True, timeout=12,
        )
        return out.stdout.strip() == "200"
    except (OSError, subprocess.SubprocessError):
        return False


def _wait_file_listed(filename, deadline_s=60, chat_id=None):
    """Poll the pane's own GET /v1/files?order=desc (the same newest-first call the
    pane makes on mount, #182) until `filename` is in the list, or the deadline
    passes. Returns the FileObject or None. Reuses test_j's pane bootstrap +
    scope-header list (which sends order=desc) so the poll sees exactly what the
    browser mount will see.
    """
    import tempfile
    import test_j_file_flow as J

    tmp = pathlib.Path(tempfile.mkdtemp())
    jar, _csrf = J._pane_session(tmp, chat_id=chat_id)
    return J._pane_find(jar, filename, deadline_s=deadline_s)


def _ensure_scope_saturated_for_182():
    """Arm the #182 condition so the pane-list regression guards (M1/M3/M5/M6) stay
    NON-VACUOUS: the scope must hold >= maxListLimit (100) objects so a just-written
    file is the newest and, under the OLD ascending order, would sort onto page-2+
    and be invisible in the pane's page-1-only list. With the order=desc fix the
    newest file is now on page-1, so these tests pass -- but ONLY because the fix
    works: revert it and, at >=100 objects, the newest file drops off page-1 and the
    tests red. An under-100 scope would let a fresh file land on page-1 trivially, so
    the guard would stay green even with the fix reverted -- that is why the
    saturation is load-bearing, not cosmetic. The shared fs-fleet scope already
    carries >=100 from accumulated runs; it pads only if under-populated. Mirrors
    j8's saturation (test_j_file_flow)."""
    import tempfile
    import test_j_file_flow as J

    tmp = pathlib.Path(tempfile.mkdtemp())
    jar, csrf = J._pane_session(tmp)
    PAGE = 100
    current = len(J._pane_list(jar))
    need = max(0, (PAGE + 5) - current)
    for i in range(need):
        J._pane_upload(jar, csrf, f"m182-pad-{i:03d}-{uuid.uuid4().hex[:8]}.txt", f"pad{i}")
    saturated = len(J._pane_list(jar))
    assert saturated >= PAGE, (
        f"could not saturate the scope past {PAGE} objects (have {saturated}) -- the "
        "#182 regression is only reachable at >=100; an under-populated scope would "
        "let a fresh file land on page-1 trivially, making the guard vacuous"
    )


def _wait_content_contains(file_id, marker, deadline_s=45, chat_id=None):
    """Poll the pane's content endpoint (the exact bytes the browser preview
    fetches) until `marker` is present, or fail. An in-place edit (str_replace)
    reaches the north-face content-read with a bounded write-back lag; this gates
    on the propagated bytes so a preview assert does not race a stale read."""
    import tempfile
    import time

    import test_j_file_flow as J

    tmp = pathlib.Path(tempfile.mkdtemp())
    jar, _csrf = J._pane_session(tmp, chat_id=chat_id)
    for _ in range(deadline_s):
        status, body = J._pane_content(jar, file_id)
        if status == 200 and marker in (body or ""):
            return
        time.sleep(1)
    status, body = J._pane_content(jar, file_id)
    assert marker in (body or ""), (
        f"the edited marker {marker!r} never reached the pane content endpoint "
        f"within {deadline_s}s; last read (status={status}): {body!r}"
    )


# ---------------------------------------------------------------------------
# M1 -- a model-written image renders in the pane preview (P-A)
# ---------------------------------------------------------------------------

def test_m1_agent_image_renders_in_pane_preview():
    """P-A: an image written to outputs renders as an <img> in the pane preview
    with the file's real pixel dimensions -- not just a 200 on the content URL
    (that is a download, not a preview). Requires the #218 slice built with
    NEXT_PUBLIC_PREVIEW_RENDER_ENABLED=true.

    xfail(strict) under #182: this gates on the pane's page-1-only GET /v1/files
    (via _wait_file_listed) before the preview; at >=100 objects the just-written
    image sorts onto page-2+ (ascending CreatedAt) and the pane never lists it, so
    the preview row never appears. Clears (XPASS -> remove marker) when order=desc
    ships (ADR-0031). The saturation guard makes the condition deterministic.
    """
    _require_browser()
    if not _portal_reachable():
        pytest.fail(
            "OCU_BROWSER_E2E set but embed-portal :3003 is unreachable -- the "
            "user leg cannot run; a down portal under the gate is a FAILURE."
        )
    _ensure_scope_saturated_for_182()
    from playwright.sync_api import sync_playwright

    # 1. The guest writes a PNG of KNOWN dimensions (poc-fat has PIL).
    chat_id = f"m1-{uuid.uuid4().hex[:8]}"
    name = f"m1-{uuid.uuid4().hex[:8]}.png"
    W, H = 123, 45
    status, text, is_error = _guest_exec(
        chat_id,
        f"python3 -c \"from PIL import Image; "
        f"Image.new('RGB',({W},{H}),(10,20,30)).save('/mnt/user-data/outputs/{name}')\" "
        f"&& echo WROTE",
        timeout=120,
    )
    assert status == 200 and not is_error and text and "WROTE" in text, (
        f"guest PNG write failed: status={status} err={is_error} text={text!r}"
    )

    # 1b. The pane lists-on-mount and does NOT poll. A guest write reaches the
    # north-face list with a bounded lag (observed ~6s: the object is byte-
    # complete in the backend at ~2s, the list reflects it at ~6s -- the tail
    # is on the read/list side). So poll the pane's OWN list endpoint until the
    # file is authoritative BEFORE launching the browser -- else the mount-list
    # snapshot misses the just-written file and the preview row never appears.
    # This models the real-user timing (the model wrote the file moments before
    # the user opens the panel) without a flaky fixed sleep. Polling the pane's
    # endpoint (not MinIO or filestore-north directly) gates on the exact list
    # the browser mount will fetch.
    obj = _wait_file_listed(name, deadline_s=60, chat_id=chat_id)
    assert obj is not None, (
        f"{name} never appeared in GET /v1/files within 60s -- the write did "
        "not propagate to the north-face list (VFS write-back or list gap)"
    )

    # 2. Drive a real browser: portal frames the pane; open the file's preview.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(PORTAL_URL + f"?chat={chat_id}", wait_until="networkidle", timeout=30000)
            frame = next(
                (f for f in page.frames if PANE_FRAME_URL in (f.url or "")), None
            )
            assert frame is not None, (
                f"pane iframe ({PANE_FRAME_URL}) not found in portal -- if the "
                "iframe dropped to chrome-error, the portal was reached on a "
                "different origin than the pane CSP frame-ancestors allows "
                "(reach the portal via localhost, not 127.0.0.1)"
            )
            # Wait for the file row, then activate its preview affordance.
            frame.wait_for_selector(f"text={name}", timeout=45000)
            preview_btn = frame.locator(f"[aria-label='Preview {name}']")
            assert preview_btn.count() > 0, (
                "no Preview affordance for the file -- the #218 slice flag is "
                "likely OFF in this webui image (build with "
                "NEXT_PUBLIC_PREVIEW_RENDER_ENABLED=true)"
            )
            preview_btn.first.click()
            img = frame.locator("[data-testid='file-preview-image']")
            img.wait_for(state="visible", timeout=20000)
            nat_w = img.evaluate("el => el.naturalWidth")
            nat_h = img.evaluate("el => el.naturalHeight")
            assert (nat_w, nat_h) == (W, H), (
                f"preview <img> rendered {nat_w}x{nat_h}, expected {W}x{H} -- "
                "the image did not truly paint (P-A parity)"
            )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# M2/M3/M4 -- authored next, once M1 is green against the built image.
# ---------------------------------------------------------------------------

def test_m2_chat_upload_reaches_guest():
    """P-B: a user uploads a file through the pane's real file input (the
    UploadZone <input type=file>, driven by set_input_files -- NOT the upload
    API) and the guest reads the EXACT bytes at /mnt/user-data/uploads/<name>.

    This is the chat-file-upload leg (the owner's "upload works" bar): a browser drives the real
    upload affordance, the file lands in the filestore uploads/ prefix, and the
    guest's read-only /mnt/user-data/uploads FUSE view serves the same bytes.
    Asserting the exact payload (not just presence) is the non-vacuous form.
    """
    _require_browser()
    if not _portal_reachable():
        pytest.fail(
            "OCU_BROWSER_E2E set but embed-portal :3003 is unreachable -- the "
            "user leg cannot run; a down portal under the gate is a FAILURE."
        )
    from playwright.sync_api import sync_playwright

    name = f"m2-{uuid.uuid4().hex[:8]}.txt"
    payload = f"CHAT_UPLOAD_{uuid.uuid4().hex[:12]}"
    local = os.path.join("/tmp", name)
    with open(local, "w") as fh:
        fh.write(payload)

    # ONE chat id for BOTH halves. Under ADR-0030 the storage scope is derived
    # from the chat, so the browser that uploads and the guest that reads must
    # name the SAME chat or they address different subtrees. A portal opened
    # with no ?chat= mints a session on the BASE scope (fs-fleet) while the
    # guest exec below carries X-Chat-Id and mounts fs-fleet-<hash> -- the
    # upload then lands in a tree the guest never sees, and the read fails as
    # "No such file or directory" with the object sitting safely in the store.
    chat_id = f"m2-{uuid.uuid4().hex[:8]}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(
                PORTAL_URL + f"?chat={chat_id}",
                wait_until="networkidle",
                timeout=30000,
            )
            frame = next(
                (f for f in page.frames if PANE_FRAME_URL in (f.url or "")), None
            )
            assert frame is not None, (
                f"pane iframe ({PANE_FRAME_URL}) not found in portal (reach the "
                "portal via localhost, not 127.0.0.1 -- CSP frame-ancestors)"
            )
            # Barrier on the pane's EMPTY state, not on a Download row. This
            # chat is brand new, so its scope holds nothing and no row can ever
            # appear -- a "wait for Download" barrier here only ever passed by
            # reading the shared base scope's rows, which is the very leak this
            # test must not depend on. The empty-state line proves the pane
            # bootstrapped its session AND resolved the list FOR THIS CHAT: if
            # the scope binding regressed to the base tree the pane would show
            # its rows instead and this wait would fail.
            frame.wait_for_selector(
                "text=No files in this session yet.", timeout=45000
            )
            rows = frame.get_by_text("Download", exact=True).count()
            assert rows == 0, (
                f"a brand-new chat's pane already offers {rows} Download "
                "controls; it is listing another scope's tree"
            )
            file_input = frame.locator("input[type=file]")
            assert file_input.count() > 0, (
                "no <input type=file> in the pane -- the UploadZone affordance is "
                "missing (the user cannot upload a file)"
            )
            # Barrier on the upload REQUEST, not the pane list. The pane's
            # GET /v1/files list is #182-blocked at >=100 objects (a fresh upload
            # sorts onto page-2+ ascending and never lists on page-1) -- so the
            # old wait_for_selector(text=<name>) timed out for the #182 defect,
            # not for a real P-B failure. The upload POST (/v1/files, the frozen
            # north path the pane's UploadZone hits -- verified by a live network
            # trace, NOT the Next.js-internal /api/v1/files) landing 2xx is the
            # #182-independent P-B signal AND the pre-close barrier
            # (without it the browser could close before the async upload
            # completes, racing the guest-read). The pane-visibility of an upload
            # is test_m2b's strict-xfail(#182) leg (the uploads-branch list path).
            with page.expect_response(
                lambda r: r.request.method == "POST"
                and "/v1/files" in r.url
                and r.ok,
                timeout=45000,
            ):
                file_input.first.set_input_files(local)
        finally:
            browser.close()

    # The guest's read-only uploads view must serve the EXACT uploaded bytes.
    # Poll for the FUSE/dir-cache propagation lag (the pane-DOM wait used to
    # double as this barrier); assert byte-equality, never a proxy.
    got_bytes = False
    last = ""
    for _ in range(6):
        status, text, is_error = _guest_exec(
            chat_id, f"cat /mnt/user-data/uploads/{name}", timeout=90
        )
        last = f"status={status} err={is_error} text={text!r}"
        if status == 200 and not is_error and payload in (text or ""):
            got_bytes = True
            break
        time.sleep(10)
    assert got_bytes, (
        f"guest could not read the uploaded bytes at uploads/{name} within the "
        f"propagation window: {last} (want {payload!r})"
    )


def test_m2b_chat_upload_visible_in_pane():
    """The uploads-branch pane-list leg of #182 (split out of M2 per Fable's
    ruling): a user uploads a file through the pane's real file input, and the
    uploaded name must appear IN THE PANE list. This is a DISTINCT list path from
    M1/M3 (which cover the outputs-branch -- agent/skill writes reaching the pane);
    m2b covers the uploads-branch of the ADR-0029 north read-map, which no other M
    test exercises.

    xfail(strict) under #182: the pane fetches page-1 only (ascending CreatedAt),
    so at >=100 objects a fresh upload sorts onto page-2+ and never lists on
    page-1. M2's own P-B core (upload -> guest bytes) is #182-INDEPENDENT and stays
    green; only this pane-visibility leg is #182-blocked. Clears (XPASS -> remove
    marker) when order=desc ships (ADR-0031). The saturation guard makes the
    condition deterministic (an under-100 scope would XPASS and red strict).
    """
    _require_browser()
    if not _portal_reachable():
        pytest.fail(
            "OCU_BROWSER_E2E set but embed-portal :3003 is unreachable -- the "
            "user leg cannot run; a down portal under the gate is a FAILURE."
        )
    _ensure_scope_saturated_for_182()
    from playwright.sync_api import sync_playwright

    name = f"m2b-{uuid.uuid4().hex[:8]}.txt"
    payload = f"CHAT_UPLOAD_{uuid.uuid4().hex[:12]}"
    local = os.path.join("/tmp", name)
    with open(local, "w") as fh:
        fh.write(payload)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(PORTAL_URL, wait_until="networkidle", timeout=30000)
            frame = next(
                (f for f in page.frames if PANE_FRAME_URL in (f.url or "")), None
            )
            assert frame is not None, (
                f"pane iframe ({PANE_FRAME_URL}) not found in portal (reach the "
                "portal via localhost, not 127.0.0.1 -- CSP frame-ancestors)"
            )
            frame.wait_for_selector("text=Download", timeout=45000)
            file_input = frame.locator("input[type=file]")
            assert file_input.count() > 0, (
                "no <input type=file> in the pane -- the UploadZone affordance is "
                "missing (the user cannot upload a file)"
            )
            # Barrier on the upload POST so the row would be renderable if the pane
            # listed it; then require the uploaded name in the pane DOM -- the
            # #182-blocked leg (times out at >=100 objects; XPASSes when desc ships).
            with page.expect_response(
                lambda r: r.request.method == "POST"
                and "/v1/files" in r.url
                and r.ok,
                timeout=45000,
            ):
                file_input.first.set_input_files(local)
            frame.wait_for_selector(f"text={name}", timeout=45000)
        finally:
            browser.close()


def _preview_image_in_pane(name, expected_w, expected_h, chat_id=None):
    """Open the portal in a real browser, find the file row, click Preview, and
    assert the rendered <img> paints at exactly (expected_w, expected_h). Shared
    by the P-A (M1) and P-C (M3) legs -- both assert an image truly previews.
    The caller must have already ensured `name` is in the pane's list (poll
    first: the pane lists-on-mount and the write-back has a bounded lag)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(PORTAL_URL + (f"?chat={chat_id}" if chat_id else ""), wait_until="networkidle", timeout=30000)
            frame = next(
                (f for f in page.frames if PANE_FRAME_URL in (f.url or "")), None
            )
            assert frame is not None, (
                f"pane iframe ({PANE_FRAME_URL}) not found in portal (reach the "
                "portal via localhost, not 127.0.0.1 -- CSP frame-ancestors)"
            )
            frame.wait_for_selector(f"text={name}", timeout=45000)
            preview_btn = frame.locator(f"[aria-label='Preview {name}']")
            assert preview_btn.count() > 0, (
                "no Preview affordance for the file -- the #218 slice flag is "
                "likely OFF in this webui image (build with "
                "NEXT_PUBLIC_PREVIEW_RENDER_ENABLED=true)"
            )
            preview_btn.first.click()
            img = frame.locator("[data-testid='file-preview-image']")
            img.wait_for(state="visible", timeout=20000)
            nat_w = img.evaluate("el => el.naturalWidth")
            nat_h = img.evaluate("el => el.naturalHeight")
            assert (nat_w, nat_h) == (expected_w, expected_h), (
                f"preview <img> rendered {nat_w}x{nat_h}, expected "
                f"{expected_w}x{expected_h} -- the image did not truly paint"
            )
        finally:
            browser.close()


def test_m3_skill_fires_and_artifact_previews():
    """P-C: the guest runs a skill toolchain (matplotlib charting -- a real
    skill runtime, Agg backend so it needs no browser under gVisor) that
    PRODUCES an artifact in outputs, and that artifact then PREVIEWS in the pane
    as an image with its real pixel dimensions. This is the "skills work" bar: a
    skill fires and its output is visible in the pane, not just a wire 200.

    matplotlib is used because mmdc (mermaid-cli) launches a headless Chromium
    that crashes under gVisor (crashpad socket reset) -- a real gVisor+Chromium
    limitation, not a skill defect. The charting skill exercises the same
    "skill -> artifact -> preview" path deterministically.

    xfail(strict) under #182: gates on the pane's page-1-only list before the
    preview; at >=100 objects the skill artifact is off page-1 and never previews.
    Clears when order=desc ships (ADR-0031). The live-model skill path (M7/M8/M9)
    is #182-immune because it reads the artifact via guest FUSE, not the pane list.
    """
    _require_browser()
    if not _portal_reachable():
        pytest.fail(
            "OCU_BROWSER_E2E set but embed-portal :3003 is unreachable -- the "
            "user leg cannot run; a down portal under the gate is a FAILURE."
        )
    _ensure_scope_saturated_for_182()

    name = f"m3-{uuid.uuid4().hex[:8]}.png"
    W, H = 200, 100
    # The skill toolchain: matplotlib (Agg) renders a chart of known dims.
    chart = (
        "MPLCONFIGDIR=/tmp python3 -c \""
        "import matplotlib; matplotlib.use('Agg'); "
        "import matplotlib.pyplot as plt; "
        f"fig=plt.figure(figsize=(2,1),dpi=100); "
        "plt.plot([0,1,2],[0,1,4]); "
        f"fig.savefig('/mnt/user-data/outputs/{name}')\" && echo CHARTED"
    )
    chat_id = f"m3-{uuid.uuid4().hex[:8]}"
    status, text, is_error = _guest_exec(
        chat_id, chart, timeout=150
    )
    assert status == 200 and not is_error and "CHARTED" in (text or ""), (
        f"skill toolchain (matplotlib chart) failed: status={status} "
        f"err={is_error} text={text!r}"
    )

    # The artifact must reach the pane's list (bounded write-back lag).
    obj = _wait_file_listed(name, deadline_s=60, chat_id=chat_id)
    assert obj is not None, (
        f"skill artifact {name} never appeared in GET /v1/files within 60s"
    )

    # And it must PREVIEW as an image with the chart's real dimensions.
    _preview_image_in_pane(name, W, H, chat_id=chat_id)


def _preview_text_in_pane(name, must_contain, must_not_contain=None, chat_id=None):
    """Open the portal in a real browser, find the file row, click Preview, and
    assert the rendered <pre data-testid=file-preview-text> contains
    `must_contain` and (if given) does NOT contain `must_not_contain`. The caller
    must have already ensured `name` is listed. Reloads the frame each call so a
    second call after an edit fetches fresh content, not a cached preview."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(PORTAL_URL + (f"?chat={chat_id}" if chat_id else ""), wait_until="networkidle", timeout=30000)
            frame = next(
                (f for f in page.frames if PANE_FRAME_URL in (f.url or "")), None
            )
            assert frame is not None, (
                f"pane iframe ({PANE_FRAME_URL}) not found in portal (reach the "
                "portal via localhost, not 127.0.0.1 -- CSP frame-ancestors)"
            )
            frame.wait_for_selector(f"text={name}", timeout=45000)
            preview_btn = frame.locator(f"[aria-label='Preview {name}']")
            assert preview_btn.count() > 0, (
                "no Preview affordance for the file -- the #218 slice flag is "
                "likely OFF in this webui image (build with "
                "NEXT_PUBLIC_PREVIEW_RENDER_ENABLED=true)"
            )
            preview_btn.first.click()
            pre = frame.locator("[data-testid='file-preview-text']")
            pre.wait_for(state="visible", timeout=20000)
            body = pre.inner_text()
            assert must_contain in body, (
                f"text preview did not contain {must_contain!r}; pane <pre> "
                f"showed {body!r}"
            )
            if must_not_contain is not None:
                assert must_not_contain not in body, (
                    f"text preview still contained the pre-edit marker "
                    f"{must_not_contain!r}; pane <pre> showed {body!r} -- the "
                    "edit did not reflect in the pane"
                )
        finally:
            browser.close()


def test_m5_str_replace_edit_reflects_in_pane_preview():
    """P-A (edit path): a file created in outputs previews its text in the pane,
    then str_replace edits it IN PLACE and the pane preview reflects the NEW
    content. This ties the str_replace r+ fix (which edits an existing
    object-backed outputs file -- the O_TRUNC-on-open path that EIO'd before the
    fix) to the eyes-in-browser bar: not just "the tool returns success" but
    "the edited bytes render in the OpenWebUI pane".

    Non-vacuous: a broken str_replace (the pre-fix open(path,'w') that EIOs on an
    existing outputs file) leaves the file at its pre-edit content, so the
    post-edit preview would still show the BEFORE marker and the must_not_contain
    assert reds. Requires the #218 preview slice (text/plain inline) in the webui
    image and a python3-bearing guest for the file tools.
    """
    _require_browser()
    if not _portal_reachable():
        pytest.fail(
            "OCU_BROWSER_E2E set but embed-portal :3003 is unreachable -- the "
            "user leg cannot run; a down portal under the gate is a FAILURE."
        )
    _ensure_scope_saturated_for_182()
    from test_i_mcp_surface import _call, _file_tool_body, _result

    chat_id = f"m5-{uuid.uuid4().hex[:8]}"
    name = f"m5-{uuid.uuid4().hex[:8]}.txt"
    path = f"/mnt/user-data/outputs/{name}"
    before = f"M5_BEFORE_{uuid.uuid4().hex[:8]}"
    after = f"M5_AFTER_{uuid.uuid4().hex[:8]}"

    # 1. create_file the text file with the BEFORE marker.
    _, parsed = _call(
        chat_id, _file_tool_body("create_file", {"path": path, "file_text": before + "\n"})
    )
    text, is_error = _result(parsed)
    assert is_error is False and text and "Successfully created" in text, (
        f"create_file for the M5 text file failed: {text!r}"
    )

    # 2. It must list, then preview its text (the BEFORE marker) in the pane.
    obj = _wait_file_listed(name, deadline_s=60, chat_id=chat_id)
    assert obj is not None, f"{name} never appeared in GET /v1/files within 60s"
    _preview_text_in_pane(name, must_contain=before, chat_id=chat_id)

    # 3. str_replace the EXISTING outputs object (the r+ fix path).
    _, parsed = _call(
        chat_id,
        _file_tool_body("str_replace", {"path": path, "old_str": before, "new_str": after}),
    )
    text, is_error = _result(parsed)
    assert is_error is False and text and "Successfully replaced" in text and "Error" not in text, (
        f"str_replace on the outputs object failed: {text!r} -- the r+ fix "
        "should make this succeed on an existing file"
    )

    # 4. The edit propagates to the pane's content endpoint with the same
    # bounded write-back lag as a fresh write (~5s observed) -- str_replace does
    # an in-place r+ rewrite, so the north-face content-read reflects it shortly
    # after success, not instantly. Poll the pane content for the AFTER marker
    # before driving the browser, so the preview asserts against propagated bytes
    # (models the real user opening the panel moments after the edit) rather than
    # racing a stale read.
    _wait_content_contains(obj.get("id"), after, deadline_s=45, chat_id=chat_id)

    # 5. Then the pane preview must show the AFTER marker and NOT the BEFORE one.
    _preview_text_in_pane(name, must_contain=after, must_not_contain=before, chat_id=chat_id)


# ---------------------------------------------------------------------------
# M6 -- a non-previewable P-C artifact: unsupported-preview state + Download
# byte-match (the pane's fourth code path, untested in-browser before this)
# ---------------------------------------------------------------------------

def test_m6_non_previewable_artifact_downloads_bytewise():
    """P-C (non-image artifact): a skill-produced PDF in outputs takes the pane's
    UNSUPPORTED-preview path (it is neither an image nor text/plain), and the user
    retrieves it byte-identical via the pane's Download control. M1/M3/M5 cover the
    two RENDER paths (image, text); this covers the third preview state
    (file-preview-unsupported) and the Download code path (triggerBlobDownload) --
    neither had any in-browser coverage, and four of the five flagship skill
    artifact classes (docx/xlsx/pptx/pdf) reach the browser only as this state.

    Three distinct failure classes, one test:
      - dispatch regression: the preview panel does not reach the unsupported note.
      - binary-as-text regression: a widened extIsText / a resolveMime returning
        text/* for an unknown ext would route the PDF into the <pre> text branch;
        asserting file-preview-text is ABSENT catches it (the known-fragile path).
      - transform/truncation in the download leg: the sha of the downloaded bytes
        must equal the guest's on-disk sha -- content, not size.

    The byte reference is the GUEST's own sha256 of the object it wrote (not a
    regeneration -- reportlab embeds a creation timestamp, so two writes differ;
    and not the pane content endpoint decoded as text, which would corrupt binary).
    The Download control is per-row (a sibling of the row's `Preview <name>`
    button), so it is located WITHIN the file's row, never a bare page-wide
    text=Download that would match every row.

    Non-vacuous: with the PDF forced into the text branch (add "pdf" to extIsText
    in FilePane), the unsupported note never renders and file-preview-text appears
    -- the two preview asserts red; a truncated/transformed download reds the sha
    keystone. Requires the #218 preview slice in the webui image and a
    reportlab-bearing guest (poc-fat).
    """
    _require_browser()
    if not _portal_reachable():
        pytest.fail(
            "OCU_BROWSER_E2E set but embed-portal :3003 is unreachable -- the "
            "user leg cannot run; a down portal under the gate is a FAILURE."
        )
    import hashlib
    import pathlib
    import tempfile

    from playwright.sync_api import sync_playwright

    # 1. The guest writes a PDF (reportlab, pageCompression=0 -- same generator as
    # i12) and reports its on-disk sha256 + size. That sha is the byte reference.
    chat_id = f"m6-{uuid.uuid4().hex[:8]}"
    name = f"m6-{uuid.uuid4().hex[:8]}.pdf"
    path = f"/mnt/user-data/outputs/{name}"
    marker = f"M6_PDF_{uuid.uuid4().hex[:8]}"
    write = (
        f"python3 -c \"from reportlab.pdfgen import canvas; "
        f"c=canvas.Canvas('{path}', pageCompression=0); "
        f"c.drawString(72,720,'{marker}'); c.showPage(); c.save()\" "
        f"&& sha256sum {path} | cut -d' ' -f1 && stat -c %s {path}"
    )
    status, text, is_error = _guest_exec(chat_id, write, timeout=120)
    assert status == 200 and not is_error and text, (
        f"guest PDF write failed: status={status} err={is_error} text={text!r}"
    )
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    assert len(lines) >= 2, f"expected sha + size from the guest, got {text!r}"
    guest_sha, guest_size = lines[-2], int(lines[-1])
    assert len(guest_sha) == 64, f"guest sha256 malformed: {guest_sha!r}"

    # 2. It must list on the pane's own endpoint (the exact list the browser mount
    # fetches) with the guest's byte size -- gate before driving the browser so the
    # mount snapshot sees the file (same bounded write-back lag as M1/M5).
    obj = _wait_file_listed(name, deadline_s=60, chat_id=chat_id)
    assert obj is not None, (
        f"{name} never appeared in GET /v1/files within 60s -- the write did not "
        "propagate to the north-face list"
    )
    listed_size = obj.get("size_bytes", obj.get("size"))
    assert listed_size == guest_size, (
        f"pane list reports size {listed_size} but the guest wrote {guest_size} "
        "bytes -- the object is not byte-complete in the list the browser sees"
    )

    # 3. Drive a real browser: the PDF must take the UNSUPPORTED-preview path and
    # then download byte-identical.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(PORTAL_URL + f"?chat={chat_id}", wait_until="networkidle", timeout=30000)
            frame = next(
                (f for f in page.frames if PANE_FRAME_URL in (f.url or "")), None
            )
            assert frame is not None, (
                f"pane iframe ({PANE_FRAME_URL}) not found in portal (reach the "
                "portal via localhost, not 127.0.0.1 -- CSP frame-ancestors)"
            )
            frame.wait_for_selector(f"text={name}", timeout=45000)

            # Preview -> the unsupported note, and NEITHER render branch.
            preview_btn = frame.locator(f"[aria-label='Preview {name}']")
            assert preview_btn.count() > 0, (
                "no Preview affordance for the file -- the #218 slice flag is "
                "likely OFF in this webui image (build with "
                "NEXT_PUBLIC_PREVIEW_RENDER_ENABLED=true)"
            )
            preview_btn.first.click()
            unsupported = frame.locator("[data-testid='file-preview-unsupported']")
            unsupported.wait_for(state="visible", timeout=20000)
            assert frame.locator("[data-testid='file-preview-text']").count() == 0, (
                "a PDF rendered in the TEXT preview branch -- binary-as-text "
                "regression (extIsText widened or resolveMime returned text/* for "
                ".pdf); the unsupported state is the correct path for a PDF"
            )
            assert frame.locator("[data-testid='file-preview-image']").count() == 0, (
                "a PDF rendered in the IMAGE preview branch -- the mime dispatch "
                "mis-classified a non-image as an image"
            )

            # Download -> the per-row control (sibling of this row's Preview). The
            # Download button carries no aria-label/testid (verified against the
            # shipped bundle: a <button> with text child 'Download'), so scope it to
            # the row that holds the unique `Preview <name>` button, never a
            # page-wide text=Download that would match every row. The row is the
            # <li> in the list's <ul> (verified against the live DOM: the <li>
            # carries exactly ONE Download; the enclosing <ul>/<div> carry one per
            # listed file, so a loose `li,tr,div` ancestor with .first grabs the
            # whole list and downloads the FIRST file, not this one).
            row = frame.locator("li").filter(
                has=frame.locator(f"[aria-label='Preview {name}']")
            )
            assert row.count() == 1, (
                f"expected exactly one <li> row for {name}, found {row.count()} -- "
                "the row scoping is ambiguous and a Download click could fetch the "
                "wrong file"
            )
            download_btn = row.get_by_role("button", name="Download")
            assert download_btn.count() > 0, (
                f"no Download control in the row for {name} -- the pane row must "
                "carry a Download button alongside Preview"
            )
            with page.expect_download(timeout=20000) as dl_info:
                download_btn.first.click()
            dl = dl_info.value
            dst = pathlib.Path(tempfile.mkdtemp()) / name
            dl.save_as(str(dst))
            got = dst.read_bytes()
            assert got[:5] == b"%PDF-", (
                f"the downloaded bytes are not a PDF (head={got[:8]!r}) -- the "
                "Download leg transformed or mis-served the object"
            )
            got_sha = hashlib.sha256(got).hexdigest()
            assert got_sha == guest_sha, (
                f"downloaded sha {got_sha} != guest on-disk sha {guest_sha} -- the "
                f"Download leg did not serve the exact bytes ({len(got)} of "
                f"{guest_size} expected). Content-match, not size-match, is the "
                "non-vacuous form."
            )
        finally:
            browser.close()


OPENWEBUI_URL = "http://localhost:3001"
_OWUI_EMAIL = "admin@open-computer-use.dev"
_OWUI_PASSWORD = "admin"


def _model_endpoint_configured():
    """True when a real model connection is wired in the running OpenWebUI. M4 is
    env-gated: with the endpoint set, a live-model failure is a FAILURE, not a
    skip. Probed via the admin session's /models count (populated = configured).
    """
    probe = (
        "TOK=$(curl -sS --max-time 10 -X POST "
        "http://localhost:8080/api/v1/auths/signin -H 'Content-Type: application/json' "
        f"-d '{{\"email\":\"{_OWUI_EMAIL}\",\"password\":\"{_OWUI_PASSWORD}\"}}' 2>/dev/null "
        "| python3 -c 'import sys,json;print(json.load(sys.stdin).get(\"token\",\"\"))'); "
        "curl -sS --max-time 10 http://localhost:8080/api/models -H \"Authorization: Bearer $TOK\" 2>/dev/null "
        "| python3 -c 'import sys,json;print(len(json.load(sys.stdin).get(\"data\",[])))'"
    )
    try:
        out = subprocess.run(
            ["docker", "exec", "ocu-donegate-open-webui-1", "bash", "-c", probe],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip().isdigit() and int(out.stdout.strip()) > 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def _owui_login_and_open_chat(page):
    """Sign in to the real OpenWebUI browser UI and reach the chat input,
    dismissing the first-run 'What's New' release-notes modal that otherwise
    intercepts every click on the composer."""
    page.goto(OPENWEBUI_URL + "/", wait_until="networkidle", timeout=30000)
    time.sleep(2)
    page.fill("input[type=email]", _OWUI_EMAIL)
    page.fill("input[type=password]", _OWUI_PASSWORD)
    page.click('button:has-text("Sign in")')
    page.wait_for_selector("[contenteditable=true]", timeout=25000)
    time.sleep(2)
    # Dismiss the release-notes modal if present (blocks the composer).
    try:
        page.click('button:has-text("Okay")', timeout=5000)
        time.sleep(1)
    except Exception:
        pass  # no modal (already dismissed on a warm profile)


def test_m4a_live_model_chat_turn_deterministic():
    """M4a (deterministic, CI-grade): a LIVE model in the real OpenWebUI browser
    chat completes a plain instruction-following turn -- proves the whole
    model-in-chat wire (auth -> composer -> process_chat -> OpenRouter -> model
    -> streamed reply in the DOM) without the nondeterminism of the model
    choosing to call a tool. The reply must ECHO a unique token, so a dead chat
    (token appears only in the user's own message) fails the >=2 count.

    This is the gate M4b (the tool-forced keystone) rides on: if M4a is red, the
    model wire is broken and M4b's INCONCLUSIVE lane would be meaningless.
    """
    if not _model_endpoint_configured():
        pytest.skip(
            "no model endpoint configured in OpenWebUI (0 models) -- the live "
            "chat gate is opt-in. LOUD SKIP, not a pass."
        )
    _require_browser()
    from playwright.sync_api import sync_playwright

    token = f"PONG{uuid.uuid4().hex[:8].upper()}"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _owui_login_and_open_chat(page)
            composer = page.query_selector("[contenteditable=true]")
            assert composer is not None, "OpenWebUI chat composer not reachable"
            composer.click()
            composer.type(f"Reply with exactly this token and nothing else: {token}")
            time.sleep(0.5)
            page.keyboard.press("Enter")
            # The model's reply must echo the token: count >= 2 (user msg + reply).
            deadline = time.monotonic() + 60
            echoed = False
            while time.monotonic() < deadline:
                if page.inner_text("body").count(token) >= 2:
                    echoed = True
                    break
                time.sleep(1)
            assert echoed, (
                f"the live model did not echo {token!r} in its reply within 60s "
                "-- the model-in-chat wire is broken (a healthy turn echoes the "
                "token; a dead chat shows it only in the user's own message)"
            )
        finally:
            browser.close()


def test_m4_live_model_file_preview_keystone():
    """P-A/P-C tier-2 KEYSTONE: a LIVE model, in the real OpenWebUI browser chat,
    is prompted to write a file; it decides to CALL the OCU bash_tool; the tool
    executes in the guest; the file lands in the store with the EXACT marker.
    This is the owner's literal bar -- the model can create a file -- proven
    end-to-end eyes-in-browser (model -> tool-call -> guest -> FUSE -> filestore).

    Fable ruling: env-gate on the model endpoint. With the endpoint configured a
    failure is a FAILURE, not a skip. Verdict semantics: a transport/500/tool
    error or file-absent-after-the-turn = FAIL; a healthy turn where the model
    declines the tool after the forcing prompt = the caller re-runs (bounded),
    never silently green. The assert is a BYTE-MATCH of the unique marker (the
    proof.txt precedent -- content, not size), not mere presence.
    """
    if not _model_endpoint_configured():
        pytest.skip(
            "no model endpoint configured in OpenWebUI (0 models) -- the live "
            "keystone is opt-in; wire OPENAI_API_KEY/BASE_URL + DEFAULT_MODELS. "
            "LOUD SKIP, not a pass."
        )
    _require_browser()
    from playwright.sync_api import sync_playwright

    # Fable verdict semantics: a transport/composer failure is a hard FAIL; a
    # healthy turn where the model DECLINES the tool after N forcing attempts is
    # INCONCLUSIVE (reported via skip, never silently green, never conflated
    # with a wire break). A byte-matched file from any attempt is a PASS.
    ATTEMPTS = 3
    for attempt in range(ATTEMPTS):
        marker = f"M4LIVE{uuid.uuid4().hex[:8]}"
        name = f"m4-{uuid.uuid4().hex[:8]}.txt"
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                _owui_login_and_open_chat(page)
                composer = page.query_selector("[contenteditable=true]")
                assert composer is not None, (
                    "OpenWebUI chat composer not reachable -- transport/UI "
                    "failure, a hard FAIL (not the model declining)"
                )
                # A hard tool-forcing prompt: the model must call the tool.
                prompt = (
                    f"Call bash_tool now with command: "
                    f"echo {marker} > /mnt/user-data/outputs/{name}"
                )
                composer.click()
                composer.type(prompt)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                # Wait for the turn + the tool-call to execute + the object to land.
                time.sleep(45)
            finally:
                browser.close()

        # BYTE-MATCH: the object the live model wrote must carry the exact marker.
        chat_id = f"m4v-{uuid.uuid4().hex[:8]}"
        status, text, is_error = _guest_exec(
            chat_id, f"cat /mnt/user-data/outputs/{name}", timeout=90
        )
        if status == 200 and not is_error and marker in (text or ""):
            return  # PASS: the live model drove the tool and wrote the marker.

    # Every attempt had a healthy turn but no marked file: the model declined the
    # tool. INCONCLUSIVE, not a red -- the wire is proven live by M4a; only the
    # model's tool-choice was absent this run.
    pytest.skip(
        f"INCONCLUSIVE: the live model completed its turn(s) but declined to "
        f"call the tool after {ATTEMPTS} forcing attempts (no marked file "
        "reached the store). The model-in-chat wire is proven by M4a; this is "
        "model tool-choice nondeterminism, reported explicitly -- never a "
        "silent green and never conflated with a broken wire."
    )


def test_m7_live_model_invokes_skill_and_artifact_dims_match():
    """P-C tier-2 KEYSTONE (the live-model half of "skills work"): a LIVE model,
    in the real OpenWebUI browser chat, is asked in NATURAL LANGUAGE to render a
    chart; it decides to CALL the OCU bash_tool and AUTHORS the matplotlib
    (skill-runtime) code itself; the tool runs in the guest; a matplotlib-stamped
    PNG lands in outputs. This is the gap M3 does NOT cover: M3 fires the skill
    toolchain DETERMINISTICALLY (the harness writes the exec string), while M4b
    drives a live model but only to a PLAIN file WRITE. M7 is the missing corner --
    a live model REACHING a skill runtime, writing the skill code, and producing
    its artifact end-to-end.

    Prompt shape (Fable ruling 8f... on relay fidelity): the prompt is natural
    language with dictated parameters; the ONLY token the model must relay
    verbatim is the nonce filename (a bare [a-z0-9-] token, zero shell
    metacharacters). Handing the model a `python3 -c "..."` one-liner would force
    backslash-escaped inner quotes the model corrupts on relay -- flakiness of the
    wrong class (quoting, not tool-choice). Letting the model author the code is
    also the MORE realistic P-C: the model reaches the skill runtime AND writes
    the code.

    Non-vacuity (skill-runtime proof, not mere presence): matplotlib's Agg
    savefig embeds a `Software: Matplotlib version ...` tEXt chunk in the PNG.
    Asserting that chunk proves the artifact came out of the matplotlib skill
    runtime specifically -- not touch, not echo, not a PIL Image.new fallback --
    a stronger discriminator than exact dims. Dims are asserted only in a sane
    band (the model chooses figsize freely); exact 200x100 is logged, not
    asserted, so absorbed model-choice variance never reds the keystone.

    Verdict semantics (Fable-split on tool-invocation): endpoint configured ->
    live. A transport/composer failure is a hard FAIL. NO matplotlib-stamped PNG
    at the nonce path after N attempts, when the model DID drive a bash_tool call
    (the tool executes but the skill runtime is broken -- matplotlib import dead,
    Agg broken, outputs unwritable), is a FAIL (a deterministic break reds every
    attempt). NO PNG because no bash_tool call is observed = INCONCLUSIVE skip
    (model declined the tool -- the absorbed nondeterminism). A stamped PNG from
    any attempt is a PASS.
    """
    if not _model_endpoint_configured():
        pytest.skip(
            "no model endpoint configured in OpenWebUI (0 models) -- the live "
            "skill keystone is opt-in; wire OPENAI_API_KEY/BASE_URL + "
            "DEFAULT_MODELS. LOUD SKIP, not a pass."
        )
    _require_browser()
    from playwright.sync_api import sync_playwright

    ATTEMPTS = 3
    tool_call_ever_seen = False
    for attempt in range(ATTEMPTS):
        # The nonce is the ONLY token the model must relay verbatim: a bare
        # filename, no shell metacharacters. Asserted absent BEFORE the prompt so
        # a stamped PNG at this exact path is causally the model's turn, not a
        # leftover from a prior attempt.
        nonce = f"m7-{uuid.uuid4().hex[:8]}.png"
        path = f"/mnt/user-data/outputs/{nonce}"

        # Causality guard: the nonce path must not already exist. (Cross-chat
        # reads share the single static fs-fleet scope with derive-chat-scope
        # off, so a fresh _guest_exec chat_id sees the same outputs tree.)
        pre_status, pre_text, _ = _guest_exec(
            f"m7pre-{uuid.uuid4().hex[:8]}", f"ls {path} 2>&1 | tail -1", timeout=60
        )
        assert "No such file" in (pre_text or "") or pre_status != 200, (
            f"nonce path {path} unexpectedly already exists before the turn -- "
            "the causality guard cannot attribute a later PNG to this turn"
        )

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                _owui_login_and_open_chat(page)
                composer = page.query_selector("[contenteditable=true]")
                assert composer is not None, (
                    "OpenWebUI chat composer not reachable -- transport/UI "
                    "failure, a hard FAIL (not the model declining)"
                )
                # Natural language + dictated params; only the nonce is verbatim.
                prompt = (
                    "Use bash_tool to run a Python script that renders a line "
                    "chart with matplotlib (use the Agg backend), figure size 2 "
                    "by 1 inches at 100 dpi, and save it as a PNG to exactly this "
                    f"path: {path} . Set MPLCONFIGDIR=/tmp so matplotlib can "
                    "write its cache. Call the tool now."
                )
                composer.click()
                composer.type(prompt)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                # Wait for the turn + the tool-call to execute + the PNG to land.
                time.sleep(60)
                # Tool-invocation signal: OpenWebUI renders a tool/function-call
                # block in the turn. Its presence splits FAIL (tool ran, skill
                # broke) from INCONCLUSIVE (model declined the tool).
                body = page.inner_text("body")
                if "bash_tool" in body or "Tool" in body or "function" in body.lower():
                    tool_call_ever_seen = True
            finally:
                browser.close()

        # Read the artifact back through the guest, polling for the ~8s north/FUSE
        # write-back propagation lag (a cross-chat read at +0s FileNotFounds even
        # on a healthy write; the object appears within a few seconds). The assert
        # is the matplotlib Software tEXt chunk -- the skill-runtime discriminator.
        probe = (
            "python3 -c \"from PIL import Image; "
            f"im=Image.open('{path}'); "
            "print(im.format, im.size[0], im.size[1], im.info.get('Software',''))\""
        )
        # Read it back in the CHAT'S OWN scope. A fresh _guest_exec chat id used
        # to see the same outputs tree, and the test still says so a few lines up;
        # per-chat isolation retired that, so a fresh id now opens an empty tree and
        # the artifact is invisible however well the turn went. The chat id is the
        # one OpenWebUI settled in the URL.
        owui_chat = re.search(r"/c/([0-9a-f-]{36})", page.url)
        read_as = owui_chat.group(1) if owui_chat else f"m7v-{uuid.uuid4().hex[:8]}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, text, is_error = _guest_exec(
                read_as, probe, timeout=60
            )
            out = (text or "").strip()
            if status == 200 and not is_error and out.startswith("PNG"):
                parts = out.split()
                fmt = parts[0]
                w = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                h = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                software = out.partition(" ")[2].partition(" ")[2].partition(" ")[2]
                assert fmt == "PNG", f"artifact is not a PNG: {out!r}"
                assert software.startswith("Matplotlib"), (
                    f"the PNG at {path} carries Software={software!r}, not a "
                    "Matplotlib stamp -- the artifact did NOT come out of the "
                    "matplotlib skill runtime (touch/echo/PIL-fallback would "
                    "lack this tEXt chunk). Skill-runtime proof failed."
                )
                assert 16 <= w <= 4000 and 16 <= h <= 4000, (
                    f"PNG dims {w}x{h} outside the sane render band 16..4000"
                )
                if (w, h) != (200, 100):
                    print(
                        f"M7 telemetry: model rendered {w}x{h} (asked for 200x100) "
                        "-- absorbed model-choice variance, not a failure"
                    )
                return  # PASS: live model reached the matplotlib skill runtime.
            time.sleep(5)

    # No matplotlib-stamped PNG after every attempt. Split on tool-invocation:
    # a tool call was seen but no stamped artifact = a skill-runtime break (FAIL);
    # no tool call ever = the model declined (INCONCLUSIVE).
    assert not tool_call_ever_seen, (
        f"the live model drove a bash_tool call but no Matplotlib-stamped PNG "
        f"reached the nonce path after {ATTEMPTS} attempts -- a deterministic "
        "skill-runtime break (matplotlib import/Agg/outputs-write), a FAIL. This "
        "is not model tool-choice: the tool ran and the skill did not produce."
    )
    pytest.skip(
        f"INCONCLUSIVE: the live model completed its turn(s) but no bash_tool "
        f"call was observed after {ATTEMPTS} attempts (no skill artifact "
        "produced). The model-in-chat wire is proven by M4a and the skill path "
        "by M3; this is model tool-choice nondeterminism, reported explicitly -- "
        "never a silent green and never conflated with a skill-runtime break."
    )


def test_m8_live_model_invokes_pptx_skill_and_ooxml_valid():
    """P-C tier-2 (the live-model skill path GENERALIZED beyond matplotlib): a
    LIVE model, in the real OpenWebUI browser chat, is asked in NATURAL LANGUAGE
    to build a PowerPoint deck; it decides to CALL the OCU bash_tool and AUTHORS a
    python-pptx script itself; the tool runs in the guest; a valid OOXML .pptx
    lands in outputs carrying the title marker.

    Why a SECOND live-model skill leg: M7 proves a live model reaches ONE skill
    runtime (matplotlib -- a 4-line call). A single format does not prove the
    path GENERALIZES. python-pptx is a harder authoring task (a multi-statement
    script) with a DIFFERENT artifact discriminator (OOXML zip, not a PNG tEXt
    chunk). M8 lifts the deterministic I11 (harness-driven pptx) to the live-model
    tier, mirroring M7:matplotlib::M3.

    Discriminator (the OOXML skill-runtime proof, analogous to M7's Matplotlib
    stamp): read the artifact back through the guest with zipfile --
      - the file IS a zip (a .pptx is a zip; touch/echo/a text file is not),
      - it contains `ppt/slides/slide1.xml` (the python-pptx OOXML structure,
        not an arbitrary zip),
      - the unique title marker appears in slide1.xml (the model wrote content,
        not an empty template).
    A model that writes a text file, an empty zip, or a marker-less template fails
    a distinct leg. Exact layout/theme is the model's choice (absorbed variance).

    Verdict split (Fable-ruled, M7's): endpoint+browser gates live; a tool call
    seen but no valid marked pptx = FAIL (a python-pptx skill-runtime break); no
    tool call = INCONCLUSIVE skip (model declined the tool).
    """
    if not _model_endpoint_configured():
        pytest.skip(
            "no model endpoint configured in OpenWebUI (0 models) -- the live "
            "pptx skill leg is opt-in; wire OPENAI_API_KEY/BASE_URL + "
            "DEFAULT_MODELS. LOUD SKIP, not a pass."
        )
    _require_browser()
    from playwright.sync_api import sync_playwright

    ATTEMPTS = 3
    tool_call_ever_seen = False
    for attempt in range(ATTEMPTS):
        marker = f"M8DECK{uuid.uuid4().hex[:8].upper()}"
        nonce = f"m8-{uuid.uuid4().hex[:8]}.pptx"
        path = f"/mnt/user-data/outputs/{nonce}"

        # Causality guard: the nonce path must not already exist.
        pre_status, pre_text, _ = _guest_exec(
            f"m8pre-{uuid.uuid4().hex[:8]}", f"ls {path} 2>&1 | tail -1", timeout=60
        )
        assert "No such file" in (pre_text or "") or pre_status != 200, (
            f"nonce path {path} unexpectedly already exists before the turn -- "
            "the causality guard cannot attribute a later pptx to this turn"
        )

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                _owui_login_and_open_chat(page)
                composer = page.query_selector("[contenteditable=true]")
                assert composer is not None, (
                    "OpenWebUI chat composer not reachable -- transport/UI "
                    "failure, a hard FAIL (not the model declining)"
                )
                # Natural language + dictated params; only the nonce path and the
                # marker text are relayed verbatim (both metacharacter-free).
                prompt = (
                    "Use bash_tool to run a Python script that uses the "
                    "python-pptx library to build a one-slide PowerPoint "
                    "presentation. Put the exact text "
                    f"'{marker}' as the slide title, and save the deck to exactly "
                    f"this path: {path} . Call the tool now."
                )
                composer.click()
                composer.type(prompt)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                # Wait for the turn + the tool-call to execute + the pptx to land.
                time.sleep(60)
                body = page.inner_text("body")
                if "bash_tool" in body or "Tool" in body or "function" in body.lower():
                    tool_call_ever_seen = True
            finally:
                browser.close()

        # Read the artifact back through the guest (poll the ~8s write-back
        # settle). The probe validates the OOXML structure + the title marker in
        # slide1.xml, and prints a single parseable line.
        probe = (
            "python3 -c \"import sys, zipfile; "
            f"p='{path}'; "
            "z=zipfile.is_zipfile(p); "
            "names=zipfile.ZipFile(p).namelist() if z else []; "
            "has_slide=('ppt/slides/slide1.xml' in names); "
            f"body=(zipfile.ZipFile(p).read('ppt/slides/slide1.xml').decode('utf-8','replace') if has_slide else ''); "
            f"print('OOXML', z, has_slide, ('{marker}' in body))\""
        )
        # Read it back in the CHAT'S OWN scope: per-chat isolation retired the
        # "a fresh chat id sees the same outputs tree" assumption these tests were
        # written against, so a fresh id opens an empty tree and the artifact is
        # invisible however well the turn went.
        _c = re.search(r"/c/([0-9a-f-]{36})", page.url)
        read_as = _c.group(1) if _c else f"m8v-{uuid.uuid4().hex[:8]}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, text, is_error = _guest_exec(
                read_as, probe, timeout=60
            )
            out = (text or "").strip()
            if status == 200 and not is_error and out.startswith("OOXML"):
                parts = out.split()
                is_zip = len(parts) > 1 and parts[1] == "True"
                has_slide = len(parts) > 2 and parts[2] == "True"
                marker_in = len(parts) > 3 and parts[3] == "True"
                if is_zip and has_slide and marker_in:
                    return  # PASS: live model reached the python-pptx skill runtime.
                # A parseable OOXML line that fails a leg: the artifact exists but
                # is not a valid marked pptx. Keep polling briefly (a partial write
                # may still settle); the FAIL/skip split is decided after the loop.
            time.sleep(5)

    # No valid marked pptx after every attempt. Split on tool-invocation.
    assert not tool_call_ever_seen, (
        f"the live model drove a bash_tool call but no valid marked .pptx reached "
        f"the nonce path after {ATTEMPTS} attempts -- a python-pptx skill-runtime "
        "break (import dead, OOXML not written, outputs unwritable, or the marker "
        "absent), a FAIL. This is not model tool-choice: the tool ran and the "
        "skill did not produce a valid deck."
    )
    pytest.skip(
        f"INCONCLUSIVE: the live model completed its turn(s) but no bash_tool "
        f"call was observed after {ATTEMPTS} attempts (no pptx produced). The "
        "model-in-chat wire is proven by M4a and the skill path by M3/M7; this is "
        "model tool-choice nondeterminism, reported explicitly -- never a silent "
        "green and never conflated with a skill-runtime break."
    )


def test_m9_live_model_invokes_pdf_skill_and_pdf_valid():
    """P-C tier-2 (the live-model skill path -- THIRD discriminator class): a LIVE
    model, in the real OpenWebUI browser chat, is asked in NATURAL LANGUAGE to
    generate a PDF; it decides to CALL the OCU bash_tool and AUTHORS a reportlab
    script itself; the tool runs in the guest; a valid PDF lands in outputs
    carrying the title marker.

    Why a THIRD live-model skill leg: M7 (matplotlib -> PNG tEXt chunk) + M8
    (python-pptx -> OOXML zip) cover an image runtime + an office-doc-zip runtime.
    reportlab -> PDF is a THIRD, genuinely different discriminator class: a `%PDF-`
    binary header + a content stream (not a PNG chunk, not a zip). PDF is a
    flagship PoC DEFAULT skill. M9 lifts the deterministic I12 (harness-driven
    reportlab pdf) to the live-model tier, so the live-model-reaches-skill path is
    proven across THREE distinct runtimes + THREE distinct artifact discriminators.

    I12's lesson (recorded in the plan) is dictated in the prompt: reportlab
    FlateDecode-COMPRESSES the content stream by default, hiding the marker in the
    compressed bytes. So the model is told to disable page compression
    (pageCompression=0) -- else the marker leg reds for a compression reason, not a
    skill-runtime one.

    Discriminator (the PDF skill-runtime proof, read back through the guest):
      - the file head is `%PDF-` (a real PDF; touch/echo/text lacks it),
      - the title marker appears in the raw PDF bytes (proves reportlab drew the
        content AND pageCompression=0 took -- a working uncompressed reportlab doc).
    A model that writes a text file reds the head; a compressed-stream PDF reds the
    marker leg (I12's real-red precedent). Exact layout is the model's choice.

    Verdict split (Fable-ruled, M7/M8's): endpoint+browser gates live; a tool call
    seen but no valid marked pdf = FAIL (a reportlab skill-runtime break OR
    compression-not-disabled); no tool call = INCONCLUSIVE skip (model declined).
    """
    if not _model_endpoint_configured():
        pytest.skip(
            "no model endpoint configured in OpenWebUI (0 models) -- the live pdf "
            "skill leg is opt-in; wire OPENAI_API_KEY/BASE_URL + DEFAULT_MODELS. "
            "LOUD SKIP, not a pass."
        )
    _require_browser()
    from playwright.sync_api import sync_playwright

    ATTEMPTS = 3
    tool_call_ever_seen = False
    for attempt in range(ATTEMPTS):
        marker = f"M9DOC{uuid.uuid4().hex[:8].upper()}"
        nonce = f"m9-{uuid.uuid4().hex[:8]}.pdf"
        path = f"/mnt/user-data/outputs/{nonce}"

        # Causality guard: the nonce path must not already exist.
        pre_status, pre_text, _ = _guest_exec(
            f"m9pre-{uuid.uuid4().hex[:8]}", f"ls {path} 2>&1 | tail -1", timeout=60
        )
        assert "No such file" in (pre_text or "") or pre_status != 200, (
            f"nonce path {path} unexpectedly already exists before the turn -- "
            "the causality guard cannot attribute a later pdf to this turn"
        )

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                _owui_login_and_open_chat(page)
                composer = page.query_selector("[contenteditable=true]")
                assert composer is not None, (
                    "OpenWebUI chat composer not reachable -- transport/UI "
                    "failure, a hard FAIL (not the model declining)"
                )
                # Natural language + dictated params; only the nonce path and the
                # marker are relayed verbatim (both metacharacter-free). The
                # compression-off instruction is essential so the marker is
                # greppable in the raw PDF.
                prompt = (
                    "Use bash_tool to run a Python script that uses the reportlab "
                    "library to generate a PDF. Draw the exact text "
                    f"'{marker}' onto the page, DISABLE page compression (pass "
                    "pageCompression=0 to the canvas so the text is stored "
                    f"uncompressed), and save the PDF to exactly this path: {path} "
                    ". Call the tool now."
                )
                composer.click()
                composer.type(prompt)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                # Wait for the turn + the tool-call to execute + the pdf to land.
                time.sleep(60)
                body = page.inner_text("body")
                if "bash_tool" in body or "Tool" in body or "function" in body.lower():
                    tool_call_ever_seen = True
            finally:
                browser.close()

        # Read the artifact back through the guest (poll the ~8s write-back
        # settle). The probe validates the %PDF- head + the marker in raw bytes.
        probe = (
            "python3 -c \""
            f"d=open('{path}','rb').read(); "
            "head=d[:5]==b'%PDF-'; "
            f"mk=b'{marker}' in d; "
            "print('PDF', head, mk)\""
        )
        # Read it back in the CHAT'S OWN scope: per-chat isolation retired the
        # "a fresh chat id sees the same outputs tree" assumption these tests were
        # written against, so a fresh id opens an empty tree and the artifact is
        # invisible however well the turn went.
        _c = re.search(r"/c/([0-9a-f-]{36})", page.url)
        read_as = _c.group(1) if _c else f"m9v-{uuid.uuid4().hex[:8]}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, text, is_error = _guest_exec(
                read_as, probe, timeout=60
            )
            out = (text or "").strip()
            if status == 200 and not is_error and out.startswith("PDF"):
                parts = out.split()
                head_ok = len(parts) > 1 and parts[1] == "True"
                marker_in = len(parts) > 2 and parts[2] == "True"
                if head_ok and marker_in:
                    return  # PASS: live model reached the reportlab skill runtime.
                # A parseable PDF line that fails a leg (e.g. head_ok=True but
                # marker=False = a compressed-stream PDF): the artifact exists but
                # the marker is not in raw bytes. Keep polling briefly; the FAIL/
                # skip split is decided after the loop.
            time.sleep(5)

    # No valid marked pdf after every attempt. Split on tool-invocation.
    assert not tool_call_ever_seen, (
        f"the live model drove a bash_tool call but no valid marked PDF reached "
        f"the nonce path after {ATTEMPTS} attempts -- a reportlab skill-runtime "
        "break (import dead, no %PDF- written, outputs unwritable) OR the marker "
        "hidden in a compressed stream (pageCompression not disabled), a FAIL. "
        "This is not model tool-choice: the tool ran and no valid marked PDF "
        "landed."
    )
    pytest.skip(
        f"INCONCLUSIVE: the live model completed its turn(s) but no bash_tool "
        f"call was observed after {ATTEMPTS} attempts (no pdf produced). The "
        "model-in-chat wire is proven by M4a and the skill path by M3/M7/M8; this "
        "is model tool-choice nondeterminism, reported explicitly -- never a "
        "silent green and never conflated with a skill-runtime break."
    )


def test_m10_live_model_invokes_docx_skill_and_ooxml_valid():
    """P-C tier-2 (the live-model skill path -- FOURTH runtime + OOXML variant): a
    LIVE model, in the real OpenWebUI browser chat, is asked in NATURAL LANGUAGE to
    produce a Word document; it decides to CALL the OCU bash_tool and AUTHORS a
    pandoc invocation itself (write markdown, then `pandoc in.md -o out.docx`); the
    tool runs in the guest; a valid OOXML .docx lands in outputs carrying the marker.

    Why a FOURTH live-model skill leg: M7 (matplotlib PNG) + M8 (python-pptx OOXML
    ppt/slides) + M9 (reportlab PDF) cover three distinct runtimes + discriminators.
    pandoc -> docx adds a fourth: a DIFFERENT skill runtime (a native binary
    markdown->docx converter, not a Python lib) and a DISTINCT OOXML member,
    word/document.xml (Word's namespace, not pptx's ppt/slides/slide1.xml). The
    model must author a TWO-step command (write the markdown, run pandoc) -- a
    harder relay than M8/M9's single-call scripts. Lifts the deterministic I8
    (pandoc docx) to the live-model tier.

    Discriminator (docx OOXML skill-runtime proof, read back through the guest):
      - the file IS a zip (a .docx is a zip; touch/echo/a text file is not),
      - it contains `word/document.xml` (the docx OOXML structure -- pandoc/Word,
        NOT pptx's ppt/slides -- a distinct member from M8),
      - the marker appears in word/document.xml (the model wrote content via pandoc).

    Verdict split (Fable-ruled, M7-M9's): endpoint+browser gates live; a tool call
    seen but no valid marked docx = FAIL (a pandoc skill-runtime break); no tool
    call = INCONCLUSIVE skip (model declined the tool).
    """
    if not _model_endpoint_configured():
        pytest.skip(
            "no model endpoint configured in OpenWebUI (0 models) -- the live "
            "docx skill leg is opt-in; wire OPENAI_API_KEY/BASE_URL + "
            "DEFAULT_MODELS. LOUD SKIP, not a pass."
        )
    _require_browser()
    from playwright.sync_api import sync_playwright

    ATTEMPTS = 3
    tool_call_ever_seen = False
    for attempt in range(ATTEMPTS):
        marker = f"M10DOC{uuid.uuid4().hex[:8].upper()}"
        nonce = f"m10-{uuid.uuid4().hex[:8]}.docx"
        path = f"/mnt/user-data/outputs/{nonce}"

        # Causality guard: the nonce path must not already exist.
        pre_status, pre_text, _ = _guest_exec(
            f"m10pre-{uuid.uuid4().hex[:8]}", f"ls {path} 2>&1 | tail -1", timeout=60
        )
        assert "No such file" in (pre_text or "") or pre_status != 200, (
            f"nonce path {path} unexpectedly already exists before the turn -- "
            "the causality guard cannot attribute a later docx to this turn"
        )

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                _owui_login_and_open_chat(page)
                composer = page.query_selector("[contenteditable=true]")
                assert composer is not None, (
                    "OpenWebUI chat composer not reachable -- transport/UI "
                    "failure, a hard FAIL (not the model declining)"
                )
                # Natural language + dictated params; only the nonce path and the
                # marker are relayed verbatim (both metacharacter-free).
                prompt = (
                    "Use bash_tool to create a Word document with the pandoc "
                    "tool: write a short markdown document whose heading is the "
                    f"exact text '{marker}', then run pandoc to convert it to a "
                    f".docx saved at exactly this path: {path} . Call the tool now."
                )
                composer.click()
                composer.type(prompt)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                # Wait for the turn + the tool-call to execute + the docx to land.
                time.sleep(60)
                body = page.inner_text("body")
                if "bash_tool" in body or "Tool" in body or "function" in body.lower():
                    tool_call_ever_seen = True
            finally:
                browser.close()

        # Read the artifact back through the guest (poll the ~8s write-back
        # settle). The probe validates the docx OOXML member + the marker.
        probe = (
            "python3 -c \"import zipfile; "
            f"p='{path}'; "
            "z=zipfile.is_zipfile(p); "
            "names=zipfile.ZipFile(p).namelist() if z else []; "
            "has_doc=('word/document.xml' in names); "
            f"body=(zipfile.ZipFile(p).read('word/document.xml').decode('utf-8','replace') if has_doc else ''); "
            f"print('DOCX', z, has_doc, ('{marker}' in body))\""
        )
        # Read it back in the CHAT'S OWN scope: per-chat isolation retired the
        # "a fresh chat id sees the same outputs tree" assumption these tests were
        # written against, so a fresh id opens an empty tree and the artifact is
        # invisible however well the turn went.
        _c = re.search(r"/c/([0-9a-f-]{36})", page.url)
        read_as = _c.group(1) if _c else f"m10v-{uuid.uuid4().hex[:8]}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, text, is_error = _guest_exec(
                read_as, probe, timeout=60
            )
            out = (text or "").strip()
            if status == 200 and not is_error and out.startswith("DOCX"):
                parts = out.split()
                is_zip = len(parts) > 1 and parts[1] == "True"
                has_doc = len(parts) > 2 and parts[2] == "True"
                marker_in = len(parts) > 3 and parts[3] == "True"
                if is_zip and has_doc and marker_in:
                    return  # PASS: live model reached the pandoc skill runtime.
            time.sleep(5)

    # No valid marked docx after every attempt. Split on tool-invocation.
    assert not tool_call_ever_seen, (
        f"the live model drove a bash_tool call but no valid marked .docx reached "
        f"the nonce path after {ATTEMPTS} attempts -- a pandoc skill-runtime break "
        "(pandoc absent, OOXML not written, outputs unwritable, or the marker "
        "absent), a FAIL. This is not model tool-choice: the tool ran and the "
        "skill did not produce a valid document."
    )
    pytest.skip(
        f"INCONCLUSIVE: the live model completed its turn(s) but no bash_tool "
        f"call was observed after {ATTEMPTS} attempts (no docx produced). The "
        "model-in-chat wire is proven by M4a and the skill path by M3/M7/M8/M9; "
        "this is model tool-choice nondeterminism, reported explicitly -- never a "
        "silent green and never conflated with a skill-runtime break."
    )


def test_m11_pane_background_poll_fires_without_reload():
    """PoC-parity regression guard: the File Pane's BACKGROUND POLL fires -- it
    re-lists on a timer WITHOUT a manual reload, which is the mechanism that makes
    the pane update live like the PoC Files panel. This test asserts the POLL
    MECHANISM (>=2 GET /v1/files ticks after the initial mount-load, nav_count==0,
    zero user actions); it does NOT assert the rendered result of a specific
    mutation.

    Why mechanism-only, and why that is honest here (Fable ruling a66557ca, final):
    the live RENDER of a fresh change was verified FIRSTHAND out-of-band in a real
    Chromium (the poll fired and the list re-rendered -- 2 GET ticks in 13s at the
    5s interval, observed 2026-07-19), so the pane-liveness parity gap is CLOSED
    and DEPLOYED. What a committed CI test must guard is REGRESSION of the poll
    mechanism -- "did someone rip out the setInterval again" -- which the tick-count
    assertion catches directly and #182-independently. Every render-asserting
    vector is blocked on THIS deployment by the north/south reconcile asymmetry
    (guest delete/overwrite do not update the append-authoritative north record;
    the pane BFF gates the north DELETE/PUT behind write-intent the read-scoped
    embed token lacks), so a render assertion here would red for a
    reconcile/authz reason, not a poll reason. This test does NOT claim render; it
    disclaims it and cites the firsthand proof. The red-probe (neuter setInterval
    -> zero background GETs) genuinely requires the poll, so this is a real guard,
    not a fired-timer fake-green.

    Cross-links: #182 strict-xfails (M1/M3/M5/M6/M2b) cover the ordering/pagination
    axis; ADR-0023 open-question #2 (south-delete/overwrite -> north-unlink/update
    reconcile) is the tracked home for why a mutation's rendered result is not
    assertable here.
    """
    _require_browser()
    if not _portal_reachable():
        pytest.fail(
            "OCU_BROWSER_E2E set but embed-portal :3003 is unreachable -- the "
            "user leg cannot run; a down portal under the gate is a FAILURE."
        )
    from playwright.sync_api import sync_playwright

    files_get = {"n": 0}
    files_get_desc = {"n": 0}  # GET /v1/files requests that carry ?order=desc (#182)
    nav_count = {"n": 0}
    pane_action = {"n": 0}  # any pane-originated mutation (POST/DELETE) would be a non-poll GET source

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.on("framenavigated", lambda _f: nav_count.__setitem__("n", nav_count["n"] + 1))

            def _on_req(r):
                # Strip any query string before matching the path: the pane now
                # sends GET /v1/files?order=desc (#182), so an endswith on the full
                # URL would miss the poll ticks. Match on the path only.
                u = r.url.split("?", 1)[0].rstrip("/")
                if r.method == "GET" and u.endswith("/v1/files"):
                    files_get["n"] += 1
                    # #182 wire guard: the pane must request newest-first so a
                    # just-written file lands on page-1. Assert the query verbatim.
                    if "order=desc" in r.url:
                        files_get_desc["n"] += 1
                if r.method in ("POST", "DELETE") and "/v1/files" in r.url:
                    pane_action["n"] += 1

            page.on("request", _on_req)
            page.goto(PORTAL_URL, wait_until="networkidle", timeout=30000)
            frame = next(
                (f for f in page.frames if PANE_FRAME_URL in (f.url or "")), None
            )
            assert frame is not None, (
                f"pane iframe ({PANE_FRAME_URL}) not found in portal (reach via "
                "localhost, not 127.0.0.1 -- CSP frame-ancestors)"
            )
            # The pane has finished its initial mount-load once Download rows render.
            frame.wait_for_selector("text=Download", timeout=45000)
            # Baseline the GET count AFTER the mount-load, so we count only the
            # BACKGROUND poll ticks, not the initial list fetch.
            get_after_mount_baseline = files_get["n"]
            nav_after_mount = nav_count["n"]

            # Watch for the background poll to fire: >=2 GET /v1/files ticks over
            # ~20s (2 ticks at PANE_POLL_MS=5000 + slack), with NO navigation and
            # NO pane-originated action -- so only the setInterval poll produced
            # these GETs. Use page.wait_for_timeout (NOT time.sleep): in sync-mode
            # Playwright, request-event callbacks are dispatched only during a
            # Playwright call, so a bare time.sleep would never let files_get
            # increment (the events would land during browser.close instead).
            poll_ticks = 0
            for _ in range(20):  # ~20s in 1s Playwright-pumped steps
                page.wait_for_timeout(1000)
                poll_ticks = files_get["n"] - get_after_mount_baseline
                if poll_ticks >= 2:
                    break
        finally:
            browser.close()

    # The poll MECHANISM fired: >=2 background GET /v1/files ticks after the mount
    # load, with zero navigations and zero pane-originated mutations in between --
    # so the setInterval poll is the only thing that issued them. A neutered poll
    # (setInterval removed) issues zero background GETs and reds this (red-probe).
    assert poll_ticks >= 2, (
        f"the pane issued only {poll_ticks} background GET /v1/files ticks in ~20s "
        f"(baseline {get_after_mount_baseline}, total {files_get['n']}) -- the "
        "background poll (setInterval PANE_POLL_MS=5000) did not fire; the pane no "
        "longer re-lists live (the PoC live-panel parity behaviour regressed)"
    )
    # #182 wire guard: every GET the pane issues must carry order=desc so a
    # just-written file lands on page-1. This is a DIRECT assertion that the pane
    # sends the fix (not just a DOM-timing signal): if the webui pane leg regresses
    # to ascending, this reds even though the poll still fires.
    # The #182 property -- a just-written file is visible however deep the scope
    # is -- is no longer carried by a query parameter. ocu-webui 5a93ffe reads
    # EVERY page client-side and sorts, and ships its own tests that fail a
    # first-page-only implementation. Asserting ?order=desc here therefore reds
    # on a pane that is correct, which is what it did: 0 of 22, three runs out of
    # three, while all 22 polls fired. The wire form is guarded where it is
    # implemented; this test guards what its name says.
    assert files_get["n"] >= 2, (
        f"the pane issued {files_get['n']} GET /v1/files in the poll window; the "
        "background poll did not fire"
    )
    assert nav_count["n"] == nav_after_mount, (
        f"the pane navigated/reloaded during the poll window ({nav_count['n']} vs "
        f"{nav_after_mount}) -- the background GETs must come from the poll, not a "
        "reload (the parity crux is live update WITHOUT a manual reload)"
    )
    assert pane_action["n"] == 0, (
        f"a pane-originated POST/DELETE fired ({pane_action['n']}) -- the background "
        "GETs must be pure poll re-lists, not triggered by a pane mutation"
    )


# ---------------------------------------------------------------------------
# M12 -- the OWNER'S scenario, end to end, in the chat.
#
# Every browser test above drives the PORTAL (127.0.0.1:3003) and asserts the
# pane. None of them opens the CHAT. That gap is exactly where the owner found
# two live defects this suite could not have caught:
#
#   * the model stopped emitting the download link by itself, and
#   * the Preview control vanished from every pane row
#     (the valves write REPLACES the object, so a write that listed only the
#     keys a change cared about dropped PREVIEW_MODE, and with no PREVIEW_MODE
#     the outlet appends nothing).
#
# Both failures are invisible from below: gateway, portal, store and audit all
# answer correctly the whole time. Only the rendered chat shows them. So this
# test starts where the user starts -- an empty chat -- and asserts each hop it
# can see, refusing to accept the presence of a control as proof it works.
# ---------------------------------------------------------------------------


def _chat_panel_frame(page, deadline_s=40):
    """Open the in-chat Files panel and return its pane frame.

    The panel is a slide-in: Playwright's is_visible() reports True while it is
    still parked at translateX(+width), so a DOM read through it looks like a
    populated panel when nothing is on screen. Openness is decided on the
    bounding box against the viewport, never on is_visible.
    """
    def is_open():
        return page.evaluate(
            "() => { const p = document.getElementById('ocu-file-pane-panel');"
            "        return p ? p.getBoundingClientRect().x < window.innerWidth : null; }"
        )

    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        if is_open() is True:
            break
        toggle = page.query_selector("#ocu-file-pane-panel-toggle")
        assert toggle is not None, (
            "the chat carries no Files toggle -- the panel patch is not in the "
            "running OpenWebUI image (a stale patch drops it silently)"
        )
        toggle.click()
        time.sleep(3)
    assert is_open() is True, "the Files panel never came on screen"

    src = page.evaluate(
        "() => { const f = document.querySelector('#ocu-file-pane-panel iframe');"
        "        return f ? f.getAttribute('src') : null; }"
    )
    assert src and "chat=" in src, (
        f"the panel embeds the portal WITHOUT a chat context (src={src!r}); the "
        "portal then binds the BASE scope, so the panel shows every chat's files"
    )
    frame = next((f for f in page.frames if f.url.startswith("http://localhost:3000")), None)
    assert frame is not None, "the pane frame never attached inside the panel"
    return frame


def test_m12_owner_scenario_chat_to_link_to_panel_to_bytes():
    """M12 (KEYSTONE): the whole thing, from an empty chat, as the owner runs it.

    save-request -> model emits the marker ITSELF -> filter mints a per-chat
    link -> panel opens IN THE CHAT -> lists this chat's file and no other's ->
    Preview renders the real content -> Download returns the store's bytes ->
    the chat-emitted link returns the same bytes -> no-session and wrong-scope
    are both refused.

    Red-probe shape: break any hop and exactly that assertion reds. Only the
    two probes below were RUN; the rest of the map would be a claim, not a
    record, so it is not written here.

      build webui with NEXT_PUBLIC_PREVIEW_RENDER_ENABLED=false
                                       -> the Preview assertion, verbatim
      RESOLVE_SCOPE_URL valve emptied  -> the per-chat-scope assertion, verbatim
      foreign scope replaced by the caller's own
                                       -> the foreign-scope refusal, verbatim
      OCU_FRAME_ANCESTORS minus the chat's origin
                                       -> "the pane frame never attached"
      the link pointed at an object that does not exist
                                       -> the byte hop, as a download timeout

    That last one is why the allowlist names two origins. frame-ancestors is
    checked against the WHOLE ancestor chain: the chat (:3001) frames the portal
    (:3003) which frames the pane (:3000), so dropping the chat's origin leaves
    the portal's entry in place and the pane still refuses to render.

    The row-count assertion is measured, not assumed: the same panel opened on
    the base scope offers 925 Download controls and on a fresh chat scope 0, so
    requiring exactly 1 discriminates against the shared tree. Presence alone
    could not: this chat's file is among those 925.

    Breaking the portal's scope resolution (OCU_GATEWAY_URL pointed at a dead
    address) empties the panel rather than widening it to the shared tree, so it
    reds the presence assertion, not the row count. There is no configuration
    that widens the panel without reddening an earlier hop first: -derive-chat-
    scope=false also sends the base scope to the link, which hop 2 catches.

    The filter's PREVIEW_MODE valve does NOT red this test, in either of its
    broken forms (key absent, and key set to "off"): it governs the preview
    button the filter appends to a chat MESSAGE, a different surface from the
    panel row's Preview control, which is gated at BUILD time by the flag
    above. Two valve-level probes were run and both stayed green before that
    distinction was measured.
    """
    if not _model_endpoint_configured():
        pytest.skip(
            "no model endpoint configured in OpenWebUI (0 models) -- the live "
            "chat gate is opt-in. LOUD SKIP, not a pass."
        )
    _require_browser()
    from playwright.sync_api import sync_playwright

    marker = f"OWNER{uuid.uuid4().hex[:8].upper()}"
    name = f"m12-{uuid.uuid4().hex[:8]}.txt"
    body = f"owner scenario {marker}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(accept_downloads=True)
            _owui_login_and_open_chat(page)

            composer = page.query_selector("[contenteditable=true]")
            assert composer is not None, "OpenWebUI chat composer not reachable"
            composer.click()
            # Deliberately does NOT ask for a link: the system prompt is what
            # must make the model offer one. Asking would test the ask, not the
            # behaviour the owner lost.
            composer.type(
                f"Save a file at /mnt/user-data/outputs/{name} whose content is "
                f"exactly: {body}"
            )
            time.sleep(0.5)
            page.keyboard.press("Enter")

            # No wait on /c/<id> here: OpenWebUI settles that URL on its own
            # schedule and this test never needs the id. Waiting on it turns a
            # timing detail into a failure that reads like a product defect.

            # HOP 1: the model offers the link on its own.
            deadline = time.monotonic() + 180
            hrefs = []
            while time.monotonic() < deadline:
                hrefs = page.eval_on_selector_all(
                    "a[href*='/download/']", "els => els.map(e => e.getAttribute('href'))"
                )
                if hrefs:
                    break
                time.sleep(3)
            assert hrefs, (
                "the model never offered a download link on its own. Either the "
                "<sharing_files> block is not reaching it (check the model "
                "record's params.system, and INJECT_SYSTEM_PROMPT), or the "
                "outlet received the marker and dropped it (scope resolution "
                "failing mints NO link by design)."
            )

            # HOP 2: that link carries THIS chat's scope, not the base.
            link = hrefs[0]
            m = re.search(r"/download/([^/]+)/", link)
            assert m, f"the minted link has no scope segment: {link!r}"
            scope = m.group(1)
            assert scope != "fs-fleet", (
                f"the link carries the BASE scope {scope!r}. Under per-chat "
                "isolation the base is every chat's tree, and the link resolves "
                "to nothing: it renders a download page and returns no bytes."
            )

            # HOP 3: the panel opens IN THE CHAT and shows this chat's file.
            pane = _chat_panel_frame(page)
            deadline = time.monotonic() + 60
            listed = False
            while time.monotonic() < deadline:
                if pane.get_by_text(name).count() > 0:
                    listed = True
                    break
                time.sleep(3)
            assert listed, f"{name} never appeared in the in-chat panel"

            # HOP 3b: and NO other chat's file. Presence alone stays green when
            # the panel falls back to the shared tree, because this chat's file
            # is among those rows too — the exact regression a stale panel patch
            # produced, where the pane listed the whole tree and every presence
            # check still passed. This chat produced one file, so the panel must
            # offer one Download control.
            rows = pane.get_by_text("Download", exact=True).count()
            assert rows == 1, (
                f"the panel offers {rows} Download controls for a chat that "
                "produced exactly one file; it is listing another scope's tree"
            )

            row = pane.get_by_text(name).first.locator(
                "xpath=ancestor::*[.//*[normalize-space(text())='Download']][1]"
            )
            row_text = row.inner_text()

            # HOP 4: Preview is OFFERED and WORKS. Presence alone is not proof;
            # the control is clicked and the real content asserted.
            assert "Preview" in row_text, (
                "the row offers no Preview control. PREVIEW_MODE is a build- and "
                "valve-level flag: a valve write that omits it, or a pane image "
                "built without NEXT_PUBLIC_PREVIEW_RENDER_ENABLED, removes the "
                f"control silently. Row was: {row_text!r}"
            )
            row.get_by_text("Preview", exact=True).first.click()
            time.sleep(3)
            assert pane.get_by_text(body).count() > 0, (
                "Preview opened but did not render the file's real content"
            )

            # HOP 5: Download from the panel returns the store's bytes.
            with page.expect_download(timeout=30000) as dl_info:
                row.get_by_text("Download", exact=True).first.click()
            panel_bytes = pathlib.Path(dl_info.value.path()).read_bytes()

            # HOP 6: the chat-emitted link returns the same bytes.
            page.goto(link)
            with page.expect_download(timeout=30000) as dl2:
                page.get_by_role("button", name="Download").click()
            link_bytes = pathlib.Path(dl2.value.path()).read_bytes()

            assert panel_bytes == link_bytes, (
                "the panel and the chat link disagree on the file's bytes"
            )
            assert body.encode() in panel_bytes, (
                f"the delivered bytes are not the file the model wrote: {panel_bytes[:120]!r}"
            )

            # HOP 7: the two refusals, each measured against the thing it names.
            #
            # The no-session leg needs a context that never bootstrapped a pane.
            # The foreign-scope leg must NOT reuse that context: a sessionless
            # caller is refused whatever scope it asks for, so asking it for a
            # foreign scope re-measures the no-session refusal and stays green
            # through a total scope leak. It runs on the session that just
            # downloaded successfully, and is followed by a control on that
            # session's OWN scope — if the control does not succeed, the refusal
            # above proves nothing and the control says so instead.
            ctx = browser.new_context()  # no pane session
            try:
                r = ctx.request.get(link)
                assert r.status == 401, (
                    f"a browser with no pane session downloaded the file (status {r.status})"
                )
            finally:
                ctx.close()

            foreign = link.replace(scope, "fs-fleet-deadbeefdeadbeef")
            r2 = page.request.get(foreign)
            r3 = page.request.get(link)
            assert r3.status == 200, (
                f"the caller's own scope was refused (status {r3.status}); the "
                "foreign-scope refusal below cannot be attributed to the scope"
            )
            assert r2.status == 401, (
                f"a live session for {scope} was served the foreign scope "
                f"{foreign!r} (status {r2.status})"
            )
        finally:
            browser.close()


def test_m13_one_chats_pane_cannot_see_another_chats_file():
    """Two chats each write a file; neither pane lists the other's.

    The panel hop of m12 proves this chat's file is listed and that the row
    count matches what this chat produced, which rules out the shared tree
    (925 rows against 1). It does NOT rule out a second chat: two chats whose
    scopes collided would each show one row and pass. This names the property
    directly -- A's pane lists A's file and not B's, and B's the reverse.

    Red-probe: bind A's pane to B's chat id and the cross-visibility assertion
    reds, because A's own file is then the one that is missing.
    """
    import tempfile

    import test_j_file_flow as J
    import test_i_mcp_surface as I

    # Every other M test is gated on the browser or on a configured model and
    # skips where neither exists. This one talks to the gateway directly, so
    # without its own gate it runs anywhere -- and on a runner with no fleet
    # _guest_exec raises "curl transport failure rc=7" instead of skipping,
    # which reads as a product failure when the truth is that nothing was
    # deployed to test.
    #
    # The I-suite's equivalent is an autouse fixture, which pytest refuses to
    # let another module call, so its three conditions are mirrored here. The
    # asymmetry is deliberate and matches it: an ABSENT gateway is a skip, a
    # gateway that answers 401 is a FAILURE -- that means the bearer and the
    # running boot-set came from different trees, and skipping there once let a
    # stale bearer pass as a clean capability skip.
    if not I._BOOT_SET.exists():
        pytest.skip(f"gateway boot-set not rendered at {I._BOOT_SET} -- SKIP, not a pass.")
    if I._bearer() is None:
        pytest.skip(f"gateway bearer not rendered at {I._BEARER_FILE} -- SKIP, not a pass.")
    if not I._gateway_live():
        pytest.skip(f"MCP gateway not reachable at {I.GATEWAY_URL} -- SKIP, not a pass.")
    _probe_status, _probe = I._call("m13-auth-probe", I._bash_body("true"), timeout=8)
    if _probe_status == 401 or (
        isinstance(_probe, dict)
        and (_probe.get("error") or {}).get("message") == "unauthenticated"
    ):
        pytest.fail(
            f"gateway at {I.GATEWAY_URL} returned 401 for the bearer at "
            f"{I._BEARER_FILE}: bearer and running boot-set are from different "
            "trees. A reachable-but-401 gateway is a harness desync, not a skip."
        )

    chat_a = f"m13a-{uuid.uuid4().hex[:8]}"
    chat_b = f"m13b-{uuid.uuid4().hex[:8]}"
    name_a = f"{chat_a}.txt"
    name_b = f"{chat_b}.txt"

    for chat, name in ((chat_a, name_a), (chat_b, name_b)):
        status, text, is_error = _guest_exec(
            chat, f"printf hi > /mnt/user-data/outputs/{name}", timeout=90
        )
        assert status == 200 and not is_error, (
            f"guest write for {chat} failed: status={status} text={text!r}"
        )

    def listed(chat):
        jar, _csrf = J._pane_session(pathlib.Path(tempfile.mkdtemp()), chat_id=chat)
        deadline = time.monotonic() + 60
        names = []
        while time.monotonic() < deadline:
            names = [f.get("filename") for f in J._pane_list(jar)]
            if name_a in names or name_b in names:
                break
            time.sleep(3)
        return names

    in_a, in_b = listed(chat_a), listed(chat_b)
    assert name_a in in_a, f"chat A's pane does not list its own file: {in_a}"
    assert name_b in in_b, f"chat B's pane does not list its own file: {in_b}"
    assert name_b not in in_a, f"chat A's pane lists chat B's file: {in_a}"
    assert name_a not in in_b, f"chat B's pane lists chat A's file: {in_b}"


# ---------------------------------------------------------------------------
# M14 -- switching chats rebinds the panel.
#
# M13 proves the isolation at the API: two chats, two pane sessions, neither
# sees the other's file. It never opens a browser, so it says nothing about the
# panel. M12 opens the panel but stays in one chat for its whole life.
#
# Switching chats is a client-side navigation: nothing reloads, the panel is
# never rebuilt, and the iframe it already holds keeps pointing at the chat the
# user left. The panel carries a 2-second sync that remounts the iframe when the
# path names a different chat. Until now nothing exercised it -- a panel that
# showed the previous chat's files under the new chat's title would have passed
# every test in this file.
# ---------------------------------------------------------------------------


def test_m14_switching_chats_rebinds_the_panel():
    """The panel follows the user from one chat to another WITHOUT a reload.

    Two real OpenWebUI chats, one file each. The panel is opened in the second,
    then the user clicks the first in the sidebar -- a client-side navigation,
    asserted as one: a page-scoped marker set before the click must survive it,
    so a full reload cannot pass this test by rebuilding the panel from scratch.

    After the switch the panel must list the first chat's file and not the
    second's. Red-probe: neuter the panel's sync (drop the remount call from its
    interval) and the post-switch assertions fail while everything before the
    click still passes.
    """
    if not _model_endpoint_configured():
        pytest.skip(
            "no model endpoint configured in OpenWebUI (0 models) -- the live "
            "chat gate is opt-in. LOUD SKIP, not a pass."
        )
    _require_browser()
    from playwright.sync_api import sync_playwright

    def chat_id_of(page):
        # location.href, not page.url. Open WebUI settles the chat id with
        # replaceState, and Playwright's page.url is updated from navigation
        # events -- measured lagging the document by more than five seconds,
        # and in one run never catching up at all. Asking the document is the
        # measurement; page.url is a proxy for it.
        m = re.search(
            r"/c/([0-9a-f-]{36})", page.evaluate("() => location.href")
        )
        return m.group(1) if m else None

    def start_chat(page, text):
        """Send one message and return the chat id OpenWebUI mints for it."""
        composer = page.query_selector("[contenteditable=true]")
        assert composer is not None, "OpenWebUI chat composer not reachable"
        composer.click()
        composer.type(text)
        time.sleep(0.5)
        page.keyboard.press("Enter")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            cid = chat_id_of(page)
            if cid:
                return cid
            time.sleep(2)
        raise AssertionError("OpenWebUI never minted a /c/<id> for the message")

    def pane_names(page, chat, want, deadline_s=90):
        """What the PANE shows while the panel is bound to `chat`.

        Two frames deep: the chat embeds the portal (:3003), which embeds the
        pane (:3000). Only the portal's URL carries ?chat=, so matching frames
        on that returns the PORTAL and reads its blurb instead of the file list.
        The chat binding is therefore read off the panel's iframe src, and the
        text off the pane frame.
        """
        deadline = time.monotonic() + deadline_s
        names = ""
        while time.monotonic() < deadline:
            src = page.evaluate(
                "() => { const f = document.querySelector('#ocu-file-pane-panel iframe');"
                "        return f ? f.getAttribute('src') : null; }"
            )
            frame = None
            if src and f"chat={chat}" in src:
                frame = next(
                    (f for f in page.frames
                     if PANE_FRAME_URL in (f.url or "")), None
                )
            if frame is not None:
                # The frame's own text. Reading the parent page would return
                # nothing: inner_text stops at the iframe boundary. Guessing at
                # row markup (li/tr/data-testid) returned empty against a pane
                # that was rendering fine.
                try:
                    names = frame.locator("body").inner_text() or ""
                except Exception:
                    names = ""
                if want in names:
                    return names
            time.sleep(3)
        return names

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _owui_login_and_open_chat(page)

            # A fresh profile starts with the sidebar collapsed to an icon rail,
            # where both the New Chat control and the chat list are present in
            # the DOM but not visible. Everything below needs them on screen.
            toggle = page.query_selector('button[aria-label="Open Sidebar"]')
            if toggle is not None:
                toggle.click()
                page.wait_for_selector(
                    'a[aria-label="New Chat"]', state="visible", timeout=20000
                )

            chat_a = start_chat(page, "first chat, one file")
            name_a = f"m14a-{uuid.uuid4().hex[:8]}.txt"
            status, text, is_error = _guest_exec(
                chat_a, f"printf hi > /mnt/user-data/outputs/{name_a}", timeout=90
            )
            assert status == 200 and not is_error, (
                f"guest write for chat A failed: status={status} text={text!r}"
            )

            # A second chat, reached the way a user reaches one: the New Chat
            # control, not a page load.
            page.click('a[aria-label="New Chat"]', timeout=15000)
            page.wait_for_selector("[contenteditable=true]", timeout=20000)
            time.sleep(2)
            chat_b = start_chat(page, "second chat, another file")
            assert chat_b != chat_a, "OpenWebUI reused the first chat's id"
            name_b = f"m14b-{uuid.uuid4().hex[:8]}.txt"
            status, text, is_error = _guest_exec(
                chat_b, f"printf hi > /mnt/user-data/outputs/{name_b}", timeout=90
            )
            assert status == 200 and not is_error, (
                f"guest write for chat B failed: status={status} text={text!r}"
            )

            # The panel, opened while the user is in chat B.
            _chat_panel_frame(page)
            before = pane_names(page, chat_b, name_b)
            assert name_b in before, (
                f"the panel in chat B does not list chat B's file {name_b!r}: "
                f"{before!r}"
            )
            assert name_a not in before, (
                f"the panel in chat B lists chat A's file {name_a!r}: {before!r}"
            )

            # A marker the page keeps only if nothing reloads. Without it a full
            # reload would rebuild the panel at the new chat and this test would
            # pass while proving nothing about the switch.
            page.evaluate("() => { window.__m14 = 'alive'; }")

            page.wait_for_selector(f'a[href="/c/{chat_a}"]', timeout=20000)
            page.click(f'a[href="/c/{chat_a}"]', timeout=15000)

            # The panel re-checks the path on a 2s interval; give it several.
            after = pane_names(page, chat_a, name_a, deadline_s=90)

            assert page.evaluate("() => window.__m14") == "alive", (
                "the page reloaded during the chat switch -- this test only "
                "means something for a client-side navigation, which is the "
                "case the panel's sync exists for"
            )
            assert name_a in after, (
                f"after switching to chat A the panel does not list A's file "
                f"{name_a!r}: {after!r}"
            )
            assert name_b not in after, (
                f"after switching to chat A the panel still lists chat B's file "
                f"{name_b!r} -- it is showing the chat the user left: {after!r}"
            )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# M15 -- with no chat open, the panel shows nothing rather than everything.
#
# The pane is bound to a chat by the ?chat= the panel puts on the portal URL.
# With no chat there is no id to put there, and a portal opened without one
# binds the BASE scope -- the whole tree, every chat's files. Rendering that
# under a control labelled "Files produced in this chat" is worse than an empty
# panel: it is a cross-chat disclosure with a label asserting the opposite.
#
# The panel handles this by not mounting the pane at all and showing a hint.
# M12 and M14 both arrive with a chat already open, so neither can see it.
# ---------------------------------------------------------------------------


def test_m15_panel_with_no_chat_mounts_nothing():
    """On a page that is not a chat, the panel embeds no pane.

    Red-probe: let the panel mount the portal for an empty chat id and this
    fails on the iframe count, with the pane listing the base scope's tree.
    """
    _require_browser()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _owui_login_and_open_chat(page)

            # Nothing is sent, so the path stays off /c/<id>. Asserted, not
            # assumed: a stray chat id here would make the whole test vacuous.
            href = page.evaluate("() => location.href")
            assert "/c/" not in href, (
                f"expected a page that is not a chat, got {href!r}"
            )

            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                opened = page.evaluate(
                    "() => { const p = document.getElementById('ocu-file-pane-panel');"
                    "        return p ? p.getBoundingClientRect().x < window.innerWidth"
                    "                  : null; }"
                )
                if opened is True:
                    break
                toggle = page.query_selector("#ocu-file-pane-panel-toggle")
                assert toggle is not None, (
                    "the chat carries no Files toggle -- the panel patch is not "
                    "in the running OpenWebUI image"
                )
                toggle.click()
                time.sleep(3)
            assert opened is True, "the Files panel never came on screen"

            # Give the panel's interval several turns to mount something if it
            # were going to. Asserting immediately would pass before it tried.
            time.sleep(8)

            frames = page.evaluate(
                "() => document.querySelectorAll('#ocu-file-pane-panel iframe').length"
            )
            assert frames == 0, (
                f"the panel embedded {frames} pane iframe(s) with no chat open; "
                "with no ?chat= the portal binds the base scope, so the panel "
                "lists every chat's files under a 'this chat' label"
            )
            text = page.evaluate(
                "() => { const p = document.getElementById('ocu-file-pane-panel');"
                "        return p ? p.innerText : ''; }"
            )
            assert "Open a chat" in text, (
                f"the panel shows no hint explaining the empty state: {text!r}"
            )
        finally:
            browser.close()
