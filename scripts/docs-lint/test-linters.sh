#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
#
# Linter self-test: prove each gate catches the violation it's supposed to.
#
# Creates temporary fixtures, runs the matching detection logic against them,
# and asserts each gate correctly flags / accepts the fixture. Cleans up.
#
# Run from repo root: scripts/docs-lint/test-linters.sh

set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

ok()   { echo "  ok:   $1"; pass=$((pass + 1)); }
err()  { echo "  FAIL: $1"; fail=$((fail + 1)); }

# -------- wc-budget --------
echo "Testing wc-budget.sh:"

big_adr="$TMP/big.md"
{
  echo "---"; echo "status: draft"; echo "---"
  for i in $(seq 1 250); do echo "line $i"; done
} > "$big_adr"

lines=$(wc -l < "$big_adr" | tr -d ' ')
if (( lines > 200 )); then
  ok "ADR cap (200) would block file with $lines lines"
else
  err "wc fixture didn't exceed cap"
fi

# -------- ai-slop-detector --------
echo "Testing ai-slop-detector.sh:"

slop_conclusion="$TMP/slop_conclusion.md"
cat > "$slop_conclusion" <<'EOF'
## Conclusion

text
EOF
if grep -qE '^##+ (Conclusion|Summary|In conclusion|TL;DR)$' "$slop_conclusion"; then
  ok "Conclusion-section regex detects short-doc summary"
else
  err "Conclusion regex didn't match fixture"
fi

slop_toc="$TMP/slop_toc.md"
cat > "$slop_toc" <<'EOF'
## Table of Contents

- a
EOF
if grep -qE '^##+ (Table of [Cc]ontents|TOC|Contents)$' "$slop_toc"; then
  ok "TOC regex detects short-doc TOC"
else
  err "TOC regex didn't match fixture"
fi

slop_stub="$TMP/slop_stub.md"
cat > "$slop_stub" <<'EOF'
## Stub

## Next section

content
EOF
result=$(awk '
  /^##+ / {
    cur=$0; line=NR
    while ((getline next_line) > 0) {
      if (next_line ~ /^[ \t]*$/) continue
      if (next_line ~ /^##+ /) { print "HIT:" line; exit }
      break
    }
  }
' "$slop_stub")
if [[ "$result" == HIT:* ]]; then
  ok "stub-heading detection works"
else
  err "stub-heading regex didn't catch fixture"
fi

# bank-as-framing fixture: a framing use must flag, a named example must pass.
slop_bank="$TMP/slop_bank.md"
cat > "$slop_bank" <<'EOF'
The bank already runs an audited store, so the platform targets banks.
EOF
bank_re="bank's|\bthe bank\b|\ba bank\b|targets? banks|bank-(required|grade|specific|facing|side)|bank (infosec|ciso|reviewer|procurement|architect|auditor)"
bank_allow='tier-1 (us or eu )?bank|tier-1 banks|US or EU bank|retail-banking|banking convention|banking-vendor convention'
if grep -nEi "$bank_re" "$slop_bank" | grep -vEi "$bank_allow" | grep -q .; then
  ok "bank-as-framing detection works"
else
  err "bank-framing regex didn't catch fixture"
fi
slop_bank_ok="$TMP/slop_bank_ok.md"
cat > "$slop_bank_ok" <<'EOF'
The capability ceiling targets a tier-1 US or EU bank as the named example.
EOF
if grep -nEi "$bank_re" "$slop_bank_ok" | grep -vEi "$bank_allow" | grep -q .; then
  err "bank-framing regex wrongly flagged the tier-1 named example"
else
  ok "bank named-example (tier-1) correctly accepted"
fi

# SAML-as-surface fixture: asserting SAML must flag, a federation clause must pass.
slop_saml="$TMP/slop_saml.md"
cat > "$slop_saml" <<'EOF'
Human action requires SAML/OIDC on the full shelf.
EOF
saml_allow='SAML-only (customer )?(idp|pam)|federates? in through (dex|keycloak)|never an OCU SAML|through Dex or Keycloak'
if grep -nEi '\bSAML\b' "$slop_saml" | grep -vEi "$saml_allow" | grep -q .; then
  ok "SAML-as-surface detection works"
else
  err "SAML regex didn't catch fixture"
fi
slop_saml_ok="$TMP/slop_saml_ok.md"
cat > "$slop_saml_ok" <<'EOF'
A SAML-only customer IdP federates in through Dex or Keycloak, never an OCU SAML surface.
EOF
if grep -nEi '\bSAML\b' "$slop_saml_ok" | grep -vEi "$saml_allow" | grep -q .; then
  err "SAML regex wrongly flagged the federation clause"
else
  ok "SAML federation clause correctly accepted"
fi

# -------- ascii-diagram-detector --------
echo "Testing ascii-diagram-detector.sh:"

ascii_fixture="$TMP/ascii.md"
cat > "$ascii_fixture" <<'EOF'
Box-drawing:

┌──────┐
│ box  │
└──────┘
EOF

if python3 -c "
import re, sys
pat = re.compile(r'[─-╿▀-▟]')
with open('$ascii_fixture') as f:
    sys.exit(0 if any(pat.search(l) for l in f) else 1)
"; then
  ok "Unicode box-drawing detected in fixture"
else
  err "ascii fixture not detected"
fi

table_fixture="$TMP/table.md"
cat > "$table_fixture" <<'EOF'
| a | b |
|---|---|
| 1 | 2 |
EOF

if python3 -c "
import re, sys
pat = re.compile(r'[─-╿▀-▟]')
with open('$table_fixture') as f:
    sys.exit(1 if any(pat.search(l) for l in f) else 0)
"; then
  ok "Markdown table not flagged as ASCII diagram"
else
  err "Markdown table false-positive"
fi

# -------- front-matter-validator --------
echo "Testing front-matter-validator.sh:"

nofm="$TMP/nofm.md"
echo "Just text. No YAML." > "$nofm"

if python3 -c "
import re, sys, pathlib
text = pathlib.Path('$nofm').read_text()
stripped = re.sub(r'^(?:<!--.*?-->\s*\n)+', '', text, flags=re.DOTALL)
sys.exit(1 if stripped.startswith('---') else 0)
"; then
  ok "missing-front-matter detected"
else
  err "missing-FM fixture wasn't caught"
fi

partial_fm="$TMP/partial.md"
cat > "$partial_fm" <<'EOF'
---
status: draft
owner: "@x"
---
content
EOF

if python3 -c "
import re, sys, pathlib
text = pathlib.Path('$partial_fm').read_text()
stripped = re.sub(r'^(?:<!--.*?-->\s*\n)+', '', text, flags=re.DOTALL)
m = re.match(r'^---\n(.*?)\n---', stripped, flags=re.DOTALL)
body = m.group(1)
fields = {}
for line in body.splitlines():
    if ':' in line and not line.startswith(' '):
        k, _, v = line.partition(':')
        fields[k.strip()] = v.strip().strip('\"').strip(\"'\")
required = ['status', 'last-reviewed', 'owner', 'applies-to']
missing = [k for k in required if k not in fields or not fields[k]]
sys.exit(0 if missing else 1)
"; then
  ok "missing-field detection works"
else
  err "partial FM wasn't caught"
fi

# -------- architecture-tree-whitelist --------
echo "Testing architecture-tree-whitelist.sh:"

# Run against an isolated fixture tree so we don't disturb the real
# docs/architecture/. Invoke the same segment-aware matcher the linter
# uses, so a future regression that swaps it back for plain fnmatch
# (which lets `*` cross `/`) is caught here.
tree_root="$TMP/atree/docs/architecture"
mkdir -p "$tree_root/adr" "$tree_root/diagrams" "$tree_root/components" \
         "$tree_root/compliance/sub"

# Allowed files.
touch "$tree_root/README.md"
touch "$tree_root/adr/0001-foo.md"
touch "$tree_root/diagrams/c4.mmd"
touch "$tree_root/components/01-control-plane.md"
touch "$tree_root/compliance/soc2-mapping.md"

# Disallowed files.
touch "$tree_root/notes.txt"                          # stray scratch note
touch "$tree_root/LAYER-0-VERIFICATION.md"            # AI snapshot
touch "$tree_root/diagrams/screenshot.png"            # binary in diagrams
touch "$tree_root/compliance/sub/x-mapping.md"        # nested-path edge case:
                                                       # plain fnmatch would
                                                       # accept this under
                                                       # compliance/*-mapping.md

allow_list=(
  "README.md"
  "adr/[0-9][0-9][0-9][0-9]-*.md"
  "diagrams/*.mmd"
  "components/[0-9][0-9]-*.md"
  "compliance/*-mapping.md"
)
violations=$(
  cd "$TMP/atree" && python3 - "${allow_list[@]}" <<'PY'
import fnmatch, pathlib, sys
allow = sys.argv[1:]
root = pathlib.Path("docs/architecture")

def match(rel: str, pat: str) -> bool:
    rp = rel.split("/")
    pp = pat.split("/")
    if len(rp) != len(pp):
        return False
    return all(fnmatch.fnmatchcase(r, p) for r, p in zip(rp, pp))

bad = []
for p in root.rglob("*"):
    if not p.is_file():
        continue
    rel = p.relative_to(root).as_posix()
    if not any(match(rel, g) for g in allow):
        bad.append(rel)
print("\n".join(sorted(bad)))
PY
)

want_bad=(
  "LAYER-0-VERIFICATION.md"
  "compliance/sub/x-mapping.md"
  "diagrams/screenshot.png"
  "notes.txt"
)
all_caught=1
for needle in "${want_bad[@]}"; do
  if ! grep -qxF "$needle" <<<"$violations"; then
    all_caught=0
    err "tree-whitelist missed expected violation: $needle"
  fi
done
if (( all_caught )); then
  ok "tree-whitelist catches stray notes, AI snapshots, binaries, nested-path edge case"
fi

# Allowed files must NOT appear in violations.
for needle in \
  "README.md" \
  "adr/0001-foo.md" \
  "diagrams/c4.mmd" \
  "components/01-control-plane.md" \
  "compliance/soc2-mapping.md"
do
  if grep -qxF "$needle" <<<"$violations"; then
    err "tree-whitelist false-positive on legitimate file: $needle"
  fi
done
ok "tree-whitelist accepts files that match allowed patterns"

# -------- identity-email-detector --------
echo "Testing identity-email-detector.sh:"

# Run the detector end-to-end against a throwaway git repo, so the test covers
# the script's real behaviour (tracked-file scan, path excludes, git invocation,
# exit code) rather than re-implementing its grep. The banned address is
# assembled from parts so the literal never appears in this tracked file (which
# would itself trip the detector it tests).
banned="i@yambr$(printf '%s' .com)"
canonical="developer@widemoat.ai"
detector="$ROOT/scripts/docs-lint/identity-email-detector.sh"

# Fixture repo with one tracked file carrying the banned address.
fixture="$TMP/identity-fixture"
git init -q "$fixture"
git -C "$fixture" config user.email test@example.com
git -C "$fixture" config user.name test
printf 'contact %s for help\n' "$banned" > "$fixture/notes.md"
git -C "$fixture" add notes.md
git -C "$fixture" commit -q -m fixture

if ( cd "$fixture" && bash "$detector" ) >/dev/null 2>&1; then
  err "identity-email-detector did not flag the banned personal address"
else
  ok "identity-email-detector flags the banned personal address"
fi

# Replace the tracked content with the canonical address and a product URL;
# neither must trip the detector.
printf 'contact %s — see https://lab.widemoat.ai\n' "$canonical" > "$fixture/notes.md"
git -C "$fixture" commit -q -am clean
if ( cd "$fixture" && bash "$detector" ) >/dev/null 2>&1; then
  ok "identity-email-detector accepts the canonical address and product URLs"
else
  err "identity-email-detector false-positives on the canonical address or a product URL"
fi

# -------- Summary --------
echo
echo "Linter self-test: $pass passed, $fail failed."
if (( fail > 0 )); then
  exit 1
fi
