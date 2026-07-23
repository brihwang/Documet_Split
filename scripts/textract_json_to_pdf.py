#!/usr/bin/env python3
"""Render Textract LINE blocks into a lightweight visual-reference PDF."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0


def pdf_text(value: str) -> str:
    return (
        value.encode("latin-1", errors="replace")
        .decode("latin-1")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def page_stream(lines: list[dict[str, Any]]) -> bytes:
    commands = ["1 1 1 rg 0 0 612 792 re f"]
    for block in sorted(
        lines,
        key=lambda item: (
            item.get("Geometry", {}).get("BoundingBox", {}).get("Top", 0),
            item.get("Geometry", {}).get("BoundingBox", {}).get("Left", 0),
        ),
    ):
        box = block.get("Geometry", {}).get("BoundingBox", {})
        left = float(box.get("Left", 0)) * PAGE_WIDTH
        width = max(float(box.get("Width", 0)) * PAGE_WIDTH, 1)
        height = max(float(box.get("Height", 0)) * PAGE_HEIGHT, 1)
        bottom = PAGE_HEIGHT - (float(box.get("Top", 0)) * PAGE_HEIGHT) - height
        text = str(block.get("Text", ""))
        estimated_width_at_12 = max(len(text) * 6.0, 1)
        font_size = min(13.0, max(7.0, 12.0 * width / estimated_width_at_12))
        baseline = bottom + max((height - font_size) / 2, 1)
        commands.extend(
            [
                f"0.88 0.90 0.94 RG 0.35 w {left:.2f} {bottom:.2f} {width:.2f} {height:.2f} re S",
                (
                    f"BT /F1 {font_size:.2f} Tf 0.08 0.10 0.14 rg "
                    f"1 0 0 1 {left + 2:.2f} {baseline:.2f} Tm ({pdf_text(text)}) Tj ET"
                ),
            ]
        )
    return ("\n".join(commands) + "\n").encode("latin-1")


def build_pdf(page_lines: list[list[dict[str, Any]]]) -> bytes:
    font_object = 3 + (2 * len(page_lines))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Count {len(page_lines)} /Kids "
            f"[{' '.join(f'{3 + 2 * index} 0 R' for index in range(len(page_lines)))}] >>"
        ).encode("ascii"),
    ]
    for index, lines in enumerate(page_lines):
        content_object = 4 + (2 * index)
        stream = page_stream(lines)
        objects.extend(
            [
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH:.0f} {PAGE_HEIGHT:.0f}] "
                    f"/Resources << /Font << /F1 {font_object} 0 R >> >> "
                    f"/Contents {content_object} 0 R >>"
                ).encode("ascii"),
                f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
                + stream
                + b"endstream",
            ]
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def render(source: Path, output: Path) -> int:
    payload = json.loads(source.read_text(encoding="utf-8"))
    blocks = payload.get("Blocks")
    if not isinstance(blocks, list):
        raise ValueError(f"{source} does not contain a Textract Blocks list")

    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        if (
            isinstance(block, dict)
            and block.get("BlockType") == "LINE"
            and isinstance(block.get("Page"), int)
        ):
            by_page[block["Page"]].append(block)
    if not by_page:
        raise ValueError(f"{source} contains no Textract LINE blocks")

    page_count = max(by_page)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(build_pdf([by_page[page] for page in range(1, page_count + 1)]))
    return page_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Textract-style raw JSON")
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    pages = render(args.source, args.output)
    print(f"Wrote {pages} pages to {args.output}")


if __name__ == "__main__":
    main()
