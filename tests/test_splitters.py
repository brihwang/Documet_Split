from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docusplit.classifier import (
    ai_split_rejection_reason,
    candidates_from_split_payload,
    confidence_metadata_from_payload,
)
from docusplit.config import load_settings
from docusplit.detector import detect_documents
from docusplit.models import PageText
from docusplit.policy_codes import PolicyCodeMatcher, extract_raw_pages, split_with_policy_codes


def raw_block(page: int, top: float, text: str) -> dict:
    return {
        "BlockType": "LINE",
        "Confidence": 99.0,
        "Text": text,
        "Page": page,
        "Geometry": {"BoundingBox": {"Top": top, "Left": 0.05, "Width": 0.9, "Height": 0.02}},
    }


def write_raw_json(path: Path, pages: list[list[str]]) -> None:
    blocks = []
    for page_number, lines in enumerate(pages, start=1):
        for line_index, line in enumerate(lines):
            blocks.append(raw_block(page_number, line_index / 20, line))
    path.write_text(json.dumps({"Blocks": blocks}), encoding="utf-8")


class SplitterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config.yaml"))

    def test_policy_code_splitter_keeps_uncoded_hidden_form_code_run_together(self) -> None:
        pages = [
            ["POL-001", "Known policy code page", "Policy Number: A-1"],
            [
                "SERVICE REQUEST FORM",
                "Form Number: HIDDEN-101",
                "Insurance company records",
                "Owner: Taylor Reed",
                "Address: 1 Main St",
                "Reason: account update",
                "Authorized signature: Taylor Reed",
            ],
            [
                "BENEFICIARY CHANGE FORM",
                "Form Number: HIDDEN-102",
                "Insurance company records",
                "Owner: Taylor Reed",
                "Address: 1 Main St",
                "Reason: beneficiary update",
                "Authorized signature: Taylor Reed",
            ],
            [
                "ADDRESS CHANGE FORM",
                "Form Number: HIDDEN-103",
                "Insurance company records",
                "Owner: Taylor Reed",
                "Address: 2 Main St",
                "Reason: mailing update",
                "Authorized signature: Taylor Reed",
            ],
            ["POL-999", "Different known policy code page", "Policy Number: Z-9"],
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "packet.raw.json"
            write_raw_json(raw_path, pages)
            raw_pages = extract_raw_pages(raw_path)

        result = split_with_policy_codes(
            raw_pages,
            raw_pages,
            PolicyCodeMatcher({"POL-001": "Known A", "POL-999": "Known Z"}),
            self.settings,
            use_ai=False,
        )

        self.assertIsNotNone(result)
        candidates, metadata = result or ([], {})
        self.assertEqual([(item.start_page, item.end_page) for item in candidates], [(1, 1), (2, 4), (5, 5)])
        self.assertEqual(metadata["uncoded_pages"], 3)

    def test_ai_dense_single_page_split_requires_very_high_confidence(self) -> None:
        pages = [PageText(index, f"Page {index}", "raw_json") for index in range(1, 4)]
        payload = {
            "overall_confidence": 0.95,
            "over_split_risk": 0.1,
            "documents": [
                {"start_page": 1, "end_page": 1, "confidence": 0.95},
                {"start_page": 2, "end_page": 2, "confidence": 0.95},
                {"start_page": 3, "end_page": 3, "confidence": 0.95},
            ],
        }

        candidates = candidates_from_split_payload(payload, pages)
        metadata = confidence_metadata_from_payload(payload)

        self.assertIsNotNone(candidates)
        self.assertIsNotNone(metadata)
        with patch.dict(os.environ, {"AI_DENSE_SPLIT_MIN_CONFIDENCE": "0.98"}):
            reason = ai_split_rejection_reason(candidates or [], pages, metadata or {})
        self.assertIn("dense split threshold is 0.98", reason or "")

    def test_distinct_same_category_documents_still_split_on_different_ids(self) -> None:
        pages = [
            PageText(
                1,
                "INVOICE\nInvoice Number: INV-100\nBill To: Alpha LLC\nAmount Due: $120\nTotal Amount: $120",
                "raw_json",
            ),
            PageText(
                2,
                "INVOICE\nInvoice Number: INV-200\nBill To: Beta LLC\nAmount Due: $240\nTotal Amount: $240",
                "raw_json",
            ),
        ]

        candidates = detect_documents(pages, self.settings)
        self.assertEqual([(item.start_page, item.end_page) for item in candidates], [(1, 1), (2, 2)])


if __name__ == "__main__":
    unittest.main()
