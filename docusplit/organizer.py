from __future__ import annotations

import json
import shutil
from pathlib import Path

from PyPDF2 import PdfReader, PdfWriter

from .classifier import ai_split_is_configured, get_last_ai_error, get_last_ai_model, split_documents_with_ai
from .detector import detect_documents
from .extractor import extract_pdf_text
from .models import DocumentCandidate, OutputDocument, PageText, Settings
from .utils import sanitize_part, unique_path


def process_file(
    path: Path,
    output_root: Path,
    settings: Settings,
    errors_root: Path,
    use_ai: bool = True,
) -> list[OutputDocument]:
    if path.suffix.lower() != ".pdf":
        return route_non_pdf(path, output_root, settings, errors_root)

    pages = extract_pdf_text(path)
    if not pages:
        raise ValueError(f"No pages could be read from {path}")
    candidates, split_metadata = choose_document_candidates(pages, settings, use_ai=use_ai)

    reader = PdfReader(str(path))
    outputs: list[OutputDocument] = []
    for candidate in candidates:
        output_file = write_split_pdf(path, reader, candidate.start_page, candidate.end_page, output_root)
        sidecar = write_sidecar(output_file, path, candidate.start_page, candidate.end_page, split_metadata)
        outputs.append(
            OutputDocument(
                source_file=path,
                output_file=output_file,
                sidecar_file=sidecar,
                start_page=candidate.start_page,
                end_page=candidate.end_page,
                routed_to_review=False,
            )
        )
    return outputs


def choose_document_candidates(
    pages: list[PageText],
    settings: Settings,
    use_ai: bool = True,
) -> tuple[list[DocumentCandidate], dict[str, object]]:
    if len(pages) == 1:
        return [candidate_from_pages(pages)], {"splitter": "single_page", "document_count": 1}

    if use_ai and ai_split_is_configured():
        ai_candidates = split_documents_with_ai(pages)
        if ai_candidates:
            metadata = {"splitter": "ai", "document_count": len(ai_candidates)}
            ai_model = get_last_ai_model()
            if ai_model:
                metadata["ai_model"] = ai_model
            return ai_candidates, metadata
        ai_error = get_last_ai_error() or "AI splitting was unavailable or failed."
        candidates = detect_documents(pages, settings) or [candidate_from_pages(pages)]
        return candidates, {"splitter": "local_page_patterns", "document_count": len(candidates), "ai_error": ai_error}

    candidates = detect_documents(pages, settings) or [candidate_from_pages(pages)]
    splitter = "local_page_patterns" if len(candidates) > 1 else "local_single_document"
    return candidates, {"splitter": splitter, "document_count": len(candidates)}


def candidate_from_pages(pages: list[PageText]) -> DocumentCandidate:
    return DocumentCandidate(
        start_page=pages[0].page_number,
        end_page=pages[-1].page_number,
        text="\n\n".join(page.text for page in pages).strip(),
    )


def route_non_pdf(path: Path, output_root: Path, settings: Settings, errors_root: Path) -> list[OutputDocument]:
    target_dir = errors_root / settings.review_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(target_dir / sanitize_part(path.name, "unsupported_file"))
    shutil.copy2(path, target)
    sidecar = write_sidecar(
        target,
        path,
        1,
        1,
        {"unsupported_file_type": path.suffix, "reason": "Non-PDF files are not split in this version."},
    )
    return [
        OutputDocument(
            source_file=path,
            output_file=target,
            sidecar_file=sidecar,
            start_page=1,
            end_page=1,
            routed_to_review=True,
        )
    ]


def write_split_pdf(
    source: Path,
    reader: PdfReader,
    start_page: int,
    end_page: int,
    output_root: Path,
) -> Path:
    writer = PdfWriter()
    for page_index in range(start_page - 1, end_page):
        writer.add_page(reader.pages[page_index])

    output_root.mkdir(parents=True, exist_ok=True)
    target = unique_path(output_root / source.name)
    with target.open("wb") as handle:
        writer.write(handle)
    return target


def write_sidecar(
    output_file: Path,
    source: Path,
    start_page: int,
    end_page: int,
    metadata: dict[str, object],
) -> Path:
    sidecar = output_file.with_suffix(output_file.suffix + ".json")
    payload = {
        "source_file": str(source),
        "output_file": str(output_file),
        "page_range": [start_page, end_page],
        "metadata": metadata,
    }
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return sidecar


def move_to_processed(path: Path, processed_root: Path) -> Path:
    processed_root.mkdir(parents=True, exist_ok=True)
    target = unique_path(processed_root / path.name)
    shutil.move(str(path), str(target))
    return target
