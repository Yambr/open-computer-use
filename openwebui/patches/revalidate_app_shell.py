#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""Make the SPA shell revalidate instead of being heuristically cached.

The shell is served by SPAStaticFiles with no Cache-Control header at all.
A response with no freshness information is not "uncached": browsers apply a
heuristic lifetime derived from Last-Modified, so a returning visitor keeps
serving the old index.html from disk and never asks the server whether it
changed. Measured on the stand: a fresh fetch of / returned 15413 bytes and a
cached fetch of the same URL returned 11028 bytes -- two different app shells,
same URL, same session, and the browser had no reason to prefer the new one.

That is not specific to what we inject. Every change to the shell -- an Open
WebUI upgrade, a new asset manifest, this project's file-pane panel -- reaches
a returning user only after the heuristic expires or they hard-reload. The
symptom is indistinguishable from "the feature was never deployed", which is
how it presented: the panel was absent on http://host:3001/ and present on
http://host:3001/?t=cachebuster, because a query string is a different cache
key.

no-cache does not mean "do not store": it means the browser must revalidate
before reuse, so an unchanged shell still answers 304 and costs one conditional
request. Only responses whose content type is HTML are stamped -- the hashed
asset bundles under /_app/immutable keep their long-lived caching, which is the
whole point of hashing them.

The rename-and-wrap keeps the upstream body untouched: this patch replaces two
lines (the class header and the method signature) and never has to match the
method's internals, which differ in quoting and formatting between releases.

Idempotent: re-running finds its own marker and exits 0 without editing.
"""

import os
import sys

MARKER = "_ocu_shell_revalidate"

CANDIDATES = (
    "/app/backend/open_webui/main.py",
)

ANCHOR = (
    "class SPAStaticFiles(StaticFiles):\n"
    "    async def get_response(self, path: str, scope):\n"
)

REPLACEMENT = (
    "class SPAStaticFiles(StaticFiles):\n"
    "    async def get_response(self, path: str, scope):\n"
    "        response = await self." + MARKER + "(path, scope)\n"
    "        # HTML only: the hashed bundles must keep their immutable caching.\n"
    '        if response.headers.get("content-type", "").startswith("text/html"):\n'
    '            response.headers["cache-control"] = "no-cache, must-revalidate"\n'
    "        return response\n"
    "\n"
    "    async def " + MARKER + "(self, path: str, scope):\n"
)


def patched(src: str) -> str:
    if ANCHOR not in src:
        raise SystemExit(
            "SPAStaticFiles.get_response not found in the expected shape; "
            "refusing to guess where to wrap the shell response"
        )
    return src.replace(ANCHOR, REPLACEMENT, 1)


def main() -> int:
    target = next((p for p in CANDIDATES if os.path.isfile(p)), None)
    if target is None:
        print(f"[patch] no main.py at any of {CANDIDATES}; nothing patched",
              file=sys.stderr)
        return 1

    with open(target, encoding="utf-8") as fh:
        src = fh.read()

    if MARKER in src:
        print(f"[patch] {target} already carries {MARKER}; nothing to do")
        return 0

    with open(target, "w", encoding="utf-8") as fh:
        fh.write(patched(src))

    # Read back rather than trusting the write, and compile: a syntax error here
    # would not surface until the server failed to boot.
    with open(target, encoding="utf-8") as fh:
        back = fh.read()
    if MARKER not in back:
        print(f"[patch] wrote {target} but the marker is absent on re-read",
              file=sys.stderr)
        return 1
    try:
        compile(back, target, "exec")
    except SyntaxError as exc:
        print(f"[patch] {target} does not parse after the edit: {exc}",
              file=sys.stderr)
        return 1

    print(f"[patch] app shell now revalidates ({target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
