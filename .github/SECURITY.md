# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Open Computer Use, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email security concerns to the maintainers directly or use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability).

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

## Security Considerations

This project runs Docker containers with access to the Docker socket. Please review the [Security Notes](../README.md#security-notes) in the README before deploying.
