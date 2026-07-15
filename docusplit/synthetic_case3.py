from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from PyPDF2 import PdfWriter


CODED_FORMS = [
    ("HIV Consent Form", "ACF0208ME"),
    ("Replacement Form", "LREP1000917"),
    ("New Business Application", "APA400113TCA"),
    ("Disclosure Accelerated Death Benefit", "ACCDISC0916"),
    ("Statement of Understanding", "AG06NY0218"),
    ("Application Supplement", "MSUMU27CA0219"),
    ("TLA Application Supplement LTC Critical Illness Chronic Illness", "MSULT10FL0319"),
    ("State Disclosure", "DIS115207"),
    ("Disclosure Terminal Illness", "ACCDISCPA0212"),
    ("Allocation Form", "ICC24TSUIU11IC0224"),
]

UNCODED_CATEGORIES = [
    "Invoice",
    "Contract",
    "Receipt",
    "Bank Statement",
    "Drivers License",
    "Passport",
    "Tax Form",
    "Medical Record",
    "Utility Bill",
]

RUN_PATTERNS = [
    [("coded", 2), ("uncoded", 1), ("coded", 1)],
    [("uncoded", 2), ("coded", 2), ("uncoded", 1)],
    [("coded", 1), ("uncoded", 3), ("uncoded", 1), ("coded", 2)],
    [("uncoded", 1), ("uncoded", 2), ("coded", 3)],
    [("coded", 2), ("uncoded", 3), ("coded", 1), ("uncoded", 2)],
    [("uncoded", 2), ("coded", 1), ("uncoded", 2), ("coded", 2)],
    [("coded", 3), ("uncoded", 1), ("uncoded", 2), ("coded", 1)],
    [("uncoded", 1), ("coded", 2), ("uncoded", 2)],
    [("coded", 1), ("uncoded", 2), ("coded", 2), ("uncoded", 1)],
    [("uncoded", 3), ("coded", 1), ("uncoded", 1), ("coded", 2)],
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate mixed coded/uncoded synthetic policy fixtures.")
    parser.add_argument("--output", type=Path, default=Path("synthetic_case3_50"))
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--start-index", type=int, default=1)
    args = parser.parse_args()

    manifest = generate_dataset(args.output, args.count, args.start_index)
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"created {args.count} synthetic PDFs in {args.output}")
    print(f"manifest: {manifest_path}")


def generate_dataset(output_root: Path, count: int, start_index: int) -> dict[str, object]:
    case_dir = output_root / "case_3_mixed_coded_uncoded"
    case_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for offset in range(count):
        file_number = start_index + offset
        stem = f"synthetic_case3_{file_number:03d}.pdf"
        pattern = RUN_PATTERNS[offset % len(RUN_PATTERNS)]
        pages, expected_runs = build_document(file_number, pattern)

        pdf_path = case_dir / stem
        raw_path = case_dir / f"{stem}.json"
        write_pdf(pdf_path, pages)
        raw_path.write_text(json.dumps({"Blocks": build_blocks(pages)}, indent=2), encoding="utf-8")

        files.append(
            {
                "file": str(raw_path.as_posix()),
                "synthetic_pdf": stem,
                "case": "mixed_coded_uncoded",
                "page_count": len(pages),
                "expected_runs": expected_runs,
            }
        )

    return {
        "dataset": output_root.name,
        "total_files": count,
        "cases": {"mixed_coded_uncoded": count},
        "uncoded_categories": UNCODED_CATEGORIES,
        "files": files,
    }


def build_document(file_number: int, pattern: list[tuple[str, int]]) -> tuple[list[list[str]], list[dict[str, object]]]:
    pages: list[list[str]] = []
    expected_runs: list[dict[str, object]] = []
    coded_index = file_number % len(CODED_FORMS)
    uncoded_index = file_number % len(UNCODED_CATEGORIES)
    page_number = 1

    for run_index, (kind, length) in enumerate(pattern, start=1):
        start_page = page_number
        if kind == "coded":
            requirement_type, policy_code = CODED_FORMS[coded_index % len(CODED_FORMS)]
            coded_index += 1
            for page_in_run in range(1, length + 1):
                pages.append(coded_page_lines(file_number, requirement_type, policy_code, page_in_run, length))
                page_number += 1
            expected_runs.append(
                {
                    "start_page": start_page,
                    "end_page": page_number - 1,
                    "kind": "coded",
                    "requirement_type": requirement_type,
                    "policy_code": policy_code,
                }
            )
        else:
            category = UNCODED_CATEGORIES[uncoded_index % len(UNCODED_CATEGORIES)]
            uncoded_index += 1
            document_id = f"UC-{file_number:03d}-{run_index:02d}"
            for page_in_run in range(1, length + 1):
                pages.append(uncoded_page_lines(file_number, category, document_id, page_in_run, length))
                page_number += 1
            expected_runs.append(
                {
                    "start_page": start_page,
                    "end_page": page_number - 1,
                    "kind": "uncoded",
                    "document_category": category,
                }
            )

    return pages, expected_runs


def coded_page_lines(
    file_number: int,
    requirement_type: str,
    policy_code: str,
    page_in_run: int,
    page_count: int,
) -> list[str]:
    return [
        requirement_type,
        f"Form code {policy_code}",
        f"Synthetic packet {file_number:03d} page {page_in_run} of {page_count}",
        f"Policy Number: POL-{file_number:05d}",
        "Applicant Name: Jordan Avery",
        "Owner Signature: ____________________",
    ]


def uncoded_page_lines(
    file_number: int,
    category: str,
    document_id: str,
    page_in_run: int,
    page_count: int,
) -> list[str]:
    if category == "Invoice":
        return [
            "Invoice",
            f"Invoice Number: {document_id}",
            "Bill To: Jordan Avery",
            f"Invoice Date: 07/{(file_number % 20) + 1:02d}/2026",
            "Total Amount Due: $248.90",
            f"Page {page_in_run} of {page_count}",
        ]
    if category == "Contract":
        return [
            "Service Agreement",
            f"Contract Number: {document_id}",
            "Client: Jordan Avery",
            "Term: Twelve months from effective date",
            "Authorized Signature: ____________________",
            f"Page {page_in_run} of {page_count}",
        ]
    if category == "Receipt":
        return [
            "Receipt",
            f"Receipt Number: {document_id}",
            "Payment Method: Card ending 1842",
            "Subtotal: $74.25",
            "Total Amount: $80.19",
            f"Page {page_in_run} of {page_count}",
        ]
    if category == "Bank Statement":
        return [
            "Bank Statement",
            f"Account Number: {document_id}",
            "Statement Period: 06/01/2026 - 06/30/2026",
            "Beginning Balance: $4,125.19",
            "Ending Balance: $4,982.33",
            f"Page {page_in_run} of {page_count}",
        ]
    if category == "Drivers License":
        return [
            "Driver License",
            f"License Number: {document_id}",
            "Name: Jordan Avery",
            "Date of Birth: 04/12/1984",
            "Expiration Date: 04/12/2030",
            f"Page {page_in_run} of {page_count}",
        ]
    if category == "Passport":
        return [
            "Passport",
            f"Passport Number: {document_id}",
            "Surname: Avery",
            "Given Names: Jordan",
            "Expiration Date: 05/18/2031",
            f"Page {page_in_run} of {page_count}",
        ]
    if category == "Tax Form":
        return [
            "Tax Form 1099 Summary",
            f"Reference Number: {document_id}",
            "Payer: Example Financial Services",
            "Recipient: Jordan Avery",
            "Total Income: $1,284.11",
            f"Page {page_in_run} of {page_count}",
        ]
    if category == "Medical Record":
        return [
            "Medical Record",
            f"Patient Number: {document_id}",
            "Patient: Jordan Avery",
            "Diagnosis: Routine follow-up",
            "Provider Signature: ____________________",
            f"Page {page_in_run} of {page_count}",
        ]
    return [
        "Utility Bill",
        f"Account Number: {document_id}",
        "Service Address: 1200 Market Street",
        "Amount Due: $136.42",
        "Balance Due: $136.42",
        f"Page {page_in_run} of {page_count}",
    ]


def build_blocks(pages: list[list[str]]) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for page_number, lines in enumerate(pages, start=1):
        for line_index, line in enumerate(lines):
            top = 0.06 + line_index * 0.075
            blocks.append(line_block(line, page_number, top))
            left = 0.07
            for word in line.split():
                width = min(max(len(word) * 0.014, 0.04), 0.18)
                blocks.append(word_block(word, page_number, top + 0.002, left, width))
                left = min(left + width + 0.018, 0.84)
    return blocks


def line_block(text: str, page_number: int, top: float) -> dict[str, object]:
    return text_block("LINE", text, page_number, top, 0.07, 0.82)


def word_block(text: str, page_number: int, top: float, left: float, width: float) -> dict[str, object]:
    return text_block("WORD", text, page_number, top, left, width)


def text_block(block_type: str, text: str, page_number: int, top: float, left: float, width: float) -> dict[str, object]:
    height = 0.024
    return {
        "BlockType": block_type,
        "Confidence": 99.0,
        "Text": text,
        "Geometry": {
            "BoundingBox": {"Width": width, "Height": height, "Left": left, "Top": top},
            "Polygon": [
                {"X": left, "Y": top},
                {"X": left + width, "Y": top},
                {"X": left + width, "Y": top + height},
                {"X": left, "Y": top + height},
            ],
        },
        "Id": str(uuid4()),
        "Page": page_number,
    }


def write_pdf(path: Path, pages: list[list[str]]) -> None:
    try:
        import fitz  # type: ignore
    except Exception:
        write_blank_pdf(path, len(pages))
        return

    document = fitz.open()
    for lines in pages:
        page = document.new_page(width=612, height=792)
        y = 72
        for line in lines:
            page.insert_text((72, y), line, fontsize=11)
            y += 24
    document.save(path)
    document.close()


def write_blank_pdf(path: Path, page_count: int) -> None:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)


if __name__ == "__main__":
    main()