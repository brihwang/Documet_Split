from __future__ import annotations

import json
import shutil
from pathlib import Path

from PyPDF2 import PdfReader, PdfWriter

from .classifier import classify_document
from .detector import detect_documents
from .extractor import extract_pdf_text
from .models import Classification, OutputDocument, Settings
from .utils import extract_year, sanitize_part, unique_path


def process_file(path: Path, output_root: Path, settings: Settings, errors_root: Path) -> list[OutputDocument]:
    if path.suffix.lower() != ".pdf":
        return route_non_pdf(path, output_root, settings, errors_root)

    pages = extract_pdf_text(path)
    candidates = detect_documents(pages, settings)
    if not candidates:
        raise ValueError(f"No pages could be read from {path}")

    reader = PdfReader(str(path))
    outputs: list[OutputDocument] = []
    for candidate in candidates:
        classification = classify_document(candidate, settings)
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


def route_non_pdf(path: Path, output_root: Path, settings: Settings, errors_root: Path) -> list[OutputDocument]:
    classification = Classification(
        document_type=settings.default_category,
        sender="Unknown Sender",
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
    sender = sanitize_part(classification.sender, "Unknown_Sender")
    doc_date = sanitize_part(classification.date, "undated")
    return {
        "type": doc_type,
        "sender": sender,
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
        "sender": classification.sender,
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
