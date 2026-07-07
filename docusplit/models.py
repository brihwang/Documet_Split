from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CategoryRule:
    name: str
    folder: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    min_confidence: float
    default_category: str
    review_folder: str
    categories: dict[str, CategoryRule]


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    source: str


@dataclass(frozen=True)
class DocumentCandidate:
    start_page: int
    end_page: int
    text: str


@dataclass
class Classification:
    document_type: str
    date: str
    confidence: float
    reason: str
    suggested_filename: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutputDocument:
    source_file: Path
    output_file: Path
    sidecar_file: Path
    start_page: int
    end_page: int
    classification: Classification
    routed_to_review: bool
