from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import CategoryRule, Settings


DEFAULT_CONFIG = """min_confidence: 0.70
filename_template: "{date}_{sender}_{type}.pdf"
default_category: Other
review_folder: review_needed

categories:
  Invoice:
    folder: "Finance/Invoices/{year}/{sender}"
    keywords: [invoice, amount due, bill to, payment terms]
  Contract:
    folder: "Legal/Contracts/{sender}"
    keywords: [agreement, contract, parties, effective date, terms and conditions]
  Receipt:
    folder: "Finance/Receipts/{year}"
    keywords: [receipt, paid, transaction, subtotal, total]
  Other:
    folder: "Other/{year}"
    keywords: []
"""


def load_settings(path: Path) -> Settings:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    categories_raw: dict[str, Any] = raw.get("categories") or {}
    if not categories_raw:
        raise ValueError("Config must define at least one category under 'categories'.")

    categories: dict[str, CategoryRule] = {}
    for name, data in categories_raw.items():
        data = data or {}
        folder = data.get("folder")
        if not folder:
            raise ValueError(f"Category {name!r} must define a folder template.")
        keywords = tuple(str(item).lower() for item in data.get("keywords", []))
        categories[str(name)] = CategoryRule(name=str(name), folder=str(folder), keywords=keywords)

    default_category = str(raw.get("default_category") or next(iter(categories)))
    if default_category not in categories:
        raise ValueError(f"default_category {default_category!r} is not listed in categories.")

    return Settings(
        min_confidence=float(raw.get("min_confidence", 0.7)),
        filename_template=str(raw.get("filename_template", "{date}_{sender}_{type}.pdf")),
        default_category=default_category,
        review_folder=str(raw.get("review_folder", "review_needed")),
        categories=categories,
    )
