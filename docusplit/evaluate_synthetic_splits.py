from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table


console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a synthetic dataset manifest to docusplit output.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Directory containing docusplit split plans or sidecars.")
    parser.add_argument("--case", default="mixed_coded_uncoded")
    parser.add_argument("--json-report", type=Path, default=None)
    args = parser.parse_args()

    report = evaluate(args.manifest, args.output, args.case)
    print_report(report)
    if args.json_report:
        args.json_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        console.print(f"JSON report: {args.json_report}")


def evaluate(manifest_path: Path, output_dir: Path, case_name: str) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    manifest_files = manifest.get("files", [])
    if not isinstance(manifest_files, list):
        raise ValueError("manifest files must be a list")

    results = []
    for entry in manifest_files:
        if not isinstance(entry, dict) or entry.get("case") != case_name:
            continue
        expected = expected_ranges(entry)
        predicted, output_file = predicted_ranges(entry, output_dir)
        expected_set = set(expected)
        predicted_set = set(predicted)
        results.append(
            {
                "synthetic_pdf": entry.get("synthetic_pdf"),
                "raw_file": entry.get("file"),
                "output_file": str(output_file) if output_file else None,
                "expected_ranges": [list(item) for item in expected],
                "predicted_ranges": [list(item) for item in predicted],
                "correct": expected == predicted,
                "missing_ranges": [list(item) for item in sorted(expected_set - predicted_set)],
                "extra_ranges": [list(item) for item in sorted(predicted_set - expected_set)],
            }
        )

    total_files = len(results)
    exact_files = sum(1 for item in results if item["correct"])
    expected_count = sum(len(item["expected_ranges"]) for item in results)
    predicted_count = sum(len(item["predicted_ranges"]) for item in results)
    matched_count = sum(
        len({tuple(value) for value in item["expected_ranges"]} & {tuple(value) for value in item["predicted_ranges"]})
        for item in results
    )
    precision = matched_count / predicted_count if predicted_count else 0.0
    recall = matched_count / expected_count if expected_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    return {
        "manifest": str(manifest_path),
        "output_dir": str(output_dir),
        "case": case_name,
        "files_evaluated": total_files,
        "files_exact": exact_files,
        "file_accuracy": exact_files / total_files if total_files else 0.0,
        "expected_document_count": expected_count,
        "predicted_document_count": predicted_count,
        "matched_document_ranges": matched_count,
        "range_precision": precision,
        "range_recall": recall,
        "range_f1": f1,
        "incorrect_files": [item for item in results if not item["correct"]],
    }


def expected_ranges(entry: dict[str, Any]) -> list[tuple[int, int]]:
    runs = entry.get("expected_runs")
    if not isinstance(runs, list):
        return []
    ranges = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        start_page = run.get("start_page")
        end_page = run.get("end_page")
        if isinstance(start_page, int) and isinstance(end_page, int):
            ranges.append((start_page, end_page))
    return ranges


def predicted_ranges(entry: dict[str, Any], output_dir: Path) -> tuple[list[tuple[int, int]], Path | None]:
    plan_path = find_split_plan(entry, output_dir)
    if plan_path:
        return ranges_from_split_plan(plan_path), plan_path
    return [], None


def find_split_plan(entry: dict[str, Any], output_dir: Path) -> Path | None:
    candidates = []
    raw_file = entry.get("file")
    if isinstance(raw_file, str):
        candidates.append(f"{Path(raw_file).stem}.split_plan.json")
    synthetic_pdf = entry.get("synthetic_pdf")
    if isinstance(synthetic_pdf, str):
        candidates.append(f"{synthetic_pdf}.split_plan.json")

    for candidate in candidates:
        direct = output_dir / candidate
        if direct.exists():
            return direct
        matches = sorted(output_dir.rglob(candidate))
        if matches:
            return matches[0]
    return None


def ranges_from_split_plan(path: Path) -> list[tuple[int, int]]:
    payload = load_json(path)
    documents = payload.get("documents", [])
    if not isinstance(documents, list):
        return []
    ranges = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        page_range = document.get("page_range")
        if isinstance(page_range, list) and len(page_range) == 2 and all(isinstance(value, int) for value in page_range):
            ranges.append((page_range[0], page_range[1]))
            continue
        start_page = document.get("start_page")
        end_page = document.get("end_page")
        if isinstance(start_page, int) and isinstance(end_page, int):
            ranges.append((start_page, end_page))
    return ranges


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def print_report(report: dict[str, Any]) -> None:
    summary = Table(title="Synthetic Split Accuracy")
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Files evaluated", str(report["files_evaluated"]))
    summary.add_row("Files exact", str(report["files_exact"]))
    summary.add_row("File accuracy", percent(report["file_accuracy"]))
    summary.add_row("Expected ranges", str(report["expected_document_count"]))
    summary.add_row("Predicted ranges", str(report["predicted_document_count"]))
    summary.add_row("Matched ranges", str(report["matched_document_ranges"]))
    summary.add_row("Range precision", percent(report["range_precision"]))
    summary.add_row("Range recall", percent(report["range_recall"]))
    summary.add_row("Range F1", percent(report["range_f1"]))
    console.print(summary)

    incorrect_files = report["incorrect_files"]
    if not incorrect_files:
        console.print("All files matched the manifest exactly.")
        return

    details = Table(title="Incorrect Files")
    details.add_column("File")
    details.add_column("Expected")
    details.add_column("Predicted")
    details.add_column("Missing")
    details.add_column("Extra")
    for item in incorrect_files:
        details.add_row(
            str(item["synthetic_pdf"]),
            compact_ranges(item["expected_ranges"]),
            compact_ranges(item["predicted_ranges"]),
            compact_ranges(item["missing_ranges"]),
            compact_ranges(item["extra_ranges"]),
        )
    console.print(details)


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def compact_ranges(ranges: list[list[int]]) -> str:
    if not ranges:
        return "-"
    return ", ".join(f"{start}-{end}" for start, end in ranges)


if __name__ == "__main__":
    main()