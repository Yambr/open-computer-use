#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""Put the File Pane in the chat, on the right.

The chat and the pane are separate origins. The pane's session cookie is minted
on ITS origin by the embed-token exchange, and the only page that performs that
exchange is the portal. A user who only ever opens the chat therefore has no
pane session -- which is why a download link the model emitted answered 401, and
why no preview could appear: there was nothing in the chat holding a session.

So the panel embeds the PORTAL, not the pane directly, and the portal embeds the
pane as it already does. Nesting one frame buys three things: the token mint and
postMessage handshake stay in the one component that owns them, the pane's
`frame-ancestors` keeps naming exactly one parent, and the chat needs no
credential of its own. The cookie lands on the pane's origin because the pane
really is running there, so the download link resolves for the same reason it
resolves after visiting the portal by hand.

This edits build/index.html rather than the compiled Svelte chunks. The chunk
hashes change on every upstream build and the surgery in the other patches has
to be re-anchored when they do; a script appended to the shell's HTML depends on
nothing but the DOM, so it survives an Open WebUI bump.

Injected into <head>, and the panel is attached to documentElement rather than
to body. SvelteKit hydrates by reconciling body against what its own render
produced, which removes every element it did not create -- measured: an earlier
revision injected before </body> and the browser's DOM came back with the style
and script gone and body holding only the app's own two children. head is not
reconciled, and documentElement is not a body child, so both survive. The
interval is belt-and-braces for a client-side route change that remounts.

The panel carries the chat id to the portal as ?chat=<id>, which is how the
portal resolves that chat's storage scope. Without it the portal binds the base
scope, and the panel lists every chat's files under a button that says "Files
produced in this chat" -- measured: 923 objects from every chat and every past
test run.

Re-running replaces a previous injection rather than skipping on its own marker.
A patch that only skips can never ship a correction: the stale block survives
every rebuild and the new one is never written.
"""

import os
import sys

MARKER = "ocu-file-pane-panel"
PORTAL_URL = os.environ.get("OCU_FILE_PANE_PORTAL_URL", "http://localhost:3003")
PANEL_WIDTH = os.environ.get("OCU_FILE_PANE_WIDTH", "420")

CANDIDATES = (
    "/app/build/index.html",
    "/app/backend/open_webui/frontend/index.html",
)

SNIPPET = """
<style id="__MARKER__-style">
  #__MARKER__ {
    position: fixed; top: 0; right: 0; height: 100vh; width: __WIDTH__px;
    z-index: 60; background: var(--color-gray-900, #101010);
    border-left: 1px solid rgba(255,255,255,.08);
    transform: translateX(100%); transition: transform .18s ease;
    display: flex; flex-direction: column;
  }
  #__MARKER__.open { transform: translateX(0); }
  #__MARKER__ iframe { flex: 1 1 auto; width: 100%; border: 0; }
  #__MARKER__-head {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 12px; font: 500 13px/1.4 system-ui, sans-serif;
    color: rgba(255,255,255,.72); border-bottom: 1px solid rgba(255,255,255,.08);
  }
  #__MARKER__-head button {
    background: none; border: 0; cursor: pointer; font-size: 16px; line-height: 1;
    color: rgba(255,255,255,.55); padding: 2px 4px;
  }
  #__MARKER__-toggle {
    position: fixed; top: 12px; right: 12px; z-index: 61;
    display: flex; align-items: center; gap: 6px;
    padding: 6px 12px; border-radius: 8px; cursor: pointer;
    border: 1px solid rgba(255,255,255,.14); background: rgba(28,28,30,.92);
    color: rgba(255,255,255,.86); font: 500 13px/1 system-ui, sans-serif;
  }
  #__MARKER__-toggle:hover { background: rgba(48,48,52,.95); }
  html.__MARKER__-open #__MARKER__-toggle { right: calc(__WIDTH__px + 12px); }
  html.__MARKER__-open body { padding-right: __WIDTH__px; }
  @media (max-width: 900px) {
    #__MARKER__ { width: 100vw; }
    html.__MARKER__-open body { padding-right: 0; }
    html.__MARKER__-open #__MARKER__-toggle { right: 12px; }
  }
</style>
<script id="__MARKER__-script">
(function () {
  var ID = "__MARKER__", SRC = "__PORTAL__", KEY = ID + ":open";

  // Which chat the user is looking at. Open WebUI puts it in the path as
  // /c/<id>. The portal turns ?chat=<id> into that chat's storage scope by
  // asking control, and with no ?chat= it binds the BASE scope instead --
  // which is every chat's files at once. Measured before this was passed:
  // 923 objects from every chat and every test run, under a button labelled
  // "Files produced in this chat".
  function chatId() {
    var m = /^\\/c\\/([^\\/?#]+)/.exec(location.pathname || "");
    return m ? m[1] : "";
  }

  function paneSrc(id) {
    return SRC + (SRC.indexOf("?") === -1 ? "?" : "&") +
           "chat=" + encodeURIComponent(id);
  }

  function build() {
    if (document.getElementById(ID)) return;

    var btn = document.createElement("button");
    btn.id = ID + "-toggle";
    btn.type = "button";
    btn.title = "Files produced in this chat";
    btn.textContent = "Files";

    var panel = document.createElement("aside");
    panel.id = ID;
    panel.setAttribute("aria-label", "Files");

    var head = document.createElement("div");
    head.id = ID + "-head";
    var title = document.createElement("span");
    title.textContent = "Files";
    var close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "Close files panel");
    close.textContent = "\\u00d7";
    head.appendChild(title);
    head.appendChild(close);

    // The iframe is created only when the panel is first opened. Mounting it at
    // page load would start a pane session for every chat view, including the
    // ones where the user never asks for a file.
    var frame = null, shownFor = null;

    // Shown instead of the pane when there is no chat yet. Mounting the pane
    // here would bind the base scope and list every chat's files under a
    // "this chat" label, which is worse than an empty panel.
    var hint = document.createElement("p");
    hint.id = ID + "-hint";
    hint.textContent = "Open a chat to see its files.";
    hint.style.cssText =
      "margin:16px 12px;font:13px/1.5 system-ui,sans-serif;color:rgba(255,255,255,.55)";

    panel.appendChild(head);

    function mount(id) {
      if (frame) { panel.removeChild(frame); frame = null; }
      if (hint.parentNode) panel.removeChild(hint);
      shownFor = id;
      if (!id) { panel.appendChild(hint); return; }
      frame = document.createElement("iframe");
      frame.src = paneSrc(id);
      frame.setAttribute("title", "Files");
      frame.setAttribute("allow", "clipboard-write");
      panel.appendChild(frame);
    }

    function open(on) {
      // Mount lazily: at page load this would start a pane session for every
      // chat view, including the ones where no file is ever asked for.
      if (on && shownFor === null) mount(chatId());
      panel.classList.toggle("open", on);
      document.documentElement.classList.toggle(ID + "-open", on);
      try { localStorage.setItem(KEY, on ? "1" : "0"); } catch (e) {}
    }

    // Switching chats is a client-side navigation, so nothing reloads. Without
    // this the panel keeps showing the previous chat's files under the new
    // chat's title.
    panel.__ocuSyncChat = function () {
      var id = chatId();
      if (shownFor !== null && id !== shownFor) mount(id);
    };

    btn.addEventListener("click", function () {
      open(!panel.classList.contains("open"));
    });
    close.addEventListener("click", function () { open(false); });

    // documentElement, not body: hydration reconciles body and drops anything
    // it did not render.
    document.documentElement.appendChild(panel);
    document.documentElement.appendChild(btn);

    var remembered = "0";
    try { remembered = localStorage.getItem(KEY) || "0"; } catch (e) {}
    if (remembered === "1") open(true);
  }

  // In <head> the document is still parsing, so wait for the app shell before
  // the first build; the interval below covers every later remount.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
  // The app re-renders its own root on navigation; the panel is a sibling of it,
  // but a full client-side remount can drop appended nodes, so re-assert.
  setInterval(function () {
    var panel = document.getElementById(ID);
    if (!panel) { build(); return; }
    if (panel.__ocuSyncChat) panel.__ocuSyncChat();
  }, 2000);
})();
</script>
"""


def without_previous(html: str) -> str:
    """Drop an injection from an earlier run so this one replaces it.

    An image is rebuilt over a filesystem that may already carry the previous
    snippet, and a patch that only ever skips when it sees its own marker can
    never ship a correction -- the stale block stays and the new one is never
    written. Both elements are removed as a pair; leaving the style behind
    would keep a panel-shaped hole reserved for an element nothing creates.
    """
    for open_tag, close_tag in (
        (f'<style id="{MARKER}-style">', "</style>"),
        (f'<script id="{MARKER}-script">', "</script>"),
    ):
        start = html.find(open_tag)
        if start == -1:
            continue
        end = html.find(close_tag, start)
        if end == -1:
            raise SystemExit(
                f"found {open_tag} with no {close_tag}; refusing to edit HTML "
                "whose shape is not the one this patch wrote"
            )
        html = html[:start] + html[end + len(close_tag):]
    return html


def patched(html: str) -> str:
    html = without_previous(html)
    body = SNIPPET.replace("__MARKER__", MARKER)
    body = body.replace("__PORTAL__", PORTAL_URL).replace("__WIDTH__", PANEL_WIDTH)
    lower = html.lower()
    idx = lower.find("</head>")
    if idx == -1:
        # No </head> is a different problem from an already-patched file, and
        # silently appending would produce HTML the browser recovers from in a
        # way that varies by engine. Refuse instead.
        raise SystemExit("index.html has no </head>; refusing to guess where to inject")
    return html[:idx] + body + html[idx:]


def main() -> int:
    target = next((p for p in CANDIDATES if os.path.isfile(p)), None)
    if target is None:
        print(f"[patch] no index.html at any of {CANDIDATES}; nothing patched",
              file=sys.stderr)
        return 1

    with open(target, encoding="utf-8") as fh:
        html = fh.read()

    replacing = MARKER in html
    out = patched(html)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(out)

    # Read back rather than trusting the write: the claim is that the shipped
    # file carries the panel, not that a write returned without raising.
    with open(target, encoding="utf-8") as fh:
        back = fh.read()
    if MARKER not in back or PORTAL_URL not in back:
        print(f"[patch] wrote {target} but the marker or portal URL is absent on "
              f"re-read; the panel would not appear", file=sys.stderr)
        return 1

    print(f"[patch] file pane panel {'replaced in' if replacing else 'injected into'} {target} "
          f"(portal {PORTAL_URL}, width {PANEL_WIDTH}px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
