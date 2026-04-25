#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Patch for Open WebUI 0.9.2: auto-open Artifacts panel

Problem: If an HTML code block is inside a collapsed <details>, CodeBlock is not mounted ->
onUpdate does not fire -> Artifacts panel does not open. Artifacts.svelte subscribe
does not help either because the component is not mounted while showControls=false.

Solution: Patch getContents() in Chat.svelte -- after artifactContents.set(contents),
if contents is non-empty, use setTimeout to set showArtifacts.set(true) and showControls.set(true).
setTimeout is needed because during chat initialization (loadChat/navigateHandler)
showControls is reset to false AFTER the reactive getContents() call.
A 300ms delay ensures that auto-show fires after all initialization resets.

Both components (Chat.svelte and Artifacts.svelte) are compiled into one chunk.

=== Compiled-code anchor ===

Subscribe in Artifacts.svelte:
  STORE.subscribe(b=>{const S=b??[];
    S.length===0?(S1.set(!1),S2.set(!1),h(f,0)):S.length>s(u).length&&h(f,S.length-1),h(u,S)
  })

Patch subscribe -- add auto-show to else branch:
  Before: S.length===0?(S1.set(!1),S2.set(!1),h(f,0)):S.length>s(u).length&&h(f,S.length-1),h(u,S)
  After:  S.length===0?(S1.set(!1),S2.set(!1),h(f,0)):/* FIX_ARTIFACTS_AUTO_SHOW */(S.length>s(u).length&&h(f,S.length-1),S2.set(!0),S1.set(!0)),h(u,S)

getContents in Chat.svelte:
  Before: STORE.set(q)},
  After:  STORE.set(q),/* FIX_ARTIFACTS_AUTO_SHOW */q.length>0&&setTimeout(()=>(S2.set(!0),S1.set(!0)),300)},

Fail-loud contract: if the anchor regex does not match any chunk, the script
exits with sys.exit(1) and prints "ERROR: ..." on stderr. This intentionally
fails the Docker build rather than producing a silently-broken image.
"""

import os
import sys
import glob
import re

BUILD_CHUNKS_DIR = "/app/build/_app/immutable/chunks"

# Idempotency marker -- injected as a JS comment at the subscribe patch site
# AND the getContents patch site. Presence of this marker indicates the chunk
# has already been patched by this script; a single substring check covers
# both injection sites.
IDEMPOTENCY_MARKER = "/* FIX_ARTIFACTS_AUTO_SHOW */"

# --- Pattern 1: Artifacts.svelte subscribe (v0.8.11-0.9.1) ---
# Compiled: VAR.length===0?(STORE1.set(!1),STORE2.set(!1),h(SIG,0)):VAR.length>s(SIG2).length&&h(SIG,VAR.length-1),h(SIG3,VAR)
# The subscribe handler: STORE.subscribe(PARAM=>{const VAR=PARAM??[];VAR.length===0?(...):...})
SUBSCRIBE_PATTERN = re.compile(
    r'(\w+)\.length===0\?\((\w+)\.set\(!1\),(\w+)\.set\(!1\),(\w+)\)'
    r':(\1)\.length>\w+\(\w+\)\.length&&(\w+)'
)
# Context: h(u,S) after the ternary (unconditional update)
SUBSCRIBE_CONTEXT = "h("

# --- Pattern 2: Chat.svelte getContents ---
# After type:"iframe" content, find STORE.set(VAR)},
GETCONTENTS_CONTEXT = 'type:"iframe"'

# --- Legacy already-patched marker (for chunks patched by pre-v0.9.1.0 runs) ---
# Subscribe patched (pre-marker builds): wraps else branch in parens with .set(!0) calls
SUBSCRIBE_PATCHED_MARKER = re.compile(
    r'\.length===0\?\(\w+\.set\(!1\),\w+\.set\(!1\),.+?\):'
    r'\(.+?\.set\(!0\),.+?\.set\(!0\)\),'
)


def cache_bust_chunk(chunk_file):
    """Copy chunk to timestamped name and update references.

    IMPORTANT: We COPY, not rename. The old file must remain because
    browsers with immutable-cached parent modules (entry/, nodes/)
    still reference the old filename. Both URLs must serve the patched content.
    """
    import shutil
    import hashlib

    old_name = os.path.basename(chunk_file)
    with open(chunk_file, 'rb') as _f:
        content_hash = hashlib.md5(_f.read()).hexdigest()[:8]
    new_name = old_name.replace('.js', f'-p{content_hash}.js')
    new_path = os.path.join(os.path.dirname(chunk_file), new_name)

    # Copy patched file to new name (keep old file for cached references)
    shutil.copy2(chunk_file, new_path)

    # Update references in nodes/, entry/, and chunks/ to point to new name
    # New browser sessions will load the timestamped version
    base_dir = os.path.dirname(os.path.dirname(chunk_file))  # _app/immutable
    updated = 0
    for subdir in ['nodes', 'entry', 'chunks']:
        search_dir = os.path.join(base_dir, subdir)
        if not os.path.isdir(search_dir):
            continue
        for fn in os.listdir(search_dir):
            if not fn.endswith('.js'):
                continue
            fpath = os.path.join(search_dir, fn)
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
            if old_name in content:
                content = content.replace(old_name, new_name)
                with open(fpath, 'w', encoding='utf-8') as f:
                    f.write(content)
                updated += 1

    print(f"  Cache bust: {old_name} -> {new_name} ({updated} files updated)")
    print(f"  Old file kept: {old_name} (for cached browser references)")
    return new_path


def find_chunk_file():
    """Find JS chunk containing both Artifacts subscribe and getContents patterns.

    Detection: chunk must contain BOTH:
      - 'showArtifacts' or the subscribe hide pattern (STORE.set(!1),STORE.set(!1))
      - 'type:"iframe"' (getContents context)

    Also recognise already-patched chunks (carrying IDEMPOTENCY_MARKER) so the
    idempotent early-exit in apply_patch() can fire.
    """
    if not os.path.isdir(BUILD_CHUNKS_DIR):
        print(f"ERROR: Directory not found: {BUILD_CHUNKS_DIR}", file=sys.stderr)
        return None

    for filepath in sorted(glob.glob(os.path.join(BUILD_CHUNKS_DIR, "*.js"))):
        if filepath.endswith(".map"):
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # Already-patched chunk (idempotent path)
            if IDEMPOTENCY_MARKER in content and GETCONTENTS_CONTEXT in content:
                return filepath
            has_subscribe = _find_subscribe_pattern(content) is not None
            has_getcontents = GETCONTENTS_CONTEXT in content
            if has_subscribe and has_getcontents:
                return filepath
        except Exception as e:
            print(f"  Warning: Could not read {filepath}: {e}")
            continue

    return None


def _find_subscribe_pattern(content):
    """Find the subscribe hide pattern in Artifacts.svelte.

    Pattern:
      VAR.length===0?(STORE1.set(!1),STORE2.set(!1),h(SIG1,0)):VAR.length>s(SIG2).length&&h(SIG1,VAR.length-1),h(SIG3,VAR)

    Returns match dict or None.
    """
    pattern = re.compile(
        r'(\w+)\.length===0\?'                          # VAR.length===0?
        r'\((\w+)\.set\(!1\),(\w+)\.set\(!1\),'         # (STORE1.set(!1),STORE2.set(!1),
        r'(\w+\([^)]+\))\)'                              # h(f,0))
        r':'                                             # :
        r'\1\.length>'                                   # VAR.length>
        r'(\w+\(\w+\))\.length'                          # s(u).length
        r'&&(\w+\([^)]+\))'                              # &&h(f,VAR.length-1)
        r',(\w+\(\w+,\1\))'                              # ,h(u,VAR)
    )
    for m in pattern.finditer(content):
        # Verify it's inside a .subscribe() callback
        before = content[max(0, m.start() - 300):m.start()]
        if '.subscribe(' in before and ('??[]' in before or '||[]' in before):
            return {
                'var': m.group(1),         # S (the array variable)
                'store1': m.group(2),      # Jr (showControls)
                'store2': m.group(3),      # bn (showArtifacts)
                'hide_tail': m.group(4),   # h(f,0)
                'getter': m.group(5),      # s(u)
                'show_tail': m.group(6),   # h(f,S.length-1)
                'update': m.group(7),      # h(u,S)
                'full_match': m.group(0),
                'start': m.start(),
                'end': m.end(),
            }
    return None


def _find_artifact_store(content, subscribe_pos):
    """Find the .subscribe() store name closest before the pattern."""
    before = content[max(0, subscribe_pos - 300):subscribe_pos]
    # Find ALL subscribe calls, take the LAST (closest to the pattern)
    all_matches = list(re.finditer(r'(\w+)\.subscribe\(\w+=>\{', before))
    return all_matches[-1].group(1) if all_matches else None


def extract_store_names(content):
    """Extract store variable names from the subscribe pattern.

    Returns dict with artifact_store, show_controls, show_artifacts, var, or None.
    """
    info = _find_subscribe_pattern(content)
    if not info:
        return None

    art_store = _find_artifact_store(content, info['start'])
    return {
        'artifact_store': art_store,
        'show_controls': info['store1'],
        'show_artifacts': info['store2'],
        'var': info['var'],
    }


def apply_patch():
    """Apply both patches: subscribe + getContents auto-show"""
    chunk_file = find_chunk_file()
    if not chunk_file:
        print("ERROR: Could not find JS chunk with Artifacts patterns", file=sys.stderr)
        print(f"  Searched in: {BUILD_CHUNKS_DIR}/*.js", file=sys.stderr)
        return False

    print(f"  Found chunk: {os.path.basename(chunk_file)}")

    with open(chunk_file, "r", encoding="utf-8") as f:
        content = f.read()

    # --- Idempotency short-circuit ---
    # If the marker is already present anywhere in the chunk, the patch has
    # been applied by a previous run (or by a previous image build layer).
    # Declare success without mutating the file.
    if IDEMPOTENCY_MARKER in content:
        print(f"ALREADY PATCHED: {os.path.basename(chunk_file)} contains {IDEMPOTENCY_MARKER}")
        return True

    # Legacy marker fallback: pre-v0.9.1.0 runs injected wrapped-else-branch
    # shape without a comment marker. Recognise those as already-patched too
    # so rebuilds of 0.8.12 images continue to succeed.
    legacy_subscribe = bool(SUBSCRIBE_PATCHED_MARKER.search(content))

    # Extract store variable names (required for both patch sites)
    stores = extract_store_names(content)
    if not stores and not legacy_subscribe:
        print("ERROR: Could not extract store variable names", file=sys.stderr)
        return False

    if stores:
        print(f"  Stores: artifact={stores['artifact_store']}, "
              f"controls={stores['show_controls']}, "
              f"artifacts={stores['show_artifacts']}")

    patched = False

    # --- Patch 1: Subscribe in Artifacts.svelte ---
    if legacy_subscribe:
        print("  Patch 1 (subscribe): already applied (legacy marker)")
        subscribe_already = True
    else:
        subscribe_already = False
        info = _find_subscribe_pattern(content)
        if info:
            store1 = info['store1']  # showControls
            store2 = info['store2']  # showArtifacts
            old = info['full_match']

            var_name = info['var']
            hide_tail = info['hide_tail']
            getter = info['getter']
            show_tail = info['show_tail']
            update = info['update']

            new = (
                f'{var_name}.length===0?'
                f'({store1}.set(!1),{store2}.set(!1),{hide_tail})'
                f':{IDEMPOTENCY_MARKER}({var_name}.length>{getter}.length&&{show_tail},'
                f'{store2}.set(!0),{store1}.set(!0))'
                f',{update}'
            )
            print(f"  Patch 1 (subscribe):")
            print(f"    Old: {old}")
            print(f"    New: {new}")
            content = content[:info['start']] + new + content[info['end']:]
            patched = True
        else:
            print("  WARNING: Could not find subscribe pattern for patch 1")

    # --- Patch 2: getContents in Chat.svelte ---
    # Find: ARTIFACT_STORE.set(VAR)}, near type:"iframe"
    # Handles 3 cases:
    #   a) Original:   da.set(q)},
    #   b) Old patch:  da.set(q),q.length>0&&(bn.set(!0),Jr.set(!0))},
    #   c) New patch:  da.set(q),/* MARKER */q.length>0&&setTimeout(...)},
    art_store = stores['artifact_store'] if stores else None
    show_art = stores['show_artifacts'] if stores else None
    show_ctrl = stores['show_controls'] if stores else None

    # If subscribe was already patched (legacy marker) but store extraction returned
    # None (legacy-wrapped shape doesn't match _find_subscribe_pattern), attempt a
    # fallback to derive art_store from the getContents context.  Without this,
    # Patch 2 would be silently skipped while the script still exits success.
    if subscribe_already and art_store is None:
        # Fallback: look for STORE.set(VAR)}, immediately after type:"iframe"
        fallback_pat = re.compile(
            r'type:"iframe"[^}]{0,400}?(\w+)\.set\(\w+\)\},'
        )
        fb_match = fallback_pat.search(content)
        if fb_match:
            art_store = fb_match.group(1)
            print(f"  Fallback store extraction succeeded: art_store={art_store}")
        else:
            print(
                "ERROR: legacy chunk patched but artifact store name could not be "
                "derived for Patch 2 verification",
                file=sys.stderr,
            )
            return False

    if not art_store:
        print("  WARNING: Could not determine artifact store name, skipping patch 2")
    else:
        getcontents_already = False
        replaced_gc = False

        def _build_new_patch(var_name):
            return (
                f'{art_store}.set({var_name}),'
                f'{IDEMPOTENCY_MARKER}'
                f'{var_name}.length>0&&'
                f'setTimeout(()=>({show_art}.set(!0),{show_ctrl}.set(!0)),300)'
                f'}},'
            )

        # Case c: Check if already patched with setTimeout
        setTimeout_pattern = re.compile(
            re.escape(art_store) + r'\.set\((\w+)\),(?:/\*[^*]*\*/)?\1\.length>0&&setTimeout'
        )
        for match in setTimeout_pattern.finditer(content):
            before = content[max(0, match.start() - 500):match.start()]
            if GETCONTENTS_CONTEXT in before:
                getcontents_already = True
                print("  Patch 2 (getContents): already applied (setTimeout)")
                break

        if not getcontents_already:
            # Case b: Old patch without setTimeout -- upgrade it
            old_patch_pattern = re.compile(
                re.escape(art_store) + r'\.set\((\w+)\),'
                r'\1\.length>0&&'
                r'\(\w+\.set\(!0\),\w+\.set\(!0\)\)'
                r'\},'
            )
            for match in old_patch_pattern.finditer(content):
                before = content[max(0, match.start() - 500):match.start()]
                if GETCONTENTS_CONTEXT not in before:
                    continue
                var_name = match.group(1)
                old = match.group(0)
                new = _build_new_patch(var_name)
                print(f"  Patch 2 (getContents upgrade to setTimeout):")
                print(f"    Old: {old}")
                print(f"    New: {new}")
                content = content[:match.start()] + new + content[match.end():]
                replaced_gc = True
                patched = True
                break

        if not getcontents_already and not replaced_gc:
            # Case a: Original unpatched -- STORE.set(VAR)},
            getcontents_pattern = re.compile(
                re.escape(art_store) + r'\.set\((\w+)\)\},'
            )
            for match in getcontents_pattern.finditer(content):
                var_name = match.group(1)
                before = content[max(0, match.start() - 500):match.start()]
                if GETCONTENTS_CONTEXT not in before:
                    continue
                old = match.group(0)
                new = _build_new_patch(var_name)
                print(f"  Patch 2 (getContents):")
                print(f"    Old: {old}")
                print(f"    New: {new}")
                content = content[:match.start()] + new + content[match.end():]
                replaced_gc = True
                patched = True
                break

        if not getcontents_already and not replaced_gc:
            print("  WARNING: Could not find getContents pattern for patch 2")

    if not patched and not subscribe_already and not getcontents_already:
        print("ERROR: No patches applied", file=sys.stderr)
        return False

    # Write patched content
    with open(chunk_file, "w", encoding="utf-8") as f:
        f.write(content)

    # Cache bust: copy chunk to timestamped name and update references
    # Old file kept so browsers with cached parent modules still work
    cache_bust_chunk(chunk_file)

    print(f"PATCHED! File: {os.path.basename(chunk_file)}")
    return True


if __name__ == "__main__":
    print("Applying Artifacts auto-show patch to Open WebUI frontend...")
    success = apply_patch()
    if not success:
        print(
            "ERROR: fix_artifacts_auto_show anchor not found in "
            f"{BUILD_CHUNKS_DIR}/*.js -- upstream may have refactored. "
            "Check v0.9.2 source + update regex. "
            "Refusing to produce a silently-broken image.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("PATCHED: fix_artifacts_auto_show applied successfully.")
    sys.exit(0)
