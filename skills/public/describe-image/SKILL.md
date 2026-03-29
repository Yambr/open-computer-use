---
name: describe-image
description: Describe images (charts, diagrams, tables, screenshots) using Vision AI. Use as fallback when you cannot read an image file directly. Supports batch processing of folders.
---

# Describe Image

Analyze images using Vision AI and generate detailed text descriptions in Russian.

## Quick Start

```bash
# Single image
python /mnt/skills/public/describe-image/scripts/describe.py \
    -i /path/to/image.png

# Folder with images
python /mnt/skills/public/describe-image/scripts/describe.py \
    -i /path/to/folder
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-i, --input` | required | Image file or folder path |
| `-c, --context` | "" | (optional) Context for better accuracy (e.g., "Sales dashboard Q4") |
| `--page` | 1 | (optional) Page number for folder processing |
| `--page-size` | 50 | (optional) Images per page (max 100) |
| `--quiet` | false | (optional) Suppress per-image logging in single-file mode |

## Supported Image Types

- Charts and graphs (bar, line, pie, radar, scatter)
- Tables and spreadsheets
- UI screenshots
- Flowcharts and process diagrams
- Architecture diagrams
- Document photos and scans

## Examples

**Single image:**
```bash
python /mnt/skills/public/describe-image/scripts/describe.py \
    -i /home/assistant/document/images/img_001.jpg
```

**With context for better accuracy:**
```bash
python /mnt/skills/public/describe-image/scripts/describe.py \
    -i dashboard.png \
    -c "Quarterly sales report showing EMEA region performance"
```

**Folder with images (batch processing):**
```bash
# Process first 50 images
python /mnt/skills/public/describe-image/scripts/describe.py \
    -i /home/assistant/assessment/images/

# Process images 51-100 (page 2)
python /mnt/skills/public/describe-image/scripts/describe.py \
    -i /home/assistant/assessment/images/ --page 2

# Process with custom page size
python /mnt/skills/public/describe-image/scripts/describe.py \
    -i /home/assistant/assessment/images/ --page-size 100
```

## Output

**Single image:** Returns structured description to stdout.

**Folder:** Creates `manifest-N.md` file in the folder. Use `view` to read it.

Console output:
```
Processed 50/150 images
Created: /home/assistant/assessment/images/manifest-1.md
Remaining pages: 2 (use --page 2, --page 3)

Use: view /home/assistant/assessment/images/manifest-1.md
```

After running the command, use the `view` tool to read the manifest file.

Manifest format (LLM-friendly XML):
```xml
<images folder="/home/assistant/assessment/images" page="1" total_pages="3">

<image path="img_001.jpg">
Horizontal bar chart showing deviations from the average score...
</image>

<image path="img_002.jpg">
Diagram with five rating categories: "Below expectations", "Needs development"...
</image>

</images>
```

## Environment

Requires `VISION_API_KEY` environment variable.
