from __future__ import annotations

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


def detect_documents(pages: list[PageText], settings: Settings) -> list[DocumentCandidate]:
    if not pages:
        return []

    starts = [0]
    previous_category = None
    for index, page in enumerate(pages):
        text = page.text.lower()
        category = best_keyword_category(text, settings)
        has_start_hint = any(re.search(rf"\b{re.escape(hint)}\b", text) for hint in START_HINTS)

        if index > 0:
            category_changed = category and category != previous_category
            if category_changed or (has_start_hint and strong_start_page(text)):
                starts.append(index)

        previous_category = category or previous_category

    starts = sorted(set(starts))
    docs: list[DocumentCandidate] = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] - 1 if pos + 1 < len(starts) else len(pages) - 1
        combined = "\n\n".join(page.text for page in pages[start : end + 1]).strip()
        docs.append(DocumentCandidate(start_page=start + 1, end_page=end + 1, text=combined))
    return docs


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
    return bool(re.search(r"\b(invoice|receipt|contract|agreement|statement)\s*(number|#|date)?\b", text))
