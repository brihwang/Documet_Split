from __future__ import annotations

import json
import os
import re
from typing import Any

from .detector import best_keyword_category, keyword_score
from .models import Classification, DocumentCandidate, PageText, Settings
from .utils import extract_date


LAST_AI_ERROR: str | None = None


def set_last_ai_error(message: str | None) -> None:
    global LAST_AI_ERROR
    LAST_AI_ERROR = message


def get_last_ai_error() -> str | None:
    return LAST_AI_ERROR


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
    keyword_hits = keyword_score(lowered, settings.categories[category].keywords)
    confidence = min(0.95, 0.45 + (keyword_hits * 0.15))
    if category == settings.default_category and keyword_hits == 0:
        confidence = 0.35

    doc_date = extract_date(text)
    reason = f"Rule-based match for {category} using {keyword_hits} keyword hit(s)."
    return Classification(
        document_type=category,
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
    content = complete_with_llm_gateway(build_ai_prompt(candidate, settings))
    if not content:
        return None
    try:
        payload = parse_json_object(content)
        return _classification_from_payload(payload, settings)
    except Exception:
        return None


def ai_split_is_configured() -> bool:
    provider = os.environ.get("AI_PROVIDER", "rules").strip().lower()
    return provider in ("llmgateway", "gateway")


def split_documents_with_ai(pages: list[PageText], settings: Settings) -> list[DocumentCandidate] | None:
    set_last_ai_error(None)
    provider = os.environ.get("AI_PROVIDER", "rules").strip().lower()
    if provider not in ("llmgateway", "gateway"):
        set_last_ai_error(f"AI_PROVIDER is {provider!r}, not 'llmgateway'.")
        return None

    content = complete_with_llm_gateway(build_split_prompt(pages, settings))
    if not content:
        return None
    try:
        payload = parse_json_object(content)
        candidates = candidates_from_split_payload(payload, pages)
        if not candidates:
            set_last_ai_error("AI split response did not contain valid contiguous page ranges.")
        return candidates
    except Exception as exc:
        set_last_ai_error(f"AI split response was not valid JSON: {exc}")
        return None


def complete_with_llm_gateway(prompt: str) -> str | None:
    api_key = os.environ.get("LLM_GATEWAY_API_KEY")
    if not api_key:
        set_last_ai_error("LLM_GATEWAY_API_KEY is not set.")
        return None

    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:
        set_last_ai_error(f"OpenAI-compatible client could not be imported: {exc}")
        return None

    base_url = os.environ.get("LLM_GATEWAY_BASE_URL", "https://api.llmgateway.io/v1")
    model = os.environ.get("LLM_GATEWAY_MODEL", "openai/gpt-4o-mini")
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        set_last_ai_error(f"LLM Gateway request failed: {exc}")
        return None


def build_ai_prompt(candidate: DocumentCandidate, settings: Settings) -> str:
    categories = ", ".join(settings.categories)
    return (
        "You are classifying one already-split document for an automated filing workflow. "
        "Choose exactly one document_type from the allowed list. Base the choice on the document's purpose, "
        "title, form labels, and category-specific fields; ignore names, addresses, sender-like headings, and incidental words. "
        "If a broad word appears inside another word, do not count it as evidence. "
        "Return only valid JSON with keys: document_type, date, confidence, suggested_filename, reason. "
        f"Allowed document_type values: {categories}. "
        "Use ISO date format for date when visible, otherwise use undated. Confidence must be a number from 0 to 1. "
        "Keep reason to one short sentence naming the decisive evidence.\n\n"
        f"{candidate.text[:12000]}"
    )


def build_split_prompt(pages: list[PageText], settings: Settings) -> str:
    categories = ", ".join(settings.categories)
    page_blocks = []
    for page in pages:
        page_blocks.append(f"<page number=\"{page.page_number}\">\n{page.text[:4000]}\n</page>")
    return (
        "You decide where a PDF should be split into separate documents for an automated filing workflow. "
        "The PDF may contain one document or multiple documents. "
        "Analyze each page as a possible start page, end page, or inner/continue page. "
        "Use content continuity, repeated headers or footers, formatting consistency, visible page numbering, logical completion cues, titles, form names, and subject matter changes. "
        "Pages belong together when they form a coherent continuous document, even if page text varies. "
        "Distinct documents of the same apparent type may be adjacent; split them when a fresh title, new identifier, new cover/title page, or completed prior document shows a new document begins. "
        "Do not split just because a person, company, address, date, or incidental keyword changes. "
        "Split only when there is clear evidence that a new distinct document begins. "
        "Every page must be assigned to exactly one document, ranges must be contiguous, and ranges must cover all pages from 1 through the final page. "
        "Return only valid JSON shaped exactly like: "
        "{\"documents\":[{\"start_page\":1,\"end_page\":1,\"document_type\":\"Invoice\",\"reason\":\"short evidence\"}]}. "
        "Use document_type only as a short label for the range; use Other when the type is not obvious. "
        f"Known document_type values: {categories}.\n\n"
        + "\n\n".join(page_blocks)
    )


def candidates_from_split_payload(payload: dict[str, Any], pages: list[PageText]) -> list[DocumentCandidate] | None:
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return None

    page_count = len(pages)
    current_page = 1
    candidates: list[DocumentCandidate] = []
    by_number = {page.page_number: page for page in pages}
    for item in sorted(documents, key=lambda value: int(value.get("start_page", 0)) if isinstance(value, dict) else 0):
        if not isinstance(item, dict):
            return None
        start_page = int(item.get("start_page", 0))
        end_page = int(item.get("end_page", 0))
        if start_page != current_page or end_page < start_page or end_page > page_count:
            return None
        text = "\n\n".join(by_number[number].text for number in range(start_page, end_page + 1)).strip()
        candidates.append(DocumentCandidate(start_page=start_page, end_page=end_page, text=text))
        current_page = end_page + 1

    if current_page != page_count + 1:
        return None
    return candidates


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
        date=str(payload.get("date") or "undated"),
        confidence=max(0.0, min(1.0, confidence)),
        reason=str(payload.get("reason") or "AI classification."),
        suggested_filename=payload.get("suggested_filename"),
        metadata={"classifier": "ai"},
    )
