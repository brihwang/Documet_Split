from __future__ import annotations

import json
import shutil
from pathlib import Path

from PyPDF2 import PdfReader, PdfWriter

from .classifier import classify_document, get_last_ai_error, split_documents_with_ai
from .detector import best_keyword_category
from .extractor import extract_pdf_text
from .models import Classification, DocumentCandidate, OutputDocument, PageText, Settings
from .utils import extract_year, sanitize_part, unique_path


def process_file(path: Path, output_root: Path, settings: Settings, errors_root: Path) -> list[OutputDocument]:
    if path.suffix.lower() != ".pdf":
        return route_non_pdf(path, output_root, settings, errors_root)

    pages = extract_pdf_text(path)
    if not pages:
        raise ValueError(f"No pages could be read from {path}")
    mixed_source_pdf = has_multiple_local_page_categories(pages, settings)
    candidates, ai_split_failed = choose_document_candidates(pages, settings, mixed_source_pdf)

    reader = PdfReader(str(path))
    outputs: list[OutputDocument] = []
    for candidate in candidates:
        if ai_split_failed:
            ai_error = get_last_ai_error() or "AI splitting was unavailable or failed."
            classification = Classification(
                document_type=settings.default_category,
                date="undated",
                confidence=0.0,
                reason=f"AI split is required for mixed-document PDFs. {ai_error}",
                metadata={"classifier": "rules", "ai_split": "failed_or_unavailable", "ai_error": ai_error},
            )
        else:
            classification = classify_document(candidate, settings, allow_ai=mixed_source_pdf)
        classification.metadata["mixed_source_pdf"] = mixed_source_pdf
        output_file = write_split_pdf(path, reader, candidate.start_page, candidate.end_page, classification, output_root, errors_root, settings)
        sidecar = write_sidecar(output_file, path, candidate.start_page, candidate.end_page, classification)
        outputs.append(
            OutputDocument(
                source_file=path,
                output_file=output_file,
                sidecar_file=sidecar,
                start_page=candidate.start_page,
                end_page=candidate.end_page,
                classification=classification,
                routed_to_review=classification.confidence < settings.min_confidence,
            )
        )
    return outputs


def choose_document_candidates(pages: list[PageText], settings: Settings, mixed_source_pdf: bool) -> tuple[list[DocumentCandidate], bool]:
    if mixed_source_pdf:
        ai_candidates = split_documents_with_ai(pages, settings)
        if ai_candidates:
            return ai_candidates, False
        return [candidate_from_pages(pages)], True
    return [candidate_from_pages(pages)], False


def candidate_from_pages(pages: list[PageText]) -> DocumentCandidate:
    return DocumentCandidate(
        start_page=pages[0].page_number,
        end_page=pages[-1].page_number,
        text="\n\n".join(page.text for page in pages).strip(),
    )


def has_multiple_local_page_categories(pages: list[PageText], settings: Settings) -> bool:
    local_types = {best_keyword_category(page.text.lower(), settings) or settings.default_category for page in pages}
    local_types.discard(settings.default_category)
    return len(local_types) > 1


def route_non_pdf(path: Path, output_root: Path, settings: Settings, errors_root: Path) -> list[OutputDocument]:
    classification = Classification(
        document_type=settings.default_category,
        date="undated",
        confidence=0.2,
        reason="Non-PDF files are not split in this version and need review.",
        metadata={"classifier": "rules", "unsupported_file_type": path.suffix},
    )
    target_dir = errors_root / settings.review_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(target_dir / sanitize_part(path.name, "unsupported_file"))
    shutil.copy2(path, target)
    sidecar = write_sidecar(target, path, 1, 1, classification)
    return [
        OutputDocument(
            source_file=path,
            output_file=target,
            sidecar_file=sidecar,
            start_page=1,
            end_page=1,
            classification=classification,
            routed_to_review=True,
        )
    ]


def write_split_pdf(
    source: Path,
    reader: PdfReader,
    start_page: int,
    end_page: int,
    classification: Classification,
    output_root: Path,
    errors_root: Path,
    settings: Settings,
) -> Path:
    writer = PdfWriter()
    for page_index in range(start_page - 1, end_page):
        writer.add_page(reader.pages[page_index])

    routed_to_review = classification.confidence < settings.min_confidence
    target_dir = errors_root / settings.review_folder if routed_to_review else output_root / folder_for(classification, settings)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(target_dir / filename_for(classification, settings))
    with target.open("wb") as handle:
        writer.write(handle)
    return target


def filename_for(classification: Classification, settings: Settings) -> str:
    if classification.suggested_filename:
        name = sanitize_part(classification.suggested_filename)
        return name if name.lower().endswith(".pdf") else f"{name}.pdf"

    values = template_values(classification)
    raw = settings.filename_template.format(**values)
    if not raw.lower().endswith(".pdf"):
        raw = f"{raw}.pdf"
    return sanitize_part(raw, "document.pdf")


def folder_for(classification: Classification, settings: Settings) -> Path:
    rule = settings.categories.get(classification.document_type) or settings.categories[settings.default_category]
    values = template_values(classification)
    parts = [sanitize_part(part, "unknown") for part in rule.folder.format(**values).split("/")]
    return Path(*parts)


def template_values(classification: Classification) -> dict[str, str]:
    doc_type = sanitize_part(classification.document_type, "Other")
    doc_date = sanitize_part(classification.date, "undated")
    return {
        "type": doc_type,
        "date": doc_date,
        "year": extract_year(classification.date),
    }


def write_sidecar(output_file: Path, source: Path, start_page: int, end_page: int, classification: Classification) -> Path:
    sidecar = output_file.with_suffix(output_file.suffix + ".json")
    payload = {
        "source_file": str(source),
        "output_file": str(output_file),
        "page_range": [start_page, end_page],
        "document_type": classification.document_type,
        "date": classification.date,
        "confidence": classification.confidence,
        "reason": classification.reason,
        "metadata": classification.metadata,
    }
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return sidecar


def move_to_processed(path: Path, processed_root: Path) -> Path:
    processed_root.mkdir(parents=True, exist_ok=True)
    target = unique_path(processed_root / path.name)
    shutil.move(str(path), str(target))
    return target
