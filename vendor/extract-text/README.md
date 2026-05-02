# `extract-text`

Vendored binary used by the `file-reading` and `pdf-reading` skills.

## What it is

`extract-text` is a Rust CLI built by Anthropic for unified plain-text extraction across document formats:

- **docx / odt / epub** → Markdown (headings, bold, lists, links, tables)
- **xlsx** → tab-separated rows under `## Sheet:` headers
- **pptx** → text under `## Slide N` headers
- **ipynb** → fenced code cells
- **rtf / html / htm** → plain text

Architecture: x86_64 ELF, dynamically linked, ~2 MB.

**This binary is x86_64-only.** Building the image under `linux/arm64`
(Apple Silicon, AWS Graviton without emulation) will produce a
non-functional binary — `extract-text /path/to/file.docx` segfaults
under qemu emulation. The project `CLAUDE.md` mandates
`docker build --platform linux/amd64`; honor that. For native arm64
deployments, either run amd64 under qemu (slow) or remove the `COPY`
line in `Dockerfile` and rely on the open-source fallbacks
(pandoc / python-docx / openpyxl / python-pptx / nbconvert) documented
in `skills/public/file-reading/SKILL.md`.

## Why it lives here

The binary is bundled into the sandbox image at `/usr/local/bin/extract-text` by the `Dockerfile`:

```dockerfile
COPY --chown=root:root vendor/extract-text/extract-text /usr/local/bin/extract-text
RUN chmod +x /usr/local/bin/extract-text
```

The skills under `/mnt/skills/public/file-reading/` and `/mnt/skills/public/pdf-reading/` shell out to it as their first move for the formats listed above.

## Licensing

This binary is part of Anthropic's Skill bundle. Use is governed by your Anthropic agreement (Commercial Terms, Consumer Terms, or a separate written agreement). See `skills/README.md` in the project root for the full disclaimer that applies to all Anthropic-authored materials in this repository.

If your deployment is not covered by an Anthropic agreement, remove this directory and the matching `COPY` line in the `Dockerfile`. The dispatch tables in `file-reading/SKILL.md` and `pdf-reading/SKILL.md` document open-source fallbacks (`pandoc`, `python-docx`, `openpyxl`, `python-pptx`, `nbconvert`) that work without `extract-text`.

## Followup

A future patch should replace this vendored binary with a build-time `curl` + `sha256sum -c` step pulling from a signed release URL, so the blob does not live in git history.
