#!/usr/bin/env python3
"""
Convert PDF to Markdown with images using MinerU OCR API.

Usage:
    python convert.py -i document.pdf -o ./output
    python convert.py -i document.pdf -o ./output -l en
"""

import argparse
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

API_URL = "https://api.anthropic.com/mineru/file_parse"


def convert_pdf(pdf_path: str, output_dir: str, lang: str = "ru", timeout: int = 300) -> dict:
    """Convert PDF to Markdown with images."""
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)

    if not pdf_path.exists():
        return {"success": False, "error": f"File not found: {pdf_path}"}

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = pdf_path.stem

    print(f"Converting: {pdf_path}")
    print(f"Language: {lang}")

    try:
        with open(pdf_path, "rb") as f:
            response = requests.post(
                API_URL,
                files={"files": (pdf_path.name, f, "application/pdf")},
                data={
                    "lang_list": lang,
                    "return_md": "true",
                    "return_images": "true",
                    "response_format_zip": "true",
                },
                timeout=timeout,
            )
            response.raise_for_status()
    except requests.Timeout:
        return {"success": False, "error": f"Timeout after {timeout}s"}
    except requests.RequestException as e:
        return {"success": False, "error": f"Request failed: {e}"}

    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            result = response.json()
            return {"success": False, "error": f"API error: {result.get('error', 'Unknown')}"}
        except json.JSONDecodeError:
            return {"success": False, "error": response.text[:500]}

    if "application/zip" not in content_type and response.content[:4] != b"PK\x03\x04":
        return {"success": False, "error": f"Unexpected response: {content_type}"}

    print(f"Received ZIP ({len(response.content)} bytes)")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        tmp.write(response.content)
        tmp_path = tmp.name

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                zf.extractall(tmp_dir)

            md_files = list(Path(tmp_dir).rglob("*.md"))
            if not md_files:
                return {"success": False, "error": "No markdown in ZIP"}

            src_md = md_files[0]
            src_images = src_md.parent / "images"

            with open(src_md, "r", encoding="utf-8") as f:
                md_content = f.read()

            dst_images = output_dir / "images"
            dst_images.mkdir(exist_ok=True)

            images_count = 0
            mapping = {}

            if src_images.exists():
                for src_img in sorted(src_images.glob("*")):
                    if src_img.suffix.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                        images_count += 1
                        new_name = f"img_{images_count:03d}{src_img.suffix.lower()}"
                        with open(src_img, "rb") as sf:
                            with open(dst_images / new_name, "wb") as df:
                                df.write(sf.read())
                        mapping[src_img.name] = new_name

            for old, new in mapping.items():
                md_content = md_content.replace(f"images/{old}", f"images/{new}")

            dst_md = output_dir / f"{filename}.md"
            with open(dst_md, "w", encoding="utf-8") as f:
                f.write(md_content)

            print(f"Output: {dst_md}")
            print(f"Images: {images_count}")

    finally:
        os.unlink(tmp_path)

    return {"success": True, "markdown": str(dst_md), "images": images_count}


def main():
    parser = argparse.ArgumentParser(description="Convert PDF to Markdown with images")
    parser.add_argument("-i", "--input", required=True, help="PDF file")
    parser.add_argument("-o", "--output", required=True, help="Output directory")
    parser.add_argument("-l", "--lang", default="ru", help="OCR language (default: ru)")
    parser.add_argument("--timeout", type=int, default=300, help=argparse.SUPPRESS)
    args = parser.parse_args()

    result = convert_pdf(args.input, args.output, args.lang, args.timeout)

    if result["success"]:
        print("\nDone!")
        sys.exit(0)
    else:
        print(f"\nError: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
