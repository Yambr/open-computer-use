#!/usr/bin/env python3
"""
Патч для Open WebUI v0.8.11–0.8.12: автоматическое обнаружение file URL в сообщениях

Problem: To show file preview in the Artifacts panel, we need to detect
Computer Use Server file links in assistant messages and auto-open the
preview SPA in the Artifacts panel.

Solution: Patch getCodeBlockContents() — the function that parses message content.
Push an iframe into htmlGroups array (e): if no code blocks found but content has
a link to /files/{chat_id}/... or /preview/{chat_id} — push iframe artifact.
The existing chain (getContents → artifactContents → auto-show) handles the rest.

The server URL is configurable via COMPUTER_USE_SERVER_URL env var
(defaults to computer-use-server:8081).

=== v0.8.11–0.8.12 compiled code ===

  Wn=r=>{r=Ce(r);const t=r.match(/```[\\s\\S]*?```/g);let n=[],e=[];
  ... // code block parsing fills e[] with {html, css, js} groups
  const i=e.map(o=>o.html).join(""),a=e.map(o=>o.css).join(""),l=e.map(o=>o.js).join("");
  return{codeBlocks:n,html:i.trim(),css:a.trim(),js:l.trim(),htmlGroups:e.filter(...).map(...)}

Injection point: BEFORE `const i=e.map(o=>o.html).join("")`
We push our iframe artifact into `e` (mutable let array), then `const i` naturally
picks it up. No const reassignment needed.

  // INJECTED:
  if(!e.some(o=>o.html)&&r&&/localhost:8081\\/(files|preview)\\//.test(r)){
    var _pm=r.match(/regex/); if(_pm) e.push({html:'<iframe...>',css:'...',js:''});
  }
  const i=e.map(o=>o.html).join(""); // now includes our iframe
"""

import os
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

# Preview server URL — configurable via COMPUTER_USE_SERVER_URL env var
# Defaults to computer-use-server:8081 (docker-compose service name)
PREVIEW_HOST = os.getenv("COMPUTER_USE_SERVER_URL", "localhost:8081")
# Strip protocol for regex, keep for iframe URL
PREVIEW_HOST_BARE = re.sub(r'^https?://', '', PREVIEW_HOST).rstrip('/')
PREVIEW_BASE_URL = PREVIEW_HOST if '://' in PREVIEW_HOST else f'http://{PREVIEW_HOST}'

# Already-patched marker
PATCHED_MARKER = 'preview-url-detect'


def find_chunk_file():
    """Find JS chunk containing getCodeBlockContents (by const pattern + backtick regex)"""
    if not os.path.isdir(BUILD_CHUNKS_DIR):
        print(f"ERROR: Directory not found: {BUILD_CHUNKS_DIR}")
        return None

    for filepath in sorted(glob.glob(os.path.join(BUILD_CHUNKS_DIR, "*.js"))):
        if filepath.endswith(".map"):
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # Check for already-patched file first
            if PATCHED_MARKER in content and '_pm' in content:
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
    Uses PREVIEW_HOST_BARE for regex matching and PREVIEW_BASE_URL for iframe src.
    """
    # Escape dots for regex
    host_regex = PREVIEW_HOST_BARE.replace('.', '\\\\.')
    iframe_html = (
        f"'<iframe src=\"{PREVIEW_BASE_URL}/preview/'"
        "+_pm[1]+'\" "
        "style=\"width:100%;height:100%;border:none\" "
        "allow=\"clipboard-write; keyboard-map\"></iframe>\\n'"
    )
    iframe_css = (
        "'*{margin:0;padding:0;overflow:hidden}"
        "html,body{height:100%}\\n'"
    )
    return (
        f'if(!{groups_var}.some(o=>o.html)&&{param_name}&&'
        f'/{host_regex}\\/(files|preview)\\//.test({param_name}))'
        f'{{var _pm={param_name}.match('
        f'/https?:\\/\\/{host_regex}\\/(?:files|preview)\\/([^\\/\\s\\"\\)]+)/'
        f');if(_pm){{{groups_var}.push({{html:{iframe_html},css:{iframe_css},js:""}})}}}}'
    )


def apply_patch():
    """Apply the preview URL detection patch to getCodeBlockContents."""
    chunk_file = find_chunk_file()
    if not chunk_file:
        print("ERROR: Could not find JS chunk with getCodeBlockContents")
        print(f"  Searched in: {BUILD_CHUNKS_DIR}/*.js")
        return False

    print(f"  Found chunk: {os.path.basename(chunk_file)}")

    with open(chunk_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if already patched
    if PATCHED_MARKER in content and '_pm' in content:
        print("  Already patched, skipping...")
        return True

    # Find the const declaration: })}const i=e.map(o=>o.html).join("")
    const_match = CONST_DECL_PATTERN.search(content)
    if not const_match:
        print("ERROR: Could not find const html declaration pattern")
        return False

    # Extract variable names
    prefix = const_match.group(1)  # })}
    html_var = const_match.group(2)  # i
    groups_var = const_match.group(3)  # e

    print(f"  Variables: html={html_var}, htmlGroups={groups_var}")

    # Extract parameter name
    param_name = extract_param_name(content, const_match)
    if not param_name:
        print("ERROR: Could not determine content parameter name")
        return False

    print(f"  Content param: {param_name}")

    # Build injection code
    injection = build_injection(param_name, groups_var)

    print(f"  Injection ({len(injection)} chars):")
    print(f"    {injection[:120]}...")

    # Injection point: between })} and const i=...
    # Replace: })}const i=...  →  })}INJECTION;const i=...
    old = const_match.group(0)
    new = prefix + injection + "const " + old[len(prefix) + len("const "):]

    content_new = content.replace(old, new, 1)

    if content_new == content:
        print("ERROR: Replacement had no effect")
        return False

    with open(chunk_file, "w", encoding="utf-8") as f:
        f.write(content_new)

    print(f"PATCHED! File: {os.path.basename(chunk_file)}")
    return True


if __name__ == "__main__":
    print("Applying preview URL detection patch to Open WebUI frontend...")
    success = apply_patch()
    if not success:
        print("WARNING: Preview URL detection patch SKIPPED (JS chunks changed in new version)")
        print("  This is expected after a major version upgrade. Patch needs rewriting.")
    exit(0)  # never fail build — frontend patches are non-critical
