---
name: pdf-markdown
description: Convert PDF to Markdown with images via MinerU OCR API. Use when markdown output with preserved images is needed. Supports Russian (default) and other languages.
---

# PDF to Markdown

Convert PDF documents to Markdown with images using MinerU OCR API.

## Quick Start

```bash
python /mnt/skills/public/pdf-markdown/scripts/convert.py \
    -i /mnt/user-data/uploads/document.pdf \
    -o /mnt/user-data/outputs/document
```

Output:
```
/mnt/user-data/outputs/document/
├── document.md
└── images/
    ├── img_001.jpg
    └── ...
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-i, --input` | required | PDF file path |
| `-o, --output` | required | Output directory |
| `-l, --lang` | `ru` | OCR language: `ru`, `en`, `ch` |

## Output Format

- **`<filename>.md`** - Markdown with `![](images/img_001.jpg)` references
- **`images/`** - Extracted images renamed sequentially

**Large PDF safeguard:** After conversion, check output size before reading:
```bash
wc -l /mnt/user-data/outputs/document/document.md
```
If the markdown > 1000 lines, do NOT read the entire file. Use `head -200` or `grep` to find relevant sections.

## Working with Images

After conversion, images (charts, diagrams, tables) are saved to `images/` folder.
To understand what's shown on an image, use the `describe-image` skill:

```bash
python /mnt/skills/public/describe-image/scripts/describe.py \
    -i /path/to/images/img_001.jpg \
    -c "Optional context about the image"
```

See `/mnt/skills/public/describe-image/SKILL.md` for details.

## Troubleshooting

**Timeout on large documents:**
```bash
python /mnt/skills/public/pdf-markdown/scripts/convert.py -i doc.pdf -o out --timeout 600
```

**Poor OCR for Russian:** Ensure `-l ru` (default).

## API Reference

See `references/api.md` for MinerU API details.
