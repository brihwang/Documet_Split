from __future__ import annotations

from dataclasses import dataclass
import re

from .models import DocumentCandidate, PageText, Settings


START_HINTS = (
    "invoice",
    "receipt",
    "statement",
    "agreement",
    "contract",
    "purchase order",
)

END_HINTS = (
    "authorized signature",
    "customer signature",
    "employee signature",
    "signature",
    "signed by",
    "sincerely",
    "respectfully",
    "end of report",
    "end of document",
    "notary public",
    "total amount",
    "amount due",
    "balance due",
)

# Pages that support a preceding document (instruction sheets, continuation
# pages, addenda) rather than beginning a new one. These frequently repeat the
# parent document's title/markers and therefore fool title/marker heuristics
# into declaring a fresh document, causing same-category over-splitting.
ACCESSORY_TITLE_PATTERN = re.compile(
    r"\b(instructions|continued|continuation sheet|continuation|addendum|"
    r"appendix|attachment|exhibit|notice to recipient)\b"
)

IDENTITY_LABELS = (
    "account",
    "account number",
    "application",
    "application number",
    "authorization",
    "authorization number",
    "certificate",
    "certificate number",
    "claim",
    "claim number",
    "contract",
    "contract number",
    "customer",
    "driver license",
    "employee",
    "form",
    "invoice",
    "invoice number",
    "license",
    "license number",
    "member",
    "patient",
    "policy",
    "policy number",
    "receipt",
    "receipt number",
    "reference",
    "reference number",
    "statement",
)

STOP_WORDS = {
    "about",
    "above",
    "after",
    "again",
    "against",
    "also",
    "amount",
    "because",
    "before",
    "below",
    "between",
    "cannot",
    "company",
    "could",
    "date",
    "document",
    "during",
    "each",
    "from",
    "have",
    "here",
    "information",
    "into",
    "name",
    "number",
    "only",
    "other",
    "page",
    "please",
    "shall",
    "should",
    "than",
    "that",
    "their",
    "there",
    "these",
    "this",
    "through",
    "under",
    "upon",
    "were",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}

DOCUMENT_MARKER_PATTERNS = {
    "application": r"\bapplication\b",
    "authorization": r"\bauthori[sz]ation\b",
    "certificate": r"\bcertificate\b",
    "claim": r"\bclaim\b",
    "contract": r"\b(contract|agreement)\b",
    "form": r"\bform\s+[a-z0-9-]+\b",
    "invoice": r"\binvoice\b",
    "letter": r"\b(dear\s+\w+|re:)\b",
    "license": r"\blicen[cs]e\b",
    "medical": r"\b(patient|diagnosis|prescription|medical)\b",
    "notice": r"\bnotice\b",
    "policy": r"\bpolicy\b",
    "receipt": r"\breceipt\b",
    "report": r"\breport\b",
    "statement": r"\bstatement\b",
    "summary": r"\bsummary\b",
    "tax": r"\b(1099|1040|w-?2|tax)\b",
}


@dataclass(frozen=True)
class PageProfile:
    category: str | None
    tokens: frozenset[str]
    title_tokens: frozenset[str]
    labels: frozenset[str]
    identity_values: frozenset[str]
    markers: frozenset[str]
    headers: frozenset[str]
    footers: frozenset[str]
    first_line: str
    first_line_starts_lowercase: bool
    last_line: str
    money_count: int
    date_count: int
    table_line_count: int
    key_value_line_count: int
    starts_like_document: bool
    ends_like_document: bool
    is_accessory: bool
    continuation: bool
    page_number: int | None


def detect_documents(pages: list[PageText], settings: Settings) -> list[DocumentCandidate]:
    if not pages:
        return []

    profiles = [build_page_profile(page, settings) for page in pages]
    threshold = boundary_threshold(pages)
    starts = [0]
    for index in range(1, len(pages)):
        previous = profiles[index - 1]
        current = profiles[index]
        if boundary_score(previous, current) >= threshold:
            starts.append(index)

    starts = sorted(set(starts))
    docs: list[DocumentCandidate] = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] - 1 if pos + 1 < len(starts) else len(pages) - 1
        combined = "\n\n".join(page.text for page in pages[start : end + 1]).strip()
        docs.append(DocumentCandidate(start_page=start + 1, end_page=end + 1, text=combined))
    return docs


def build_page_profile(page: PageText, settings: Settings) -> PageProfile:
    text = page.text.lower()
    lines = meaningful_lines(page.text)
    title_lines = lines[:8]
    labels = extract_labels(lines)
    identity_values = extract_identity_values(lines)
    tokens = extract_tokens(text)
    title_tokens = extract_tokens(" ".join(title_lines))
    markers = frozenset(name for name, pattern in DOCUMENT_MARKER_PATTERNS.items() if re.search(pattern, text))
    page_number = extract_visible_page_number(text)
    key_value_line_count = sum(1 for line in lines if looks_like_key_value(line))
    table_line_count = sum(1 for line in lines if looks_like_table_row(line))
    is_accessory = looks_like_accessory_page(text, title_lines)
    # An accessory page never counts as a document start: its title/markers
    # mirror the parent document, so treating it as a start manufactures a
    # spurious boundary inside a single document.
    starts_like_document = looks_like_document_start(text, title_lines, labels, markers) and not is_accessory
    ends_like_document = looks_like_document_end(text, lines)

    return PageProfile(
        category=best_keyword_category(text, settings),
        tokens=tokens,
        title_tokens=title_tokens,
        labels=labels,
        identity_values=identity_values,
        markers=markers,
        headers=extract_repeated_edge_lines(lines[:4]),
        footers=extract_repeated_edge_lines(lines[-4:]),
        first_line=normalize_line(lines[0]) if lines else "",
        first_line_starts_lowercase=starts_with_lowercase(lines[0]) if lines else False,
        last_line=normalize_line(lines[-1]) if lines else "",
        money_count=len(re.findall(r"\$\s?\d|(?:total|balance|premium|subtotal)\b", text)),
        date_count=len(re.findall(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", text)),
        table_line_count=table_line_count,
        key_value_line_count=key_value_line_count,
        starts_like_document=starts_like_document,
        ends_like_document=ends_like_document,
        is_accessory=is_accessory,
        continuation=looks_like_continuation(text, page_number),
        page_number=page_number,
    )


def boundary_score(previous: PageProfile, current: PageProfile) -> float:
    if is_likely_continuation(previous, current):
        return 0.0

    same_category = bool(previous.category and current.category and previous.category == current.category)
    fresh_start = same_type_fresh_start(previous, current)
    # Inside a single same-category document, page-to-page variation in wording,
    # titles, and layout is normal (e.g. a form followed by its instructions).
    # Discount those "dissimilarity" signals when the category is unchanged and
    # there is no genuine fresh-start marker, so they cannot, on their own,
    # fabricate a boundary within one document.
    dissimilarity_weight = 0.35 if same_category and not fresh_start else 1.0

    score = 0.0
    if previous.category and current.category and previous.category != current.category:
        score += 3.0
    elif current.category and not previous.category:
        score += 1.0

    if current.starts_like_document:
        score += 2.0

    if previous.ends_like_document and current.starts_like_document:
        score += 1.5
    elif previous.ends_like_document:
        score += 0.5

    if fresh_start:
        score += 2.25

    text_similarity = jaccard(previous.tokens, current.tokens)
    if text_similarity < 0.12:
        score += 1.5 * dissimilarity_weight
    elif text_similarity < 0.24:
        score += 0.75 * dissimilarity_weight

    title_similarity = jaccard(previous.title_tokens, current.title_tokens)
    if current.title_tokens and title_similarity < 0.18:
        score += 1.0 * dissimilarity_weight
    elif title_similarity > 0.45:
        score -= 1.0

    label_similarity = jaccard(previous.labels, current.labels)
    if current.labels and previous.labels and label_similarity < 0.2:
        score += 1.25 * dissimilarity_weight

    if previous.markers and current.markers and previous.markers.isdisjoint(current.markers):
        score += 1.0

    if formatting_similarity(previous, current) > 0.45:
        score -= 1.0

    if structural_shift(previous, current) >= 4:
        score += 0.75 * dissimilarity_weight

    if same_category:
        score -= 0.75 if fresh_start else 1.5

    return score


def is_likely_continuation(previous: PageProfile, current: PageProfile) -> bool:
    if current.is_accessory and categories_compatible(previous, current):
        return True
    if current.starts_like_document and previous.ends_like_document:
        return False
    if current.starts_like_document and same_type_fresh_start(previous, current):
        return False
    if current.starts_like_document and categories_conflict(previous, current):
        if current.continuation and previous.first_line and previous.first_line == current.first_line:
            return True
        return False
    if content_continues(previous, current):
        return True
    if current.continuation and categories_compatible(previous, current):
        return True
    if previous.page_number is not None and current.page_number == previous.page_number + 1:
        return True
    if previous.category and previous.category == current.category and jaccard(previous.title_tokens, current.title_tokens) > 0.35:
        return True
    return False


def categories_compatible(previous: PageProfile, current: PageProfile) -> bool:
    if not previous.category or not current.category:
        return True
    return previous.category == current.category


def categories_conflict(previous: PageProfile, current: PageProfile) -> bool:
    return bool(previous.category and current.category and previous.category != current.category)


def boundary_threshold(pages: list[PageText]) -> float:
    return 2.75 if any(page.source == "raw_json" for page in pages) else 3.0


def meaningful_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract_tokens(text: str) -> frozenset[str]:
    tokens = re.findall(r"[a-z][a-z0-9]{2,}", text.lower())
    return frozenset(token for token in tokens if token not in STOP_WORDS)


def extract_labels(lines: list[str]) -> frozenset[str]:
    labels = set()
    for line in lines:
        if ":" in line:
            label = line.split(":", 1)[0]
            normalized = normalize_label(label)
            if normalized:
                labels.add(normalized)
        match = re.match(r"^([A-Za-z][A-Za-z /_-]{2,35})\s{2,}\S", line)
        if match:
            normalized = normalize_label(match.group(1))
            if normalized:
                labels.add(normalized)
    return frozenset(labels)


def extract_identity_values(lines: list[str]) -> frozenset[str]:
    values = set()
    for line in lines[:20]:
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        label = normalize_label(label)
        if label not in IDENTITY_LABELS:
            continue
        value = normalize_identity_value(value)
        if value:
            values.add(f"{label}:{value}")
    return frozenset(values)


def normalize_identity_value(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9-]+", " ", value).strip().lower()
    value = re.sub(r"\s+", " ", value)
    if len(value) < 2 or len(value) > 60:
        return ""
    return value


def normalize_label(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9 ]+", " ", value).strip().lower()
    value = re.sub(r"\s+", " ", value)
    if len(value) < 3 or len(value) > 40:
        return ""
    return value


def normalize_line(value: str) -> str:
    value = re.sub(r"\bpage\s+\d{1,3}(?:\s+of\s+\d{1,3})?\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[^A-Za-z0-9$./:-]+", " ", value).strip().lower()
    return re.sub(r"\s+", " ", value)


def extract_repeated_edge_lines(lines: list[str]) -> frozenset[str]:
    edge_lines = set()
    for line in lines:
        normalized = normalize_line(line)
        if len(normalized) >= 6 and not re.fullmatch(r"\d+", normalized):
            edge_lines.add(normalized)
    return frozenset(edge_lines)


def looks_like_document_start(text: str, title_lines: list[str], labels: frozenset[str], markers: frozenset[str]) -> bool:
    first_text = "\n".join(title_lines).lower()
    if any(re.search(rf"\b{re.escape(hint)}\b", first_text) for hint in START_HINTS):
        return strong_start_page(text)
    if markers and any(marker in first_text for marker in markers):
        return True
    if re.search(r"\b(form|application|notice|certificate|report|authorization|summary)\b", first_text):
        return True
    if re.search(r"\b(dear\s+\w+|re:)\b", first_text):
        return True
    if len(labels) >= 4 and has_title_like_line(title_lines):
        return True
    return False


def looks_like_accessory_page(text: str, title_lines: list[str]) -> bool:
    head = " ".join(title_lines[:4]).lower()
    if ACCESSORY_TITLE_PATTERN.search(head):
        return True
    if re.search(r"\binstructions?\s+for\s+(recipient|recipients|payer|payee|employee|filer|filers)\b", text):
        return True
    if re.search(r"\b(paperwork reduction act|privacy act and paperwork reduction act)\b", text):
        return True
    if re.search(r"\bcontinued\s+(on|from)\s+(the\s+)?(next|previous|following|prior)\s+page\b", text):
        return True
    return False


def looks_like_document_end(text: str, lines: list[str]) -> bool:
    edge_text = "\n".join(lines[-10:]).lower()
    if any(re.search(rf"\b{re.escape(hint)}\b", edge_text) for hint in END_HINTS):
        return True
    if re.search(r"\b(total|amount due|balance due)\b.{0,40}\$\s?\d", edge_text):
        return True
    if re.search(r"\b(i certify|certified by|approved by|prepared by|submitted by)\b", edge_text):
        return True
    if re.search(r"_\s*_+\s*(signature|date)\b", edge_text):
        return True
    if lines and normalize_line(lines[-1]) in {"thank you", "end", "completed"}:
        return True
    return False


def has_title_like_line(lines: list[str]) -> bool:
    for line in lines[:5]:
        letters = re.sub(r"[^A-Za-z]", "", line)
        if len(letters) >= 8 and line.upper() == line:
            return True
        if len(line.split()) <= 8 and re.search(r"\b(Form|Application|Notice|Statement|Summary|Report|Certificate)\b", line):
            return True
    return False


def looks_like_continuation(text: str, page_number: int | None) -> bool:
    first_and_last = f"{text[:800]}\n{text[-800:]}"
    if re.search(r"\b(continued|continued from previous|see next page)\b", first_and_last):
        return True
    return page_number is not None and page_number > 1


def content_continues(previous: PageProfile, current: PageProfile) -> bool:
    if not previous.last_line or not current.first_line:
        return False
    if previous.last_line.endswith((".", ":", ";", "!", "?")):
        return False
    if re.match(r"^(and|or|but|the|to|of|for|with|that|which|where|because|continued)\b", current.first_line):
        return True
    if current.first_line_starts_lowercase:
        return True
    if section_numbers_continue(previous.last_line, current.first_line):
        return True
    return False


def section_numbers_continue(previous_line: str, current_line: str) -> bool:
    previous_match = re.match(r"^(\d{1,2})(?:\.\d+)*[.)]?\s+", previous_line)
    current_match = re.match(r"^(\d{1,2})(?:\.\d+)*[.)]?\s+", current_line)
    if not previous_match or not current_match:
        return False
    return int(current_match.group(1)) in {int(previous_match.group(1)), int(previous_match.group(1)) + 1}


def starts_with_lowercase(line: str) -> bool:
    match = re.search(r"[A-Za-z]", line)
    return bool(match and match.group(0).islower())


def extract_visible_page_number(text: str) -> int | None:
    first_and_last = f"{text[:800]}\n{text[-800:]}"
    match = re.search(r"\bpage\s+(\d{1,3})(?:\s+of\s+\d{1,3})?\b", first_and_last)
    if not match:
        return None
    return int(match.group(1))


def looks_like_key_value(line: str) -> bool:
    return bool(re.search(r"^[A-Za-z][A-Za-z /_-]{2,45}:\s*\S", line))


def looks_like_table_row(line: str) -> bool:
    return bool(re.search(r"\S+\s{2,}\S+\s{2,}\S+", line) or re.search(r"\|", line))


def structural_shift(previous: PageProfile, current: PageProfile) -> int:
    return (
        abs(previous.money_count - current.money_count)
        + abs(previous.date_count - current.date_count)
        + abs(previous.table_line_count - current.table_line_count)
        + abs(previous.key_value_line_count - current.key_value_line_count)
    )


def same_type_fresh_start(previous: PageProfile, current: PageProfile) -> bool:
    if not current.starts_like_document:
        return False
    if previous.category and current.category and previous.category != current.category:
        return False
    if previous.identity_values and current.identity_values and previous.identity_values.isdisjoint(current.identity_values):
        return True
    if previous.ends_like_document and formatting_similarity(previous, current) < 0.35:
        return True
    if (
        previous.ends_like_document
        and previous.markers
        and current.markers
        and previous.markers == current.markers
        and jaccard(previous.title_tokens, current.title_tokens) < 0.25
    ):
        return True
    return False


def formatting_similarity(previous: PageProfile, current: PageProfile) -> float:
    header_similarity = jaccard(previous.headers, current.headers)
    footer_similarity = jaccard(previous.footers, current.footers)
    return max(header_similarity, footer_similarity)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def best_keyword_category(text: str, settings: Settings) -> str | None:
    scores = {}
    for name, rule in settings.categories.items():
        scores[name] = keyword_score(text, rule.keywords)
    best_name, best_score = max(scores.items(), key=lambda item: item[1])
    return best_name if best_score else None


def keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword_matches(text, keyword))


def keyword_matches(text: str, keyword: str) -> bool:
    keyword = keyword.strip().lower()
    if not keyword:
        return False
    return bool(re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text))


def strong_start_page(text: str) -> bool:
    return bool(
        re.search(
            r"\b(invoice|receipt|contract|agreement|statement|purchase order|application|notice|certificate|report|form)\s*(number|#|date)?\b",
            text,
        )
    )
