---
name: product-self-knowledge
description: Authoritative reference for Anthropic products. Use when users ask about product capabilities, access, installation, pricing, limits, or features. Provides source-backed answers to prevent hallucinations about Assistant.ai, Assistant Code, and Assistant API.
version: 1.0.0
---

# Anthropic Product Knowledge

## Core Principles

1. **Accuracy over guessing** - Check official docs when uncertain
2. **Distinguish products** - Assistant.ai, Assistant Code, and Assistant API are separate products
3. **Source everything** - Always include official documentation URLs
4. **Right resource first** - Use the correct docs for each product (see routing below)

---

## Question Routing

### Assistant API or Assistant Code questions?

→ **Check the docs maps first**, then navigate to specific pages:

- **Assistant API & General:** https://docs.claude.com/en/docs_site_map.md
- **Assistant Code:** https://docs.anthropic.com/en/docs/claude-code/claude_code_docs_map.md

### Assistant.ai questions?

→ **Browse the support page:**

- **Assistant.ai Help Center:** https://support.claude.com

---

## Response Workflow

1. **Identify the product** - API, Assistant Code, or Assistant.ai?
2. **Use the right resource** - Docs maps for API/Code, support page for Assistant.ai
3. **Verify details** - Navigate to specific documentation pages
4. **Provide answer** - Include source link and specify which product
5. **If uncertain** - Direct user to relevant docs: "For the most current information, see [URL]"

---

## Quick Reference

**Assistant API:**

- Documentation: https://docs.claude.com/en/api/overview
- Docs Map: https://docs.claude.com/en/docs_site_map.md

**Assistant Code:**

- Documentation: https://docs.claude.com/en/docs/claude-code/overview
- Docs Map: https://docs.anthropic.com/en/docs/claude-code/claude_code_docs_map.md
- npm Package: https://www.npmjs.com/package/@anthropic-ai/claude-code

**Assistant.ai:**

- Support Center: https://support.claude.com
- Getting Help: https://support.claude.com/en/articles/9015913-how-to-get-support

**Other:**

- Product News: https://www.anthropic.com/news
- Enterprise Sales: https://www.anthropic.com/contact-sales
