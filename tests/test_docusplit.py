from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyPDF2 import PdfReader
from PyPDF2 import PdfWriter

from docusplit.classifier import classify_document
from docusplit.config import load_settings
from docusplit.extractor import extract_pdf_text
from docusplit.models import Classification, DocumentCandidate
from docusplit.organizer import filename_for, process_file


def write_text_pdf(path: Path, pages: list[list[str]]) -> None:
    objects: list[str] = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [{kids}] /Count {count} >>",
    ]
    page_ids = []
    next_id = 3
    for lines in pages:
        page_id = next_id
        font_id = next_id + 1
        content_id = next_id + 2
        next_id += 3
        page_ids.append(page_id)
        stream = pdf_text_stream(lines)
        objects.append(f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> /MediaBox [0 0 612 792] /Contents {content_id} 0 R >>")
        objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        objects.append(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")

    objects[1] = objects[1].format(kids=" ".join(f"{page_id} 0 R" for page_id in page_ids), count=len(page_ids))

    chunks = ["%PDF-1.4\n"]
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(sum(len(chunk.encode("latin-1")) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n{obj}\nendobj\n")
    xref_offset = sum(len(chunk.encode("latin-1")) for chunk in chunks)
    chunks.append(f"xref\n0 {len(objects) + 1}\n")
    chunks.append("0000000000 65535 f \n")
    for offset in offsets[1:]:
        chunks.append(f"{offset:010d} 00000 n \n")
    chunks.append(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n")
    path.write_bytes("".join(chunks).encode("latin-1"))


def pdf_text_stream(lines: list[str]) -> str:
    commands = ["BT", "/F1 14 Tf", "72 740 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -22 Td")
        commands.append(f"({escape_pdf_text(line)}) Tj")
    commands.append("ET")
    return "\n".join(commands)


def escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class DocusplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root / "config.yaml"
        self.config.write_text(
            """
min_confidence: 0.70
filename_template: "{date}_{sender}_{type}.pdf"
default_category: Other
review_folder: review_needed
categories:
  Invoice:
    folder: "Finance/Invoices/{year}/{sender}"
    keywords: [invoice, amount due, bill to]
  Contract:
    folder: "Legal/Contracts/{sender}"
    keywords: [agreement, contract, parties, effective date]
  Receipt:
    folder: "Finance/Receipts/{year}"
    keywords: [receipt, paid, total]
  Other:
    folder: "Other/{year}"
    keywords: []
""",
            encoding="utf-8",
        )
        self.settings = load_settings(self.config)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_splits_two_document_pdf_and_routes_by_config(self) -> None:
        source = self.root / "mixed.pdf"
        write_text_pdf(
            source,
            [
                ["Acme Supplies", "Invoice Number 123", "Date 2026-07-01", "Amount Due $100"],
                ["Northwind Legal", "Contract Agreement", "Effective Date 2026-06-15", "Parties agree"],
            ],
        )

        outputs = process_file(source, self.root / "organized", self.settings, self.root / "errors")

        self.assertEqual(len(outputs), 2)
        self.assertEqual(outputs[0].classification.document_type, "Invoice")
        self.assertEqual(outputs[1].classification.document_type, "Contract")
        self.assertIn("Finance/Invoices/2026/Acme_Supplies", str(outputs[0].output_file))
        self.assertIn("Legal/Contracts/Northwind_Legal", str(outputs[1].output_file))
        self.assertEqual(len(PdfReader(str(outputs[0].output_file)).pages), 1)
        self.assertEqual(len(PdfReader(str(outputs[1].output_file)).pages), 1)

    def test_single_document_pdf_stays_single(self) -> None:
        source = self.root / "invoice.pdf"
        write_text_pdf(
            source,
            [
                ["Acme Supplies", "Invoice Number 123", "Date 2026-07-01", "Amount Due $100"],
                ["Line items continued", "Payment terms net 30"],
            ],
        )

        outputs = process_file(source, self.root / "organized", self.settings, self.root / "errors")

        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].start_page, 1)
        self.assertEqual(outputs[0].end_page, 2)
        self.assertEqual(len(PdfReader(str(outputs[0].output_file)).pages), 2)

    def test_low_confidence_goes_to_review_with_sidecar(self) -> None:
        source = self.root / "unknown.pdf"
        write_text_pdf(source, [["A mystery page", "No useful category words", "2026-05-01"]])

        outputs = process_file(source, self.root / "organized", self.settings, self.root / "errors")

        self.assertEqual(len(outputs), 1)
        self.assertTrue(outputs[0].routed_to_review)
        self.assertIn("errors/review_needed", str(outputs[0].output_file))
        payload = json.loads(outputs[0].sidecar_file.read_text(encoding="utf-8"))
        self.assertEqual(payload["document_type"], "Other")

    def test_filename_sanitization(self) -> None:
        classification = Classification(
            document_type="Invoice",
            sender="Bad / Sender: Inc.",
            date="2026-07-01",
            confidence=0.9,
            reason="test",
        )

        self.assertEqual(filename_for(classification, self.settings), "2026-07-01_Bad_Sender_Inc_Invoice.pdf")

    def test_scanned_pdf_can_use_ocr_hook(self) -> None:
        source = self.root / "scanned.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with source.open("wb") as handle:
            writer.write(handle)

        with patch("docusplit.extractor.try_ocr_page", return_value="Acme Receipt Date 2026-07-02 Total $20"):
            pages = extract_pdf_text(source)

        self.assertEqual(pages[0].source, "ocr")
        self.assertIn("Receipt", pages[0].text)

    def test_missing_ai_key_falls_back_to_rules(self) -> None:
        candidate = DocumentCandidate(
            start_page=1,
            end_page=1,
            text="Acme Supplies\nInvoice Number 123\nDate 2026-07-01\nAmount Due $100",
        )

        with patch.dict("os.environ", {}, clear=True):
            classification = classify_document(candidate, self.settings)

        self.assertEqual(classification.document_type, "Invoice")
        self.assertEqual(classification.metadata["classifier"], "rules")

    def test_single_category_pdf_does_not_call_ai(self) -> None:
        source = self.root / "single_category.pdf"
        write_text_pdf(
            source,
            [
                ["Acme Supplies", "Invoice Number 123", "Date 2026-07-01", "Amount Due $100"],
                ["Acme Supplies", "Invoice Number 124", "Date 2026-07-02", "Amount Due $200"],
            ],
        )

        with patch("docusplit.classifier.classify_with_ai") as ai:
            outputs = process_file(source, self.root / "organized", self.settings, self.root / "errors")

        ai.assert_not_called()
        self.assertEqual(len(outputs), 2)
        self.assertEqual(outputs[0].classification.metadata["classifier"], "rules")
        self.assertFalse(outputs[0].classification.metadata["mixed_source_pdf"])

    def test_mixed_category_pdf_allows_ai(self) -> None:
        source = self.root / "mixed_category.pdf"
        write_text_pdf(
            source,
            [
                ["Acme Supplies", "Invoice Number 123", "Date 2026-07-01", "Amount Due $100"],
                ["Northwind Legal", "Contract Agreement", "Effective Date 2026-06-15", "Parties agree"],
            ],
        )
        ai_classification = Classification(
            document_type="Invoice",
            sender="AI Sender",
            date="2026-07-01",
            confidence=0.95,
            reason="AI classification used for mixed source PDF.",
            metadata={"classifier": "ai"},
        )

        with patch("docusplit.classifier.classify_with_ai", return_value=ai_classification) as ai:
            outputs = process_file(source, self.root / "organized", self.settings, self.root / "errors")

        self.assertGreaterEqual(ai.call_count, 1)
        self.assertTrue(outputs[0].classification.metadata["mixed_source_pdf"])


if __name__ == "__main__":
    unittest.main()
