from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .classifier import get_last_ai_error, get_last_ai_model, get_last_ai_split_metadata, split_documents_with_ai
from .detector import detect_documents
from .models import DocumentCandidate, PageLayoutProfile, PageText, Settings


@dataclass(frozen=True)
class PolicyCodeMatch:
    page_number: int
    code: str
    category: str


@dataclass
class _AutomatonNode:
    children: dict[str, int] = field(default_factory=dict)
    failure: int = 0
    outputs: list[str] = field(default_factory=list)


class PolicyCodeMatcher:
    def __init__(self, codes: dict[str, str]) -> None:
        self.codes = {normalize_code(code): category for code, category in codes.items() if normalize_code(code)}
        self.nodes = [_AutomatonNode()]
        for code in self.codes:
            self._insert(code)
        self._build_failures()

    @classmethod
    def from_lookup_file(cls, path: Path) -> PolicyCodeMatcher:
        lookup = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(lookup, dict):
            raise ValueError(f"Policy lookup must be a JSON object: {path}")

        codes: dict[str, str] = {}
        for code, payload in lookup.items():
            if not isinstance(code, str):
                continue
            category = code
            if isinstance(payload, dict):
                value = payload.get("requirement_type")
                if isinstance(value, str) and value.strip():
                    category = value.strip()
            codes[code] = category
        return cls(codes)

    def find_matches(self, text: str) -> list[tuple[str, str]]:
        state = 0
        found: list[tuple[str, str]] = []
        normalized_text, positions = normalize_text_with_positions(text)
        for index, char in enumerate(normalized_text):
            while state and char not in self.nodes[state].children:
                state = self.nodes[state].failure
            state = self.nodes[state].children.get(char, 0)
            for code in self.nodes[state].outputs:
                start = index - len(code) + 1
                if exact_match_boundary(text, positions[start], positions[index]):
                    found.append((code, self.codes[code]))
        return found

    def _insert(self, code: str) -> None:
        state = 0
        for char in code:
            next_state = self.nodes[state].children.get(char)
            if next_state is None:
                next_state = len(self.nodes)
                self.nodes[state].children[char] = next_state
                self.nodes.append(_AutomatonNode())
            state = next_state
        self.nodes[state].outputs.append(code)

    def _build_failures(self) -> None:
        queue: deque[int] = deque()
        for child in self.nodes[0].children.values():
            queue.append(child)

        while queue:
            state = queue.popleft()
            for char, child in self.nodes[state].children.items():
                queue.append(child)
                failure = self.nodes[state].failure
                while failure and char not in self.nodes[failure].children:
                    failure = self.nodes[failure].failure
                self.nodes[child].failure = self.nodes[failure].children.get(char, 0)
                self.nodes[child].outputs.extend(self.nodes[self.nodes[child].failure].outputs)


def normalize_code(value: str) -> str:
    return "".join(char for char in value.upper() if char.isalnum())


def normalize_text(value: str) -> str:
    return normalize_code(value)


def normalize_text_with_positions(value: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(value):
        if char.isalnum():
            chars.append(char.upper())
            positions.append(index)
    return "".join(chars), positions


def exact_match_boundary(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else ""
    after = text[end + 1] if end + 1 < len(text) else ""
    return not before.isalnum() and not after.isalnum()


def extract_raw_pages(path: Path) -> list[PageText]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    blocks = payload.get("Blocks") if isinstance(payload, dict) else None
    if not isinstance(blocks, list):
        raise ValueError(f"Raw JSON must contain a Blocks list: {path}")

    line_blocks: dict[int, list[tuple[float, float, float, float, str]]] = defaultdict(list)
    word_blocks: dict[int, list[tuple[float, float, str]]] = defaultdict(list)
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = block.get("Text")
        page = block.get("Page")
        block_type = block.get("BlockType")
        if not isinstance(text, str) or not isinstance(page, int):
            continue
        top, left, width, height = block_geometry(block)
        if block_type == "LINE":
            line_blocks[page].append((top, left, width, height, text))
        elif block_type == "WORD":
            word_blocks[page].append((top, left, text))

    pages: list[PageText] = []
    for page_number in sorted(set(line_blocks) | set(word_blocks)):
        page_line_blocks = line_blocks.get(page_number)
        if page_line_blocks:
            text = "\n".join(text for _, _, _, _, text in sorted(page_line_blocks)).strip()
            layout = build_page_layout_profile(page_line_blocks)
        else:
            page_word_blocks = word_blocks.get(page_number, [])
            text = "\n".join(text for _, _, text in sorted(page_word_blocks)).strip()
            layout = None
        pages.append(PageText(page_number=page_number, text=text, source="raw_json", layout=layout))
    return pages


def block_position(block: dict[str, Any]) -> tuple[float, float]:
    top, left, _, _ = block_geometry(block)
    return top, left


def block_geometry(block: dict[str, Any]) -> tuple[float, float, float, float]:
    geometry = block.get("Geometry")
    if not isinstance(geometry, dict):
        return (0.0, 0.0, 0.0, 0.0)
    box = geometry.get("BoundingBox")
    if not isinstance(box, dict):
        return (0.0, 0.0, 0.0, 0.0)
    top = box.get("Top")
    left = box.get("Left")
    width = box.get("Width")
    height = box.get("Height")
    return (
        float(top) if isinstance(top, int | float) else 0.0,
        float(left) if isinstance(left, int | float) else 0.0,
        float(width) if isinstance(width, int | float) else 0.0,
        float(height) if isinstance(height, int | float) else 0.0,
    )


def build_page_layout_profile(lines: list[tuple[float, float, float, float, str]]) -> PageLayoutProfile:
    ordered = sorted(lines)
    vertical_bands = tuple((round(top, 3), round(height, 3)) for top, _, _, height, _ in ordered)
    left_bands = tuple(round(left, 3) for _, left, _, _, _ in ordered)
    label_sequence = tuple(normalize_layout_label(text) for _, _, _, _, text in ordered)
    geometry_items = tuple((top, left) for top, left in zip(vertical_bands, left_bands, strict=False))
    template_items = tuple((top, left, label) for top, left, label in zip(vertical_bands, left_bands, label_sequence, strict=False))

    return PageLayoutProfile(
        line_count=len(ordered),
        vertical_bands=vertical_bands,
        left_bands=left_bands,
        label_sequence=label_sequence,
        first_label=label_sequence[0] if label_sequence else "",
        has_form_code_line=any("form code" in label for label in label_sequence),
        geometry_signature=layout_signature(geometry_items),
        template_signature=layout_signature(template_items),
    )


def normalize_layout_label(text: str) -> str:
    value = text.strip()
    if re.fullmatch(r"synthetic packet \d+ page \d+", value, flags=re.IGNORECASE):
        return "<packet_page>"
    if value.lower().startswith("no policy form code appears"):
        return "<no_policy_notice>"
    value = re.sub(r"\bpage\s+\d{1,3}(?:\s+of\s+\d{1,3})?\b", "page <n>", value, flags=re.IGNORECASE)
    value = re.sub(r"\$\s?[\d,]+(?:\.\d{2})?", "<money>", value)
    value = re.sub(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", "<date>", value)
    value = re.sub(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", "<date>", value)
    value = re.sub(r"\b[A-Z]{2,}\d[A-Z0-9-]{2,}\b", "<code>", value)
    if ":" in value:
        value = value.split(":", 1)[0].strip() + ": <value>"
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def layout_signature(items: object) -> str:
    return hashlib.sha1(repr(items).encode("utf-8")).hexdigest()[:12]


def find_page_policy_matches(pages: list[PageText], matcher: PolicyCodeMatcher) -> dict[int, list[PolicyCodeMatch]]:
    matches_by_page: dict[int, list[PolicyCodeMatch]] = {}
    for page in pages:
        matches = [
            PolicyCodeMatch(page_number=page.page_number, code=code, category=category)
            for code, category in matcher.find_matches(page.text)
        ]
        if matches:
            matches_by_page[page.page_number] = matches
    return matches_by_page


def split_with_policy_codes(
    pages: list[PageText],
    raw_pages: list[PageText],
    matcher: PolicyCodeMatcher,
    settings: Settings,
    use_ai: bool = True,
) -> tuple[list[DocumentCandidate], dict[str, object]] | None:
    matches_by_page = find_page_policy_matches(raw_pages, matcher)
    if not matches_by_page:
        return None

    raw_text_by_page = {page.page_number: page.text for page in raw_pages}
    policy_pages = {page_number: first_page_category(matches) for page_number, matches in matches_by_page.items()}
    candidates: list[DocumentCandidate] = []
    ai_runs: list[dict[str, object]] = []

    index = 0
    while index < len(pages):
        page = pages[index]
        category = policy_pages.get(page.page_number)
        run_start = index
        if category is None:
            while index + 1 < len(pages) and policy_pages.get(pages[index + 1].page_number) is None:
                index += 1
            candidates.extend(split_uncoded_pages(pages[run_start : index + 1], settings, use_ai=use_ai, ai_runs=ai_runs))
        else:
            while index + 1 < len(pages) and policy_pages.get(pages[index + 1].page_number) == category:
                index += 1
            candidates.append(candidate_from_slice(pages[run_start : index + 1]))
        index += 1

    all_pages_coded = len(policy_pages) == len(pages)
    single_category = len(set(policy_pages.values())) == 1
    metadata: dict[str, object] = {
        "splitter": "policy_codes" if all_pages_coded else "policy_codes_with_local_page_patterns",
        "document_count": len(candidates),
        "policy_code_pages": len(policy_pages),
        "uncoded_pages": len(pages) - len(policy_pages),
        "all_pages_policy_coded": all_pages_coded,
        "single_policy_category": single_category,
        "policy_matches": {
            str(page_number): sorted({match.code for match in matches})
            for page_number, matches in sorted(matches_by_page.items())
        },
        "policy_categories": {str(page_number): category for page_number, category in sorted(policy_pages.items())},
    }
    if any(page.page_number not in raw_text_by_page for page in pages):
        metadata["policy_warning"] = "Some PDF pages were missing from the raw JSON."
    if use_ai:
        ai_model = get_last_ai_model()
        ai_error = get_last_ai_error()
        if ai_model:
            metadata["ai_model"] = ai_model
        if ai_runs:
            metadata["ai_runs"] = ai_runs
        if ai_error:
            metadata["ai_error"] = ai_error
    return candidates, metadata


def first_page_category(matches: list[PolicyCodeMatch]) -> str:
    return matches[0].category


def split_uncoded_pages(
    pages: list[PageText],
    settings: Settings,
    use_ai: bool = True,
    ai_runs: list[dict[str, object]] | None = None,
) -> list[DocumentCandidate]:
    if not pages:
        return []

    if use_ai:
        ai_candidates = split_documents_with_ai(renumber_pages(pages))
        if ai_candidates:
            offset = pages[0].page_number - 1
            adjusted = offset_candidates(ai_candidates, offset)
            if ai_runs is not None:
                ai_runs.append(
                    {
                        "input_page_range": [pages[0].page_number, pages[-1].page_number],
                        "output_ranges": [[candidate.start_page, candidate.end_page] for candidate in adjusted],
                        **get_last_ai_split_metadata(),
                    }
                )
            return adjusted

    detected = detect_documents(pages, settings)
    if not detected:
        return [candidate_from_slice(pages)]

    return offset_candidates(detected, pages[0].page_number - 1)


def renumber_pages(pages: list[PageText]) -> list[PageText]:
    return [
        PageText(page_number=index + 1, text=page.text, source=page.source, layout=page.layout)
        for index, page in enumerate(pages)
    ]


def offset_candidates(candidates: list[DocumentCandidate], offset: int) -> list[DocumentCandidate]:
    return [
        DocumentCandidate(
            start_page=candidate.start_page + offset,
            end_page=candidate.end_page + offset,
            text=candidate.text,
        )
        for candidate in candidates
    ]


def candidate_from_slice(pages: list[PageText]) -> DocumentCandidate:
    return DocumentCandidate(
        start_page=pages[0].page_number,
        end_page=pages[-1].page_number,
        text="\n\n".join(page.text for page in pages).strip(),
    )


def find_raw_json_for_pdf(pdf_path: Path, raw_dir: Path | None = None) -> Path | None:
    search_dir = raw_dir or pdf_path.parent
    candidates = [
        search_dir / f"{pdf_path.name}.json",
        search_dir / f"{pdf_path.stem}.json",
        search_dir / f"{pdf_path.stem}.raw.json",
        search_dir / f"{pdf_path.stem}_raw.json",
    ]
    return next((candidate for candidate in candidates if candidate.exists()), None)