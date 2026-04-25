#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Patch for Open WebUI 0.9.2 (host-agnostic): automatic detection of file URLs in messages

Problem: To show file preview in the Artifacts panel, we need to detect
Computer Use Server file links in assistant messages and auto-open the
preview SPA in the Artifacts panel.

Solution: Patch getCodeBlockContents() -- the function that parses message content.
Push an iframe into htmlGroups array (e): if no code blocks found but content has
a link to /files/{chat_id}/... or /preview/{chat_id} -- push iframe artifact.
The existing chain (getContents -> artifactContents -> auto-show) handles the rest.

Host-agnostic: the iframe src is reconstructed at runtime from the matched URL's own
origin, so no build-time host configuration is needed.

=== Compiled-code anchor ===

  Wn=r=>{r=Ce(r);const t=r.match(/```[\\s\\S]*?```/g);let n=[],e=[];
  ... // code block parsing fills e[] with {html, css, js} groups
  const i=e.map(o=>o.html).join(""),a=e.map(o=>o.css).join(""),l=e.map(o=>o.js).join("");
  return{codeBlocks:n,html:i.trim(),css:a.trim(),js:l.trim(),htmlGroups:e.filter(...).map(...)}

Injection point: BEFORE `const i=e.map(o=>o.html).join("")`
We push our iframe artifact into `e` (mutable let array), then `const i` naturally
picks it up. No const reassignment needed.

  // INJECTED:
  /* FIX_PREVIEW_URL_DETECTION */
  if(!e.some(o=>o.html)&&r&&/\\/(files|preview)\\//.test(r)){
    var _pm=r.match(/regex/); if(_pm) e.push({html:'<iframe...>',css:'...',js:''});
  }
  const i=e.map(o=>o.html).join(""); // now includes our iframe

Fail-loud contract: if the anchor regex does not match any chunk, the script
exits with sys.exit(1) and prints "ERROR: ..." on stderr. This intentionally
fails the Docker build rather than producing a silently-broken image.
"""

import os
import sys
import glob
import re

BUILD_CHUNKS_DIR = "/app/build/_app/immutable/chunks"

# Search pattern: the const declarations right before return
# We match: })}const i=e.map(o=>o.html).join("")
CONST_DECL_PATTERN = re.compile(
    r'(\}\)\})const (\w+)=(\w+)\.map\(\w+=>\w+\.html\)\.join\(""\)'
)

# Context marker: the backtick regex (confirms we're in getCodeBlockContents)
BACKTICK_REGEX_MARKER = r'[\s\S]*?'  # part of /```[\s\S]*?```/g

# This patch is host-agnostic. The iframe `src` is reconstructed at runtime
# from the matched URL's own origin (_pm[1] in the injected JS), so no
# build-time host configuration is consumed here. COMPUTER_USE_SERVER_URL
# is intentionally not read by this patch.

# Idempotency marker -- injected as a JS comment at the patch site.
# Presence of this marker indicates the chunk has already been patched by this script.
IDEMPOTENCY_MARKER = "/* FIX_PREVIEW_URL_DETECTION */"
# Legacy marker -- continue to recognise chunks patched by v0.8.12 runs.
LEGACY_PATCHED_MARKER = "preview-url-detect"


def find_chunk_file():
    """Find JS chunk containing getCodeBlockContents (by const pattern + backtick regex)"""
    if not os.path.isdir(BUILD_CHUNKS_DIR):
        print(f"ERROR: Directory not found: {BUILD_CHUNKS_DIR}", file=sys.stderr)
        return None

    for filepath in sorted(glob.glob(os.path.join(BUILD_CHUNKS_DIR, "*.js"))):
        if filepath.endswith(".map"):
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # Check for already-patched file first (new or legacy marker)
            if (IDEMPOTENCY_MARKER in content) or (LEGACY_PATCHED_MARKER in content and '_pm' in content):
                if BACKTICK_REGEX_MARKER in content:
                    return filepath
            # Check for unpatched file
            has_const = CONST_DECL_PATTERN.search(content)
            has_backtick = BACKTICK_REGEX_MARKER in content
            if has_const and has_backtick:
                return filepath
        except Exception as e:
            print(f"  Warning: Could not read {filepath}: {e}")
            continue

    return None


def extract_param_name(content, const_match):
    """Extract the function parameter name (the 'content' parameter).

    Looks backwards from the const declaration to find PARAM.match(/```...)
    """
    before = content[max(0, const_match.start() - 2000):const_match.start()]
    param_match = re.search(r'(\w+)\.match\(/```', before)
    if param_match:
        return param_match.group(1)
    return None


def build_injection(param_name, groups_var):
    """Build the URL detection code to inject before const declarations.

    Pushes an iframe artifact into the htmlGroups array (e).
    The array is mutable (let), so push works in strict mode.

    Host-agnostic: matches any HTTP(S) URL whose path contains /files/<id>/
    or /preview/<id>. The actual host is read back from the matched URL
    itself, so the filter's X-Public-Base-URL (localhost, 127.0.0.1,
    computer-use-server, public domain, etc.) all work without the patch
    having to know what it is at build time.
    """
    # Build the JS expression that, at runtime, produces an iframe tag string.
    # Two literal fragments + two interpolations (_pm[1]=origin, _pm[2]=id).
    iframe_html_expr = (
        "'<iframe src=\"'+_pm[1]+'/preview/'+_pm[2]+"
        "'\" style=\"width:100%;height:100%;border:none\" "
        "allow=\"clipboard-write; keyboard-map\"></iframe>\\n'"
    )
    iframe_css = (
        "'*{margin:0;padding:0;overflow:hidden}"
        "html,body{height:100%}\\n'"
    )
    # Host-agnostic detector: /(files|preview)\/ in url path, then capture
    # the origin (_pm[1]) and the id segment (_pm[2]) via a single regex.
    # Guard with `!param.some(o=>o.html)` so genuine fenced <html> blocks
    # still take precedence.
    # NOTE: we match origin http(s)://host[:port] then /files|/preview/ then id.
    return (
        f'{IDEMPOTENCY_MARKER}'
        f'if(!{groups_var}.some(o=>o.html)&&{param_name}&&'
        f'/\\/(files|preview)\\//.test({param_name}))'
        f'{{var _pm={param_name}.match('
        f'/(https?:\\/\\/[^\\/\\s\\"\\)]+)\\/(?:files|preview)\\/([^\\/\\s\\"\\)]+)/'
        f');if(_pm){{{groups_var}.push({{html:{iframe_html_expr},css:{iframe_css},js:""}})}}}}'
        f'/*{LEGACY_PATCHED_MARKER}*/'
    )


def apply_patch():
    """Apply the preview URL detection patch to getCodeBlockContents."""
    chunk_file = find_chunk_file()
    if not chunk_file:
        print("ERROR: Could not find JS chunk with getCodeBlockContents", file=sys.stderr)
        print(f"  Searched in: {BUILD_CHUNKS_DIR}/*.js", file=sys.stderr)
        return False

    print(f"  Found chunk: {os.path.basename(chunk_file)}")

    with open(chunk_file, "r", encoding="utf-8") as f:
        content = f.read()

    # --- Idempotency short-circuit ---
    # Either the new-style marker or the legacy marker indicates a prior run
    # has already patched this chunk. Declare success without mutating.
    if IDEMPOTENCY_MARKER in content:
        print(f"ALREADY PATCHED: {os.path.basename(chunk_file)} contains {IDEMPOTENCY_MARKER}")
        return True
    if LEGACY_PATCHED_MARKER in content and '_pm' in content:
        print(f"ALREADY PATCHED: {os.path.basename(chunk_file)} contains legacy marker '{LEGACY_PATCHED_MARKER}'")
        return True

    # Find the const declaration: })}const i=e.map(o=>o.html).join("")
    const_match = CONST_DECL_PATTERN.search(content)
    if not const_match:
        print("ERROR: Could not find const html declaration pattern", file=sys.stderr)
        return False

    # Extract variable names
    prefix = const_match.group(1)  # })}
    html_var = const_match.group(2)  # i
    groups_var = const_match.group(3)  # e

    print(f"  Variables: html={html_var}, htmlGroups={groups_var}")

    # Extract parameter name
    param_name = extract_param_name(content, const_match)
    if not param_name:
        print("ERROR: Could not determine content parameter name", file=sys.stderr)
        return False

    print(f"  Content param: {param_name}")

    # Build injection code
    injection = build_injection(param_name, groups_var)

    print(f"  Injection ({len(injection)} chars):")
    print(f"    {injection[:140]}...")

    # Injection point: between })} and const i=...
    # Replace: })}const i=...  ->  })}INJECTION;const i=...
    old = const_match.group(0)
    new = prefix + injection + "const " + old[len(prefix) + len("const "):]

    content_new = content.replace(old, new, 1)

    if content_new == content:
        print("ERROR: Replacement had no effect", file=sys.stderr)
        return False

    with open(chunk_file, "w", encoding="utf-8") as f:
        f.write(content_new)

    print(f"PATCHED! File: {os.path.basename(chunk_file)}")
    return True


if __name__ == "__main__":
    print("Applying Preview URL detection patch to Open WebUI frontend...")
    success = apply_patch()
    if not success:
        print(
            "ERROR: fix_preview_url_detection anchor not found in "
            f"{BUILD_CHUNKS_DIR}/*.js -- getCodeBlockContents compiled shape changed. "
            "Check v0.9.2 source + update CONST_DECL_PATTERN. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("PATCHED: fix_preview_url_detection applied successfully.")
    sys.exit(0)
