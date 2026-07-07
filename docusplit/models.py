from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CategoryRule:
    name: str
    folder: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
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


@dataclass(frozen=True)
class OutputDocument:
    source_file: Path
    output_file: Path
    sidecar_file: Path
    start_page: int
    end_page: int
    routed_to_review: bool
