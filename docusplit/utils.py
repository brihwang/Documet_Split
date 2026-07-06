from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path


DATE_RE = re.compile(
    r"\b(?:(\d{4})[-/](\d{1,2})[-/](\d{1,2})|(\d{1,2})[-/](\d{1,2})[-/](\d{2,4}))\b"
)


def sanitize_part(value: str | None, default: str = "unknown") -> str:
    text = (value or "").strip() or default
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w.\- ]+", "", text)
    text = re.sub(r"\s+", "_", text).strip("._- ")
    return text[:90] or default


def extract_date(text: str) -> str:
    match = DATE_RE.search(text)
    if not match:
        return "undated"
    if match.group(1):
        year, month, day = match.group(1), match.group(2), match.group(3)
    else:
        month, day, year = match.group(4), match.group(5), match.group(6)
        if len(year) == 2:
            year = f"20{year}"
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return "undated"


def extract_year(value: str) -> str:
    match = re.search(r"\b(20\d{2}|19\d{2})\b", value or "")
    return match.group(1) if match else "unknown_year"


def guess_sender(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip(" \t:-")
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered.startswith(("invoice", "receipt", "contract", "agreement", "statement", "date ")):
            continue
        if len(cleaned) <= 80:
            return cleaned
    return "Unknown Sender"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
