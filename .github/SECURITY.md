# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Open Computer Use, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, reach out via:
- **Telegram**: [@yambrcom](https://t.me/yambrcom)
- **GitHub**: [Private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)

## What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

## Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix or mitigation**: Depends on severity

## Scope

The following are in scope:
- Computer Use Server (`computer-use-server/`)
- Sandbox container escape
- MCP authentication bypass
- File access outside sandbox
- Open WebUI integration vulnerabilities

## Current Security Model

This project is designed for **closed, self-hosted** deployments. Key points:

- **Docker socket access** grants significant host control — run only in trusted environments
- **MCP_API_KEY** is the only auth for the MCP endpoint — set a strong random key
- **File/preview endpoints** use chat ID (UUID) as the sole access control — not a real security boundary
- **User identity** is client-asserted (HTTP headers), not verified server-side
- **API credentials** (GitLab, Anthropic) are passed in HTTP headers — use HTTPS if exposing externally

For multi-user deployments, see the **Security Roadmap** in [README.md](../README.md#security-roadmap).

## Known Issues

These are known limitations, not bugs — they reflect the current single-user design:

1. **Unauthenticated file access**: Anyone with a chat ID can download files via `/files/{chat_id}/`
2. **No user verification**: Server trusts `X-User-Email` header without validation
3. **Default credentials**: `admin@open-computer-use.dev` / `admin` in Open WebUI auto-init

We are working on per-session signed tokens, JWT validation, and audit logging. See README for the full roadmap.
