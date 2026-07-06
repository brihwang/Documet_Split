from __future__ import annotations

from pathlib import Path
from string import Formatter
from typing import Any

import yaml

from .models import CategoryRule, Settings


DEFAULT_CONFIG = """min_confidence: 0.70
filename_template: "{date}_{type}.pdf"
default_category: Other
review_folder: review_needed

categories:
  Invoice:
    folder: "Invoice"
    keywords: [invoice, amount due, bill to, payment terms]
  Contract:
    folder: "Contract"
    keywords: [agreement, contract, parties, effective date, terms and conditions]
  Receipt:
    folder: "Receipt"
    keywords: [receipt, paid, transaction, subtotal, total]
  Statement:
    folder: "Statement"
    keywords: [statement, account summary, beginning balance, ending balance]
  Drivers License:
    folder: "Drivers License"
    keywords: [driver's license, drivers license, driver license, date of birth, license number, state id, class, endorsements, restrictions]
  Passport:
    folder: "Passport"
    keywords: [passport, nationality, place of birth, issuing authority, travel document]
  Tax Form:
    folder: "Tax Form"
    keywords: [w-2, form w-2, wage and tax statement, employer identification number, 1099, 1040, w2, tax return, taxable income, withholding, irs, internal revenue]
  Insurance:
    folder: "Insurance"
    keywords: [insurance, policy number, premium, coverage, deductible, insured, beneficiary]
  Medical:
    folder: "Medical"
    keywords: [medical intake, patient information, patient, diagnosis, prescription, physician, medical record, hospital, clinic, health]
  Other:
    folder: "Other"
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
        validate_template(str(folder), f"Category {name!r} folder")
        keywords = tuple(str(item).lower() for item in data.get("keywords", []))
        categories[str(name)] = CategoryRule(name=str(name), folder=str(folder), keywords=keywords)

    default_category = str(raw.get("default_category") or next(iter(categories)))
    if default_category not in categories:
        raise ValueError(f"default_category {default_category!r} is not listed in categories.")

    filename_template = str(raw.get("filename_template", "{date}_{type}.pdf"))
    validate_template(filename_template, "filename_template")

    return Settings(
        min_confidence=float(raw.get("min_confidence", 0.7)),
        filename_template=filename_template,
        default_category=default_category,
        review_folder=str(raw.get("review_folder", "review_needed")),
        categories=categories,
    )


def validate_template(template: str, label: str) -> None:
    allowed_fields = {"date", "type", "year"}
    fields = {field_name for _, field_name, _, _ in Formatter().parse(template) if field_name}
    unsupported = sorted(fields - allowed_fields)
    if unsupported:
      names = ", ".join(f"{{{name}}}" for name in unsupported)
      allowed = ", ".join(f"{{{name}}}" for name in sorted(allowed_fields))
      raise ValueError(f"{label} uses unsupported placeholder(s): {names}. Allowed placeholders: {allowed}.")
