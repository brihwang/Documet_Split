from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

from PyPDF2 import PdfReader, PdfWriter

from .classifier import ai_split_is_configured, get_last_ai_error, get_last_ai_model, split_documents_with_ai
from .detector import detect_documents
from .extractor import extract_pdf_text
from .models import DocumentCandidate, OutputDocument, PageText, Settings
from .policy_codes import PolicyCodeMatcher, extract_raw_pages, find_raw_json_for_pdf, split_with_policy_codes
from .utils import sanitize_part, unique_path


def process_file(
    path: Path,
    output_root: Path,
    settings: Settings,
    errors_root: Path,
    use_ai: bool = True,
    raw_dir: Path | None = None,
    form_lookup: Path | None = None,
) -> list[OutputDocument]:
    if path.suffix.lower() == ".json":
        return process_raw_json(path, output_root, settings, use_ai=use_ai, form_lookup=form_lookup)

    if path.suffix.lower() != ".pdf":
        return route_non_pdf(path, output_root, settings, errors_root)

    pages = extract_pdf_text(path)
    if not pages:
        raise ValueError(f"No pages could be read from {path}")
    raw_pages = None
    raw_path = find_raw_json_for_pdf(path, raw_dir)
    if raw_path is not None:
        raw_pages = extract_raw_pages(raw_path)
    candidates, split_metadata = choose_document_candidates(
        pages,
        settings,
        use_ai=use_ai,
        raw_pages=raw_pages,
        form_lookup=form_lookup,
    )
    if raw_path is not None:
        split_metadata["raw_json"] = str(raw_path)

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


def process_raw_json(
    path: Path,
    output_root: Path,
    settings: Settings,
    use_ai: bool = True,
    form_lookup: Path | None = None,
) -> list[OutputDocument]:
    pages = extract_raw_pages(path)
    if not pages:
        raise ValueError(f"No pages could be read from {path}")

    candidates, split_metadata = choose_document_candidates(
        pages,
        settings,
        use_ai=use_ai,
        raw_pages=pages,
        form_lookup=form_lookup,
    )
    split_metadata["raw_json"] = str(path)
    split_metadata["output_type"] = "split_plan"
    plan_file = write_split_plan(path, candidates, split_metadata, output_root)

    return [
        OutputDocument(
            source_file=path,
            output_file=plan_file,
            sidecar_file=plan_file,
            start_page=candidate.start_page,
            end_page=candidate.end_page,
            routed_to_review=False,
        )
        for candidate in candidates
    ]


def choose_document_candidates(
    pages: list[PageText],
    settings: Settings,
    use_ai: bool = True,
    raw_pages: list[PageText] | None = None,
    form_lookup: Path | None = None,
) -> tuple[list[DocumentCandidate], dict[str, object]]:
    if len(pages) == 1:
        return [candidate_from_pages(pages)], {"splitter": "single_page", "document_count": 1}

    if raw_pages and form_lookup and form_lookup.exists():
        policy_result = split_with_policy_codes(
            pages,
            raw_pages,
            PolicyCodeMatcher.from_lookup_file(form_lookup),
            settings,
            use_ai=use_ai,
        )
        if policy_result is not None:
            return policy_result

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


def write_split_plan(
    source: Path,
    candidates: list[DocumentCandidate],
    metadata: dict[str, object],
    output_root: Path,
    document_outputs: list[Path] | None = None,
) -> Path:
    if document_outputs is not None and len(document_outputs) != len(candidates):
        raise ValueError("document_outputs must match the number of candidates")
    output_root.mkdir(parents=True, exist_ok=True)
    target = unique_path(output_root / f"{source.stem}.split_plan.json")
    payload = {
        "source_file": str(source),
        "output_file": str(target),
        "metadata": metadata,
        "documents": [
            {
                "document_index": index,
                "start_page": candidate.start_page,
                "end_page": candidate.end_page,
                "page_range": [candidate.start_page, candidate.end_page],
                **(
                    {"output_file": str(document_outputs[index - 1])}
                    if document_outputs is not None
                    else {}
                ),
            }
            for index, candidate in enumerate(candidates, start=1)
        ],
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def write_split_textract_json(
    source: Path,
    candidates: list[DocumentCandidate],
    document_types: list[str],
    output_root: Path,
) -> list[Path]:
    """Write one self-contained Textract-style JSON response per candidate."""
    if len(document_types) != len(candidates):
        raise ValueError("document_types must match the number of candidates")

    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("Blocks"), list):
        raise ValueError(f"Raw JSON must contain a Blocks list: {source}")

    packet_name = textract_packet_name(source)
    packet_dir = output_root / packet_name
    packet_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for index, (candidate, document_type) in enumerate(
        zip(candidates, document_types, strict=True), start=1
    ):
        split_payload = split_textract_payload(
            payload, candidate.start_page, candidate.end_page
        )
        category = sanitize_part(document_type.lower(), "other")
        filename = (
            f"document_{index:03d}_{category}."
            f"pages_{candidate.start_page}-{candidate.end_page}.json"
        )
        target = unique_path(packet_dir / filename)
        target.write_text(
            json.dumps(split_payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        outputs.append(target)
    return outputs


def split_textract_payload(
    payload: dict[str, Any], start_page: int, end_page: int
) -> dict[str, Any]:
    """Select and locally renumber a page range from a Textract response."""
    if start_page < 1 or end_page < start_page:
        raise ValueError("Invalid Textract page range")
    blocks = payload.get("Blocks")
    if not isinstance(blocks, list):
        raise ValueError("Textract payload must contain a Blocks list")

    selected: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        page = block.get("Page")
        if isinstance(page, int) and start_page <= page <= end_page:
            item = copy.deepcopy(block)
            item["Page"] = page - start_page + 1
            selected.append(item)

    retained_ids = {
        block["Id"]
        for block in selected
        if isinstance(block.get("Id"), str)
    }
    for block in selected:
        relationships = block.get("Relationships")
        if not isinstance(relationships, list):
            continue
        cleaned_relationships: list[dict[str, Any]] = []
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            item = copy.deepcopy(relationship)
            ids = item.get("Ids")
            if isinstance(ids, list):
                item["Ids"] = [
                    value
                    for value in ids
                    if isinstance(value, str) and value in retained_ids
                ]
                if not item["Ids"]:
                    continue
            cleaned_relationships.append(item)
        if cleaned_relationships:
            block["Relationships"] = cleaned_relationships
        else:
            block.pop("Relationships", None)

    result = copy.deepcopy(payload)
    result["Blocks"] = selected
    metadata = result.get("DocumentMetadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["Pages"] = end_page - start_page + 1
    result["DocumentMetadata"] = metadata
    result.pop("NextToken", None)
    return result


def textract_packet_name(source: Path) -> str:
    name = source.name
    for suffix in (".raw.json", "_raw.json", ".json"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return sanitize_part(name, "packet")


def move_to_processed(path: Path, processed_root: Path) -> Path:
    processed_root.mkdir(parents=True, exist_ok=True)
    target = unique_path(processed_root / path.name)
    shutil.move(str(path), str(target))
    return target
