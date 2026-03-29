#!/usr/bin/env python3
"""
Settings CLI for AI assistant — check tokens, manage skills.

Usage:
    settings-cli.py check-tokens
    settings-cli.py my-skills
    settings-cli.py toggle <skill-name> on|off
    settings-cli.py search <query>
    settings-cli.py download <skill-name>

Environment:
    GIT_AUTHOR_EMAIL — user email (required, set by Docker-AI)
    SETTINGS_API_URL — API base URL (default: https://example.com)
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

BASE_URL = os.environ.get(
    "SETTINGS_API_URL", "https://example.com"
)


def get_email() -> str:
    email = os.environ.get("GIT_AUTHOR_EMAIL")
    if not email:
        print(
            "Error: GIT_AUTHOR_EMAIL environment variable is not set",
            file=sys.stderr,
        )
        sys.exit(1)
    return email


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _request(method: str, path: str, body: dict | None = None):
    """Make HTTP request. Returns parsed JSON or raw bytes."""
    url = f"{BASE_URL}{path}"
    data = None
    req = urllib.request.Request(url, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    resp = urllib.request.urlopen(req, data, timeout=15, context=_ssl_ctx())
    content_type = resp.headers.get("Content-Type", "")
    raw = resp.read()
    if "application/json" in content_type:
        return json.loads(raw.decode())
    return raw


# ── Commands ─────────────────────────────────────────────────────────────


def cmd_check_tokens() -> None:
    email = get_email()
    data = _request("GET", f"/api/user-status/{email}")

    print(f"Token status for {email}:\n")
    for tok in data.get("tokens", []):
        server = tok["server"].capitalize()
        if tok["is_configured"]:
            updated = tok.get("updated_at", "")[:10] or "?"
            print(f"  {server:12s} ✅ configured (updated {updated})")
        else:
            print(f"  {server:12s} ❌ not configured")

    print(f"\nConfigure tokens: {BASE_URL}/tokens")


def cmd_my_skills() -> None:
    email = get_email()
    data = _request("GET", f"/api/user-skills/{email}")

    skills = data.get("skills", [])
    always_on = [s for s in skills if s.get("category") == "public"]
    enabled = [
        s
        for s in skills
        if s.get("category") != "public" and s.get("is_enabled")
    ]
    disabled = [
        s
        for s in skills
        if s.get("category") != "public" and not s.get("is_enabled")
    ]

    print(f"Skills for {email}:\n")

    if always_on:
        print(f"Always enabled ({len(always_on)}):")
        for s in always_on:
            print(f"  ✅ {s['display_name']} [{s['name']}] -- {s['description'][:60]}")
        print()

    if enabled:
        print(f"Enabled optional ({len(enabled)}):")
        for s in enabled:
            print(f"  ✅ {s['display_name']} [{s['name']}] -- {s['description'][:60]}")
        print()

    if disabled:
        print(f"Available (disabled) ({len(disabled)}):")
        for s in disabled:
            users = s.get("users_count", 0)
            suffix = f" ({users} users)" if users else ""
            print(f"  ⬚ {s['display_name']} [{s['name']}] -- {s['description'][:60]}{suffix}")
        print()

    print(f"Manage: {BASE_URL}/skills")


def cmd_toggle(skill_name: str, on_off: str) -> None:
    if on_off not in ("on", "off"):
        print("Error: specify on or off", file=sys.stderr)
        sys.exit(1)

    email = get_email()
    encoded_name = urllib.request.quote(skill_name, safe="")
    is_enabled = on_off == "on"
    data = _request(
        "PATCH",
        f"/api/user-skills/{email}/{encoded_name}",
        {"is_enabled": is_enabled},
    )

    if data.get("success"):
        print(f"✅ {data.get('message', 'Done')}")
        print("Change will take effect in the next message.")
    else:
        print(f"❌ {data.get('message', 'Error')}")
        sys.exit(1)


def cmd_search(query: str) -> None:
    encoded = urllib.request.quote(query, safe="")
    data = _request("GET", f"/api/skills?q={encoded}")

    skills = data.get("skills", [])
    if not skills:
        print(f"No results found for \"{query}\".")
        return

    print(f"Search results for \"{query}\":\n")
    for s in skills:
        cat = s.get("category", "")
        users = s.get("users_count", 0)
        active = "✅" if s.get("is_active") else "⬚"
        suffix = f" [{users} users]" if users else ""
        print(
            f"  {active} {s.get('display_name', s['name'])} — "
            f"{s['description'][:60]} [{cat}]{suffix}"
        )


def cmd_download(skill_name: str) -> None:
    result = _request("GET", f"/api/skills/{skill_name}/download")

    if isinstance(result, bytes):
        extract_dir = Path(f"./{skill_name}")
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(BytesIO(result)) as zf:
            zf.extractall(extract_dir)
        size_kb = len(result) / 1024

        # ZIP may contain a nested folder with the skill name — find SKILL.md
        skill_md = extract_dir / "SKILL.md"
        if not skill_md.exists():
            nested = extract_dir / skill_name / "SKILL.md"
            if nested.exists():
                skill_md = nested

        print(f"✅ Skill \"{skill_name}\" downloaded and extracted ({size_kb:.1f} KB)")
        print(f"   Directory: {extract_dir.resolve()}")
        if skill_md.exists():
            print(f"   SKILL.md:   {skill_md.resolve()}")
            print()
            print("Next steps:")
            print(f"  1. Read SKILL.md: cat {skill_md.resolve()}")
            print(f"  2. Enable the skill for new chats:")
            print(f"     python /mnt/skills/public/settings-manager/scripts/settings-cli.py toggle {skill_name} on")
            print(f"  3. Test the skill -- try running the scenarios described in SKILL.md")
        else:
            print("   ⚠️ SKILL.md not found in the archive")
    elif isinstance(result, dict):
        msg = result.get("message", "")
        if msg:
            print(f"ℹ️ {msg}")
        else:
            print(f"ℹ️ Skill \"{skill_name}\" is not available for download.")


def cmd_upload(skill_file: str) -> None:
    email = get_email()
    skill_path = Path(skill_file)

    if not skill_path.exists():
        print(f"❌ File not found: {skill_path}", file=sys.stderr)
        sys.exit(1)

    if skill_path.suffix != ".skill":
        print(
            "❌ Expected a .skill file. Package the skill first:",
            file=sys.stderr,
        )
        print(
            "   python /mnt/skills/public/skill-creator/scripts/package_skill.py <skill-directory>",
            file=sys.stderr,
        )
        sys.exit(1)

    zip_bytes = skill_path.read_bytes()
    filename = skill_path.name

    # Multipart upload
    boundary = "----SkillUploadBoundary"
    body = bytearray()

    # author_email field
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="author_email"\r\n\r\n'
    body += f"{email}\r\n".encode()

    # file field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    body += b"Content-Type: application/zip\r\n\r\n"
    body += zip_bytes
    body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    url = f"{BASE_URL}/api/skills"
    req = urllib.request.Request(url, data=bytes(body), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    resp = urllib.request.urlopen(req, timeout=30, context=_ssl_ctx())
    data = json.loads(resp.read().decode())

    skill_name = skill_path.stem  # "my-skill.skill" → "my-skill"

    if data.get("success"):
        print(f"✅ {data.get('message', 'Skill uploaded')}")
        print()
        print("Next steps:")
        print(f"  1. Enable the skill: python /mnt/skills/public/settings-manager/scripts/settings-cli.py toggle {skill_name} on")
        print(f"  2. Start a new chat and test the skill")
    else:
        print(f"❌ {data.get('message', 'Error')}")
        errors = data.get("errors", [])
        for e in errors:
            print(f"   - {e}")
        sys.exit(1)


# ── Main ─────────────────────────────────────────────────────────────────


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "help"):
        print("Usage: settings-cli.py <command> [arguments]")
        print()
        print("Commands:")
        print("  check-tokens              Check MCP token status")
        print("  my-skills                 Show user skills")
        print("  toggle <name> on|off      Enable/disable a skill")
        print("  search <query>            Search skills by description")
        print("  download <name>           Download a skill (user-uploaded)")
        print("  upload <file.skill>       Upload/update a skill (.skill file)")
        sys.exit(0 if len(sys.argv) > 1 else 1)

    cmd = sys.argv[1]

    try:
        if cmd == "check-tokens":
            cmd_check_tokens()
        elif cmd == "my-skills":
            cmd_my_skills()
        elif cmd == "toggle":
            if len(sys.argv) < 4:
                print(
                    "Usage: settings-cli.py toggle <skill-name> on|off",
                    file=sys.stderr,
                )
                sys.exit(1)
            cmd_toggle(sys.argv[2], sys.argv[3])
        elif cmd == "search":
            if len(sys.argv) < 3:
                print(
                    "Usage: settings-cli.py search <query>",
                    file=sys.stderr,
                )
                sys.exit(1)
            cmd_search(" ".join(sys.argv[2:]))
        elif cmd == "download":
            if len(sys.argv) < 3:
                print(
                    "Usage: settings-cli.py download <skill-name>",
                    file=sys.stderr,
                )
                sys.exit(1)
            cmd_download(sys.argv[2])
        elif cmd == "upload":
            if len(sys.argv) < 3:
                print(
                    "Usage: settings-cli.py upload <file.skill>",
                    file=sys.stderr,
                )
                sys.exit(1)
            cmd_upload(sys.argv[2])
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            sys.exit(1)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
            err = json.loads(body)
            body = err.get("message", body)
        except Exception:
            pass
        print(f"❌ HTTP {e.code}: {body or e.reason}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"❌ Connection error: {e.reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
