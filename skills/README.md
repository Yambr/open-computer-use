# Skills

This directory bundles AI skills that ship inside the sandbox image at `/mnt/skills/`. Each subdirectory under `public/` and `examples/` is a self-contained skill with its own `SKILL.md`.

## Licensing

Skills here come from three different sources, each with its own license:

| Source | Where | License | Notes |
| --- | --- | --- | --- |
| Project-original | `public/describe-image/`, `public/sub-agent/` | MIT (SPDX header) | Authored for this project. |
| Apache 2.0 forks | `public/frontend-design/`, `public/webapp-testing/`, `examples/*/` | Apache 2.0 (`LICENSE.txt`) | Imported under their original Apache license; safe to redistribute. |
| Anthropic-authored | `public/docx/`, `public/pdf/`, `public/pptx/`, `public/xlsx/`, `public/file-reading/`, `public/pdf-reading/` (any directory containing a proprietary `LICENSE.txt` starting with `© 2025 Anthropic, PBC`) | Anthropic Skill License (proprietary) | See disclaimer below. |

### Anthropic Skill disclaimer

> **The Anthropic-authored skills in this directory are governed by Anthropic's proprietary Skill License (see the `LICENSE.txt` next to each `SKILL.md`).** They are bundled here **for reference and convenience** of operators who already hold a valid Anthropic agreement (Commercial Terms, Consumer Terms, or a separate written agreement) that permits using these skills with Anthropic's services.
>
> **You are responsible for confirming your own license entitlement before deploying or distributing this image.** If you do not have an Anthropic agreement that covers these materials, remove or replace the affected skill directories before building or publishing the image — the toolchain falls back gracefully to open-source alternatives documented in each `SKILL.md` (`pandoc`, `python-docx`, `openpyxl`, `python-pptx`, `pdfplumber`, `pypdfium2`, `nbconvert`, etc.).
>
> The maintainers of this repository do not grant any sublicense to Anthropic-authored materials and make no representation about your right to use them. The presence of these files in this repository is a convenience for licensed users, not a transfer of rights.

### How to identify which skills are affected

```bash
grep -l "Anthropic, PBC" skills/*/*/LICENSE.txt
```

### Removing Anthropic skills before building

If your deployment is not covered by an Anthropic agreement, drop the affected directories before `docker build`:

```bash
for d in $(grep -l "Anthropic, PBC" skills/*/*/LICENSE.txt); do
    rm -rf "$(dirname "$d")"
done
docker build --platform linux/amd64 -t open-computer-use:latest .
```

The remaining MIT/Apache-licensed skills will still load.

## Layout

- `public/` — production skills auto-mounted at `/mnt/skills/public/`
- `examples/` — reference implementations under permissive licenses
- See each `SKILL.md` for usage instructions
