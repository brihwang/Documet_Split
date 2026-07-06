from __future__ import annotations

import json
import os
import re
from typing import Any

from .detector import best_keyword_category
from .models import Classification, DocumentCandidate, Settings
from .utils import extract_date, guess_sender


def classify_document(candidate: DocumentCandidate, settings: Settings, allow_ai: bool = False) -> Classification:
    rule_result = classify_with_rules(candidate, settings)
    if not should_use_ai(rule_result, settings, allow_ai):
        return rule_result

    ai_result = classify_with_ai(candidate, settings)
    if ai_result:
        return ai_result
    return rule_result


def should_use_ai(classification: Classification, settings: Settings, allow_ai: bool) -> bool:
    return allow_ai


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
    provider = os.environ.get("AI_PROVIDER", "rules").strip().lower()
    if provider in ("", "rules", "none", "off"):
        return None
    if provider in ("llmgateway", "gateway"):
        return classify_with_llm_gateway(candidate, settings)
    return None


def classify_with_llm_gateway(candidate: DocumentCandidate, settings: Settings) -> Classification | None:
    api_key = os.environ.get("LLM_GATEWAY_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return None

    base_url = os.environ.get("LLM_GATEWAY_BASE_URL", "https://api.llmgateway.io/v1")
    model = os.environ.get("LLM_GATEWAY_MODEL", "openai/gpt-4o-mini")
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": build_ai_prompt(candidate, settings)}],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        payload = parse_json_object(content)
        return _classification_from_payload(payload, settings)
    except Exception:
        return None


def build_ai_prompt(candidate: DocumentCandidate, settings: Settings) -> str:
    categories = ", ".join(settings.categories)
    return (
        "You classify documents for an automated document routing system. "
        "Return only valid JSON with keys: document_type, sender, date, confidence, "
        "suggested_filename, reason. "
        f"Allowed document_type values: {categories}. "
        "Use ISO date format when possible. Confidence must be a number from 0 to 1.\n\n"
        f"{candidate.text[:12000]}"
    )


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


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
