from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .classifier import parse_json_object
from .models import DocumentCandidate, PageText, Settings


DEFAULT_BEDROCK_MODEL = "us.amazon.nova-pro-v1:0"


@dataclass(frozen=True)
class PageClassification:
    page_number: int
    doc_type: str
    document_boundary: str
    confidence: float
    reason: str = ""


@dataclass(frozen=True)
class AwsSplitResult:
    candidates: list[DocumentCandidate]
    classifications: list[PageClassification]
    input_tokens: int
    output_tokens: int
    model: str
    multimodal: bool


def split_with_bedrock(
    pages: list[PageText],
    settings: Settings,
    *,
    source_pdf: Path | None = None,
    model: str = DEFAULT_BEDROCK_MODEL,
    region: str | None = None,
    profile: str | None = None,
    context_pages: int = 1,
    multimodal: bool = True,
    max_retries: int = 2,
    client: Any | None = None,
) -> AwsSplitResult:
    """Classify pages with Bedrock and convert start/continue tags into ranges."""
    if not pages:
        raise ValueError("At least one page is required.")
    if context_pages < 0:
        raise ValueError("context_pages must be zero or greater.")

    bedrock = client or create_bedrock_client(region=region, profile=profile)
    images: dict[int, bytes] = {}
    used_multimodal = bool(multimodal and source_pdf)
    if used_multimodal:
        images = render_pdf_pages(source_pdf)
        used_multimodal = bool(images)

    classifications: list[PageClassification] = []
    input_tokens = 0
    output_tokens = 0
    allowed_classes = set(settings.categories)
    for index, page in enumerate(pages):
        response, classification = classify_page(
            bedrock,
            pages,
            index,
            settings,
            images=images if used_multimodal else {},
            model=model,
            context_pages=context_pages,
            max_retries=max_retries,
        )
        if classification.doc_type not in allowed_classes:
            raise ValueError(
                f"Bedrock returned invalid class {classification.doc_type!r} for page "
                f"{page.page_number}; expected one of {sorted(allowed_classes)}."
            )
        classifications.append(classification)
        usage = response.get("usage") or {}
        input_tokens += int(usage.get("inputTokens", 0) or 0)
        output_tokens += int(usage.get("outputTokens", 0) or 0)

    classifications[0] = PageClassification(
        page_number=classifications[0].page_number,
        doc_type=classifications[0].doc_type,
        document_boundary="start",
        confidence=classifications[0].confidence,
        reason=classifications[0].reason,
    )
    candidates = candidates_from_classifications(pages, classifications)
    return AwsSplitResult(
        candidates=candidates,
        classifications=classifications,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        multimodal=used_multimodal,
    )


def create_bedrock_client(*, region: str | None, profile: str | None) -> Any:
    try:
        import boto3  # type: ignore
        from botocore.config import Config  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "AWS support requires boto3. Install it with: python -m pip install -e '.[aws]'"
        ) from exc

    config = Config(read_timeout=3600, connect_timeout=30, retries={"max_attempts": 3, "mode": "standard"})
    if profile:
        return boto3.Session(profile_name=profile, region_name=region).client(
            "bedrock-runtime", config=config
        )
    return boto3.client("bedrock-runtime", region_name=region, config=config)


def classify_page(
    client: Any,
    pages: list[PageText],
    target_index: int,
    settings: Settings,
    *,
    images: dict[int, bytes],
    model: str,
    context_pages: int,
    max_retries: int,
) -> tuple[dict[str, Any], PageClassification]:
    content = build_page_content(pages, target_index, settings, images, context_pages)
    last_error = ""
    response: dict[str, Any] = {}
    for attempt in range(max_retries + 1):
        request_content = list(content)
        if attempt:
            request_content.append(
                {
                    "text": (
                        "Your previous response was invalid. Return only the required JSON object. "
                        f"Error: {last_error}"
                    )
                }
            )
        response = client.converse(
            modelId=model,
            messages=[{"role": "user", "content": request_content}],
            inferenceConfig={"temperature": 0.0, "maxTokens": 500},
        )
        try:
            text = response_text(response)
            payload = parse_json_object(text)
            return response, validate_page_classification(
                payload, pages[target_index].page_number, set(settings.categories)
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
    raise ValueError(
        f"Bedrock returned an invalid classification for page "
        f"{pages[target_index].page_number} after {max_retries + 1} attempts: {last_error}"
    )


def build_page_content(
    pages: list[PageText],
    target_index: int,
    settings: Settings,
    images: dict[int, bytes],
    context_pages: int,
) -> list[dict[str, Any]]:
    lower = max(0, target_index - context_pages)
    upper = min(len(pages), target_index + context_pages + 1)
    target = pages[target_index]
    class_descriptions = "\n".join(
        (
            f'<class name="{name}"><description>'
            f"{', '.join(rule.keywords) or 'Other or unknown document type'}"
            f"</description></class>"
        )
        for name, rule in settings.categories.items()
    )
    prompt = (
        "You perform page-level document classification and sequence segmentation. "
        "Decide whether the TARGET page begins a new logical document or continues the prior one. "
        "Use type, content continuity, repeated headers/footers, page numbering, identifiers, title "
        "pages, completed signatures/totals, and layout. A new document of the same type must still "
        'be tagged "start". Accessory, instruction, continuation, and blank pages normally continue '
        "the document they belong to. Context pages are evidence only; classify TARGET PAGE alone.\n"
        f"<document-types>\n{class_descriptions}\n</document-types>\n"
        'Return only JSON: {"doc_type":"one exact class name","document_boundary":"start|continue",'
        '"confidence":0.0,"reason":"brief evidence"}.\n'
    )
    content: list[dict[str, Any]] = [{"text": prompt}]
    for index in range(lower, upper):
        page = pages[index]
        role = "TARGET PAGE" if index == target_index else (
            "CONTEXT BEFORE" if index < target_index else "CONTEXT AFTER"
        )
        content.append(
            {
                "text": (
                    f"<{role.lower().replace(' ', '-')} number=\"{page.page_number}\">\n"
                    f"{page.text[:5000]}\n"
                    f"</{role.lower().replace(' ', '-')}>"
                )
            }
        )
        image = images.get(page.page_number)
        if image:
            content.append({"image": {"format": "png", "source": {"bytes": image}}})
    if target.page_number == 1:
        content.append({"text": "The first packet page must have document_boundary=start."})
    return content


def response_text(response: dict[str, Any]) -> str:
    blocks = response["output"]["message"]["content"]
    text = "\n".join(str(block["text"]) for block in blocks if "text" in block)
    if not text:
        raise ValueError("response contained no text")
    return text


def validate_page_classification(
    payload: dict[str, Any], page_number: int, allowed_classes: set[str]
) -> PageClassification:
    doc_type = str(payload.get("doc_type", "")).strip()
    boundary = str(payload.get("document_boundary", "")).strip().lower()
    if doc_type not in allowed_classes:
        raise ValueError(f"doc_type must be one of {sorted(allowed_classes)}")
    if boundary not in {"start", "continue"}:
        raise ValueError("document_boundary must be 'start' or 'continue'")
    try:
        confidence = float(payload["confidence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("confidence must be a number from 0 to 1") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be a number from 0 to 1")
    return PageClassification(
        page_number=page_number,
        doc_type=doc_type,
        document_boundary=boundary,
        confidence=confidence,
        reason=str(payload.get("reason", "")).strip(),
    )


def candidates_from_classifications(
    pages: list[PageText], classifications: list[PageClassification]
) -> list[DocumentCandidate]:
    if len(pages) != len(classifications):
        raise ValueError("Every page must have exactly one classification.")
    starts = [0]
    for index in range(1, len(classifications)):
        current = classifications[index]
        previous = classifications[index - 1]
        if current.document_boundary == "start" or current.doc_type != previous.doc_type:
            starts.append(index)

    candidates: list[DocumentCandidate] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] - 1 if position + 1 < len(starts) else len(pages) - 1
        candidates.append(
            DocumentCandidate(
                start_page=pages[start].page_number,
                end_page=pages[end].page_number,
                text="\n\n".join(page.text for page in pages[start : end + 1]).strip(),
            )
        )
    return candidates


def render_pdf_pages(path: Path) -> dict[int, bytes]:
    try:
        import fitz  # type: ignore
    except Exception:
        return {}

    images: dict[int, bytes] = {}
    with fitz.open(path) as document:
        for index, page in enumerate(document):
            # Converse limits an individual embedded image to 3.75 MB. Reduce
            # resolution until the PNG fits instead of failing the whole packet.
            for scale in (1.5, 1.2, 0.9, 0.7):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                data = pixmap.tobytes("png")
                if len(data) <= 3_500_000:
                    images[index + 1] = data
                    break
    return images
