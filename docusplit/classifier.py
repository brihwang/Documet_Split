from __future__ import annotations

import json
import os
import re
from typing import Any

from .models import DocumentCandidate, PageText


LAST_AI_ERROR: str | None = None
LAST_AI_MODEL: str | None = None


def set_last_ai_error(message: str | None) -> None:
    global LAST_AI_ERROR
    LAST_AI_ERROR = message


def set_last_ai_model(model: str | None) -> None:
    global LAST_AI_MODEL
    LAST_AI_MODEL = model


def get_last_ai_error() -> str | None:
    return LAST_AI_ERROR


def get_last_ai_model() -> str | None:
    return LAST_AI_MODEL


def ai_split_is_configured() -> bool:
    provider = os.environ.get("AI_PROVIDER", "rules").strip().lower()
    return provider in ("llmgateway", "gateway")


def split_documents_with_ai(pages: list[PageText]) -> list[DocumentCandidate] | None:
    set_last_ai_error(None)
    set_last_ai_model(None)
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
                set_last_ai_model(model)
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
        "{\"documents\":[{\"start_page\":1,\"end_page\":1,\"reason\":\"short evidence\"}]}.\n\n"
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
