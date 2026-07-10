from __future__ import annotations

import json
import os
import re
from typing import Any

from .models import DocumentCandidate, PageText


LAST_AI_ERROR: str | None = None
LAST_AI_MODEL: str | None = None
LAST_AI_SPLIT_METADATA: dict[str, object] = {}
DEFAULT_MIN_AI_SPLIT_CONFIDENCE = 0.7
DEFAULT_MAX_AI_OVER_SPLIT_RISK = 0.35
DEFAULT_DENSE_SPLIT_MIN_CONFIDENCE = 0.92


def set_last_ai_error(message: str | None) -> None:
    global LAST_AI_ERROR
    LAST_AI_ERROR = message


def set_last_ai_model(model: str | None) -> None:
    global LAST_AI_MODEL
    LAST_AI_MODEL = model


def set_last_ai_split_metadata(metadata: dict[str, object] | None) -> None:
    global LAST_AI_SPLIT_METADATA
    LAST_AI_SPLIT_METADATA = metadata or {}


def get_last_ai_error() -> str | None:
    return LAST_AI_ERROR


def get_last_ai_model() -> str | None:
    return LAST_AI_MODEL


def get_last_ai_split_metadata() -> dict[str, object]:
    return dict(LAST_AI_SPLIT_METADATA)


def ai_split_is_configured() -> bool:
    provider = os.environ.get("AI_PROVIDER", "rules").strip().lower()
    return provider in ("llmgateway", "gateway")


def split_documents_with_ai(pages: list[PageText]) -> list[DocumentCandidate] | None:
    set_last_ai_error(None)
    set_last_ai_model(None)
    set_last_ai_split_metadata(None)
    provider = os.environ.get("AI_PROVIDER", "rules").strip().lower()
    if provider not in ("llmgateway", "gateway"):
        set_last_ai_error(f"AI_PROVIDER is {provider!r}, not 'llmgateway'.")
        return None

    errors = []
    prompt = build_split_prompt(pages)
    for model in llm_gateway_models():
        content = complete_with_llm_gateway(prompt, model=model)
        if not content:
            errors.append(get_last_ai_error() or f"{model}: no response")
            continue
        try:
            payload = parse_json_object(content)
            candidates = candidates_from_split_payload(payload, pages)
            if candidates:
                confidence_metadata = confidence_metadata_from_payload(payload)
                if confidence_metadata is None:
                    errors.append(f"{model}: AI split response did not include confidence ratings.")
                    continue
                rejection_reason = ai_split_rejection_reason(candidates, pages, confidence_metadata)
                if rejection_reason:
                    errors.append(f"{model}: {rejection_reason}")
                    continue
                set_last_ai_model(model)
                set_last_ai_split_metadata({"model": model, **confidence_metadata})
                set_last_ai_error(None)
                return candidates
            errors.append(f"{model}: AI split response did not contain valid contiguous page ranges.")
        except Exception as exc:
            errors.append(f"{model}: AI split response was not valid JSON: {exc}")

    set_last_ai_error(" | ".join(errors) if errors else "No LLM Gateway models were configured.")
    return None


def complete_with_llm_gateway(prompt: str, model: str | None = None) -> str | None:
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
    model = model or os.environ.get("LLM_GATEWAY_MODEL", "openai/gpt-4o-mini")
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        set_last_ai_error(f"{model}: LLM Gateway request failed: {exc}")
        return None


def llm_gateway_models() -> list[str]:
    primary = os.environ.get("LLM_GATEWAY_MODEL", "openai/gpt-4o-mini")
    fallbacks = os.environ.get("LLM_GATEWAY_FALLBACK_MODELS", "")
    models = [primary, *fallbacks.split(",")]
    cleaned = []
    for model in models:
        model = model.strip()
        if model and model not in cleaned:
            cleaned.append(model)
    return cleaned


def build_split_prompt(pages: list[PageText]) -> str:
    page_blocks = []
    for page in pages:
        page_blocks.append(f"<page number=\"{page.page_number}\">\n{page.text[:4000]}\n</page>")
    source_description = "Textract-style raw JSON LINE/WORD text" if any(page.source == "raw_json" for page in pages) else "PDF page text"
    return (
        f"You decide where a document packet should be split into separate documents for an automated filing workflow. The input below is {source_description}. "
        "It will come from a raw JSON text extracted from each page; do not expect visual layout beyond the text, page order, and repeated line cues shown here. "
        "The packet may contain one document or multiple documents. "
        "When policy-code preprocessing has already handled coded pages, you may only receive a contiguous run of pages without policy codes. "
        "Analyze each page as a possible start page, end page, or inner/continue page. "
        "Use document category cues, titles, headings, field labels, repeated headers or footers, visible page numbering, logical completion cues, form names, and subject matter changes. "
        "Pages belong together when they form a coherent continuous document or the same uncoded document category, even if page text varies. "
        "Do not split just because a person, company, address, date, or incidental keyword changes. "
        "Split only when there is clear evidence that a new distinct document begins. "
        "Rate your confidence from 0.0 to 1.0 for each proposed document and for the full split plan. "
        "Also rate over_split_risk from 0.0 to 1.0, where higher means the plan may be splitting pages that should stay together. "
        "Use lower confidence when adjacent pages might be continuations of the same document. "
        "Every page must be assigned to exactly one document, ranges must be contiguous, and ranges must cover all pages from 1 through the final page. "
        "Return only valid JSON shaped exactly like: "
        "{\"overall_confidence\":0.82,\"over_split_risk\":0.18,\"documents\":[{\"start_page\":1,\"end_page\":1,\"confidence\":0.82,\"reason\":\"short evidence\"}]}.\n\n"
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


def confidence_metadata_from_payload(payload: dict[str, Any]) -> dict[str, object] | None:
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return None

    document_confidences = [bounded_float(item.get("confidence")) for item in documents if isinstance(item, dict)]
    if not document_confidences or any(value is None for value in document_confidences):
        return None

    overall_confidence = bounded_float(payload.get("overall_confidence"))
    over_split_risk = bounded_float(payload.get("over_split_risk"))
    if overall_confidence is None or over_split_risk is None:
        return None

    confidences = [overall_confidence, *(value for value in document_confidences if value is not None)]
    return {
        "confidence": min(confidences),
        "overall_confidence": overall_confidence,
        "document_confidences": document_confidences,
        "over_split_risk": over_split_risk,
        "min_confidence_threshold": min_ai_split_confidence(),
        "max_over_split_risk": max_ai_over_split_risk(),
    }


def bounded_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0.0 or number > 1.0:
        return None
    return number


def ai_split_rejection_reason(
    candidates: list[DocumentCandidate],
    pages: list[PageText],
    metadata: dict[str, object],
) -> str | None:
    confidence = float(metadata["confidence"])
    over_split_risk = float(metadata["over_split_risk"])
    if confidence < min_ai_split_confidence():
        return f"AI split confidence {confidence:.2f} is below threshold {min_ai_split_confidence():.2f}."
    if over_split_risk > max_ai_over_split_risk():
        return f"AI over-split risk {over_split_risk:.2f} is above threshold {max_ai_over_split_risk():.2f}."
    if dense_single_page_split(candidates, pages) and confidence < dense_split_min_confidence():
        return (
            f"AI split would make every page a separate document at confidence {confidence:.2f}; "
            f"dense split threshold is {dense_split_min_confidence():.2f}."
        )
    return None


def dense_single_page_split(candidates: list[DocumentCandidate], pages: list[PageText]) -> bool:
    return len(pages) >= 3 and len(candidates) == len(pages) and all(
        candidate.start_page == candidate.end_page for candidate in candidates
    )


def min_ai_split_confidence() -> float:
    return env_float("AI_MIN_SPLIT_CONFIDENCE", DEFAULT_MIN_AI_SPLIT_CONFIDENCE)


def max_ai_over_split_risk() -> float:
    return env_float("AI_MAX_OVER_SPLIT_RISK", DEFAULT_MAX_AI_OVER_SPLIT_RISK)


def dense_split_min_confidence() -> float:
    return env_float("AI_DENSE_SPLIT_MIN_CONFIDENCE", DEFAULT_DENSE_SPLIT_MIN_CONFIDENCE)


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))
