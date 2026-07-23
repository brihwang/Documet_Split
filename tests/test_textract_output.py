from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from docusplit.models import DocumentCandidate
from docusplit.organizer import (
    split_textract_payload,
    write_split_plan,
    write_split_textract_json,
)


def textract_payload() -> dict:
    blocks = []
    for page in range(1, 4):
        page_id = f"page-{page}"
        line_id = f"line-{page}"
        blocks.extend(
            [
                {
                    "BlockType": "PAGE",
                    "Id": page_id,
                    "Page": page,
                    "Relationships": [
                        {"Type": "CHILD", "Ids": [line_id, "missing-id"]}
                    ],
                },
                {
                    "BlockType": "LINE",
                    "Id": line_id,
                    "Page": page,
                    "Text": f"Page {page}",
                },
            ]
        )
    return {
        "DocumentMetadata": {"Pages": 3},
        "Blocks": blocks,
        "DetectDocumentTextModelVersion": "1.0",
        "NextToken": "not-valid-for-a-split-result",
    }


class TextractOutputTests(unittest.TestCase):
    def test_split_payload_filters_renumbers_and_repairs_relationships(self) -> None:
        result = split_textract_payload(textract_payload(), 2, 3)

        self.assertEqual(result["DocumentMetadata"]["Pages"], 2)
        self.assertEqual({block["Page"] for block in result["Blocks"]}, {1, 2})
        self.assertNotIn("NextToken", result)
        retained_ids = {block["Id"] for block in result["Blocks"]}
        relationship_ids = {
            value
            for block in result["Blocks"]
            for relationship in block.get("Relationships", [])
            for value in relationship.get("Ids", [])
        }
        self.assertTrue(relationship_ids <= retained_ids)
        self.assertNotIn("page-1", retained_ids)

    def test_writer_creates_document_files_and_links_them_from_plan(self) -> None:
        candidates = [
            DocumentCandidate(1, 2, "invoice"),
            DocumentCandidate(3, 3, "receipt"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "packet_01.raw.json"
            source.write_text(json.dumps(textract_payload()), encoding="utf-8")

            outputs = write_split_textract_json(
                source, candidates, ["Invoice", "Receipt"], root / "out"
            )
            plan = write_split_plan(
                source,
                candidates,
                {"splitter": "test"},
                root / "out",
                document_outputs=outputs,
            )

            self.assertEqual(len(outputs), 2)
            self.assertEqual(outputs[0].parent.name, "packet_01")
            self.assertIn("document_001_invoice.pages_1-2", outputs[0].name)
            self.assertEqual(
                json.loads(outputs[0].read_text())["DocumentMetadata"]["Pages"], 2
            )
            plan_payload = json.loads(plan.read_text())
            self.assertEqual(
                [item["output_file"] for item in plan_payload["documents"]],
                [str(path) for path in outputs],
            )


if __name__ == "__main__":
    unittest.main()
