from __future__ import annotations

import unittest
from pathlib import Path

from docusplit.aws_splitter import (
    PageClassification,
    candidates_from_classifications,
    split_with_bedrock,
)
from docusplit.config import load_settings
from docusplit.models import PageText


def bedrock_response(doc_type: str, boundary: str, confidence: float = 0.9) -> dict:
    return {
        "output": {
            "message": {
                "content": [
                    {
                        "text": (
                            f'{{"doc_type":"{doc_type}","document_boundary":"{boundary}",'
                            f'"confidence":{confidence},"reason":"test"}}'
                        )
                    }
                ]
            }
        },
        "usage": {"inputTokens": 100, "outputTokens": 20},
    }


class FakeBedrockClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = iter(responses)
        self.requests: list[dict] = []

    def converse(self, **kwargs) -> dict:
        self.requests.append(kwargs)
        return next(self.responses)


class AwsSplitterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("config.yaml"))

    def test_start_continue_tags_create_same_type_document_boundaries(self) -> None:
        pages = [
            PageText(1, "Invoice INV-1", "raw_json"),
            PageText(2, "Invoice INV-1 continued", "raw_json"),
            PageText(3, "Invoice INV-2", "raw_json"),
        ]
        client = FakeBedrockClient(
            [
                bedrock_response("Invoice", "start"),
                bedrock_response("Invoice", "continue"),
                bedrock_response("Invoice", "start"),
            ]
        )

        result = split_with_bedrock(
            pages, self.settings, client=client, multimodal=False, context_pages=1
        )

        self.assertEqual(
            [(item.start_page, item.end_page) for item in result.candidates],
            [(1, 2), (3, 3)],
        )
        self.assertEqual(result.input_tokens, 300)
        self.assertEqual(result.output_tokens, 60)

    def test_type_change_is_a_boundary_even_if_model_says_continue(self) -> None:
        pages = [PageText(1, "Invoice", "raw_json"), PageText(2, "Contract", "raw_json")]
        classifications = [
            PageClassification(1, "Invoice", "start", 0.9),
            PageClassification(2, "Contract", "continue", 0.9),
        ]

        candidates = candidates_from_classifications(pages, classifications)

        self.assertEqual(
            [(item.start_page, item.end_page) for item in candidates], [(1, 1), (2, 2)]
        )

    def test_invalid_class_is_retried_with_validation_feedback(self) -> None:
        pages = [PageText(1, "Invoice", "raw_json")]
        client = FakeBedrockClient(
            [
                bedrock_response("hallucinated_type", "start"),
                bedrock_response("Invoice", "start"),
            ]
        )

        result = split_with_bedrock(
            pages, self.settings, client=client, multimodal=False, max_retries=1
        )

        self.assertEqual(result.classifications[0].doc_type, "Invoice")
        self.assertEqual(len(client.requests), 2)
        retry_text = client.requests[1]["messages"][0]["content"][-1]["text"]
        self.assertIn("previous response was invalid", retry_text)


if __name__ == "__main__":
    unittest.main()
