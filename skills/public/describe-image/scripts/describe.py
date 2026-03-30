#!/usr/bin/env python3
"""
Describe image using Vision API (Qwen3-VL).

Usage:
    python describe.py -i image.png
    python describe.py -i screenshot.jpg -c "This is a dashboard screenshot"
    python describe.py -i /path/to/folder --page 1 --page-size 50
"""

import argparse
import base64
import math
import mimetypes
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

# Default configuration (can be overridden by env vars)
DEFAULT_API_URL = "https://api.anthropic.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o"

# Supported image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# Batch processing limits
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

SYSTEM_PROMPT = """You are an expert image analyst. Your task is to create accurate and structured text descriptions of images.

IMPORTANT: Always respond in the same language as the user's message.

Description rules:
1. Identify the image type (chart, diagram, table, UI screenshot, flowchart, document photo, etc.)
2. Describe the content as accurately and completely as possible
3. For charts and graphs: specify axes, legend, trends, key values
4. For tables: describe structure, headers, key data
5. For UI screenshots: describe UI elements, their state, visible text
6. For flowcharts and process diagrams: describe relationships, stages, flow directions
7. Extract all visible text
8. If there are numerical data - provide them exactly

Response format:
- Start with a brief description of the image type
- Then give a detailed description of the content
- End with extracted text (if any)"""


def get_mime_type(file_path: Path) -> str:
    """Determine MIME type from file extension."""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type is None:
        ext = file_path.suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        mime_type = mime_map.get(ext, "image/png")
    return mime_type


def encode_image(image_path: Path) -> tuple[str, str]:
    """Read and encode image to base64."""
    mime_type = get_mime_type(image_path)
    with open(image_path, "rb") as f:
        base64_data = base64.b64encode(f.read()).decode("utf-8")
    return base64_data, mime_type


def describe_image(
    image_path: str,
    context: str = "",
    timeout: int = 120,
    verbose: bool = True,
) -> dict:
    """Describe image using Vision API."""
    image_path = Path(image_path)

    if not image_path.exists():
        return {"success": False, "error": f"File not found: {image_path}"}

    # Check file size (max ~20MB for base64)
    file_size = image_path.stat().st_size
    if file_size > 20 * 1024 * 1024:
        return {
            "success": False,
            "error": f"File too large: {file_size / 1024 / 1024:.1f}MB (max 20MB)",
        }

    # Get configuration from environment
    api_url = os.environ.get("VISION_API_URL", DEFAULT_API_URL)
    if not api_url.endswith("/v1/chat/completions"):
        api_url = api_url.rstrip("/") + "/v1/chat/completions"
    model = os.environ.get("VISION_MODEL", DEFAULT_MODEL)
    api_key = os.environ.get("VISION_API_KEY")

    if not api_key:
        return {"success": False, "error": "VISION_API_KEY not set"}

    if verbose:
        print(f"Describing: {image_path}")
        print(f"Model: {model}")
        if context:
            print(f"Context: {context}")

    # Encode image
    try:
        base64_image, mime_type = encode_image(image_path)
    except Exception as e:
        return {"success": False, "error": f"Failed to read image: {e}"}

    # Build user message with optional context
    if context:
        user_text = f"Context: {context}\n\nDescribe this image."
    else:
        user_text = "Describe this image."

    # Build request payload (OpenAI-compatible format)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_image}"},
                    },
                ],
            },
        ],
        "max_tokens": 4096,
        "temperature": 0.1,  # Low temperature for factual description
    }

    # Make API request
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            api_url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.Timeout:
        return {"success": False, "error": f"Request timeout after {timeout}s"}
    except requests.RequestException as e:
        return {"success": False, "error": f"API request failed: {e}"}

    # Parse response
    try:
        result = response.json()
    except Exception as e:
        return {"success": False, "error": f"Failed to parse response: {e}"}

    # Check for API error
    if "error" in result:
        return {"success": False, "error": f"API error: {result['error']}"}

    # Extract description from response
    try:
        description = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        return {"success": False, "error": f"Unexpected response format: {e}"}

    return {"success": True, "description": description}


def collect_images(folder: Path) -> list[Path]:
    """Collect all image files from folder, sorted by name."""
    images = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(folder.glob(f"*{ext}"))
        images.extend(folder.glob(f"*{ext.upper()}"))
    return sorted(set(images), key=lambda p: p.name.lower())


def process_folder(
    folder_path: str,
    context: str = "",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    timeout: int = 120,
) -> dict:
    """Process all images in a folder with pagination."""
    folder = Path(folder_path)

    if not folder.exists():
        return {"success": False, "error": f"Folder not found: {folder}"}

    if not folder.is_dir():
        return {"success": False, "error": f"Not a directory: {folder}"}

    # Collect and paginate images
    all_images = collect_images(folder)
    total_images = len(all_images)

    if total_images == 0:
        return {"success": False, "error": f"No images found in {folder}"}

    total_pages = math.ceil(total_images / page_size)

    if page < 1 or page > total_pages:
        return {
            "success": False,
            "error": f"Invalid page {page}. Valid range: 1-{total_pages}",
        }

    # Get slice for current page
    start_idx = (page - 1) * page_size
    end_idx = min(start_idx + page_size, total_images)
    page_images = all_images[start_idx:end_idx]

    print(f"Processing folder: {folder}")
    print(f"Total images: {total_images}, Page: {page}/{total_pages}")
    print(f"Processing images {start_idx + 1}-{end_idx}...")
    if context:
        print(f"Context: {context}")

    # Process images in parallel
    results = {}
    with ThreadPoolExecutor(max_workers=page_size) as executor:
        future_to_path = {
            executor.submit(describe_image, str(img), context, timeout, verbose=False): img
            for img in page_images
        }

        completed = 0
        for future in as_completed(future_to_path):
            img_path = future_to_path[future]
            completed += 1
            try:
                result = future.result()
                results[img_path] = result
                status = "OK" if result["success"] else "FAILED"
                print(f"  [{completed}/{len(page_images)}] {img_path.name}: {status}")
            except Exception as e:
                results[img_path] = {"success": False, "error": str(e)}
                print(f"  [{completed}/{len(page_images)}] {img_path.name}: ERROR")

    # Generate manifest content
    manifest_lines = [
        f'<images folder="{folder.absolute()}" page="{page}" total_pages="{total_pages}">',
        "",
    ]

    success_count = 0
    for img_path in page_images:
        result = results.get(img_path, {"success": False, "error": "Unknown error"})
        if result["success"]:
            success_count += 1
            manifest_lines.append(f'<image path="{img_path.name}">')
            manifest_lines.append(result["description"])
            manifest_lines.append("</image>")
        else:
            manifest_lines.append(f'<image path="{img_path.name}" error="true">')
            manifest_lines.append(f"Error: {result.get('error', 'Unknown error')}")
            manifest_lines.append("</image>")
        manifest_lines.append("")

    manifest_lines.append("</images>")
    manifest_content = "\n".join(manifest_lines)

    # Save manifest file
    manifest_path = folder / f"manifest-{page}.md"
    try:
        manifest_path.write_text(manifest_content, encoding="utf-8")
    except Exception as e:
        return {"success": False, "error": f"Failed to write manifest: {e}"}

    return {
        "success": True,
        "manifest_path": str(manifest_path),
        "manifest_content": manifest_content,
        "processed": len(page_images),
        "success_count": success_count,
        "total_images": total_images,
        "total_pages": total_pages,
        "current_page": page,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Describe image(s) using Vision API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Single image
    python describe.py -i chart.png
    python describe.py -i screenshot.jpg -c "Dashboard showing sales data"

    # Folder with images (batch processing)
    python describe.py -i /path/to/folder
    python describe.py -i /path/to/folder --page 2
    python describe.py -i /path/to/folder --page-size 100
        """,
    )
    parser.add_argument(
        "-i", "--input", required=True, help="Image file or folder path"
    )
    parser.add_argument(
        "-c", "--context", default="", help="Optional context about the image(s)"
    )
    parser.add_argument(
        "--page", type=int, default=1, help="Page number for folder processing (default: 1)"
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Images per page for folder processing (default: {DEFAULT_PAGE_SIZE}, max: {MAX_PAGE_SIZE})",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress per-image logging"
    )
    parser.add_argument("--timeout", type=int, default=120, help=argparse.SUPPRESS)
    args = parser.parse_args()

    # Validate page-size
    if args.page_size < 1 or args.page_size > MAX_PAGE_SIZE:
        print(f"Error: --page-size must be between 1 and {MAX_PAGE_SIZE}", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input)

    # Determine if input is file or folder
    if input_path.is_dir():
        # Folder processing
        result = process_folder(
            args.input,
            args.context,
            args.page,
            args.page_size,
            args.timeout,
        )

        if result["success"]:
            print(f"\nProcessed {result['success_count']}/{result['processed']} images")
            print(f"Created: {result['manifest_path']}")

            if result["total_pages"] > 1:
                remaining = result["total_pages"] - result["current_page"]
                if remaining > 0:
                    next_pages = ", ".join(
                        f"--page {i}"
                        for i in range(result["current_page"] + 1, result["total_pages"] + 1)
                    )
                    print(f"Remaining pages: {remaining} (use {next_pages})")

            print(f"\nUse: view {result['manifest_path']}")
            sys.exit(0)
        else:
            print(f"\nError: {result['error']}", file=sys.stderr)
            sys.exit(1)
    else:
        # Single file processing
        result = describe_image(args.input, args.context, args.timeout, verbose=not args.quiet)

        if result["success"]:
            print("\n" + "=" * 60)
            print("DESCRIPTION:")
            print("=" * 60)
            print(result["description"])
            sys.exit(0)
        else:
            print(f"\nError: {result['error']}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
