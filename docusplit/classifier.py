from __future__ import annotations

import json
import os
from typing import Any

from .detector import best_keyword_category
from .models import Classification, DocumentCandidate, Settings
from .utils import extract_date, guess_sender


def classify_document(candidate: DocumentCandidate, settings: Settings) -> Classification:
    ai_result = classify_with_ai(candidate, settings)
    if ai_result:
        return ai_result
    return classify_with_rules(candidate, settings)


def classify_with_rules(candidate: DocumentCandidate, settings: Settings) -> Classification:
    text = candidate.text
    lowered = text.lower()
    category = best_keyword_category(lowered, settings) or settings.default_category
    keyword_hits = sum(1 for keyword in settings.categories[category].keywords if keyword in lowered)
    confidence = min(0.95, 0.45 + (keyword_hits * 0.15))
    if category == settings.default_category and keyword_hits == 0:
        confidence = 0.35

    doc_date = extract_date(text)
    sender = guess_sender(text)
    reason = f"Rule-based match for {category} using {keyword_hits} keyword hit(s)."
    return Classification(
        document_type=category,
        sender=sender,
        date=doc_date,
        confidence=confidence,
        reason=reason,
        metadata={"classifier": "rules", "keyword_hits": keyword_hits},
    )


def classify_with_ai(candidate: DocumentCandidate, settings: Settings) -> Classification | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return None

    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    categories = ", ".join(settings.categories)
    prompt = (
        "Classify this document and return only JSON with keys: "
        "document_type, sender, date, confidence, suggested_filename, reason. "
        f"Allowed document_type values: {categories}. Use ISO date if possible.\n\n"
        f"{candidate.text[:12000]}"
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            input=prompt,
            temperature=0,
        )
        payload = json.loads(response.output_text)
        return _classification_from_payload(payload, settings)
    except Exception:
        return None


def _classification_from_payload(payload: dict[str, Any], settings: Settings) -> Classification:
    doc_type = str(payload.get("document_type") or settings.default_category)
    if doc_type not in settings.categories:
        doc_type = settings.default_category
    confidence = float(payload.get("confidence") or 0.0)
    return Classification(
        document_type=doc_type,
        sender=str(payload.get("sender") or "Unknown Sender"),
        date=str(payload.get("date") or "undated"),
        confidence=max(0.0, min(1.0, confidence)),
        reason=str(payload.get("reason") or "AI classification."),
        suggested_filename=payload.get("suggested_filename"),
        metadata={"classifier": "ai"},
    )
