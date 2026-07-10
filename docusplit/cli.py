from __future__ import annotations

from pathlib import Path
import shutil

import typer
from rich.console import Console
from rich.table import Table

from .config import load_settings
from .organizer import move_to_processed, process_file


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            import os

            os.environ[name] = value

app = typer.Typer(help="Split document files into separate PDFs.")
console = Console()


@app.command()
def init(
    input_dir: Path = typer.Option(Path("inbox"), "--input"),
    output_dir: Path = typer.Option(Path("organized"), "--output"),
    processed_dir: Path = typer.Option(Path("processed"), "--processed"),
    errors_dir: Path = typer.Option(Path("errors"), "--errors"),
) -> None:
    """Create the default working folders."""
    for path in (input_dir, output_dir, processed_dir, errors_dir / "review_needed"):
        path.mkdir(parents=True, exist_ok=True)
        console.print(f"ready: {path}")


@app.command()
def policy_ai(
    input_dir: Path = typer.Option(Path("inbox"), "--input", exists=True, file_okay=False),
    output_dir: Path = typer.Option(Path("organized"), "--output"),
    config: Path = typer.Option(Path("config.yaml"), "--config"),
    processed_dir: Path = typer.Option(Path("processed"), "--processed"),
    errors_dir: Path = typer.Option(Path("errors"), "--errors"),
    form_lookup: Path = typer.Option(Path("form_lookup.json"), "--form-lookup", help="Policy-code lookup JSON."),
) -> None:
    """Split with inbox raw JSON policy codes, then AI for uncoded pages."""
    process_policy_first(input_dir, output_dir, config, processed_dir, errors_dir, form_lookup, use_ai=True)


@app.command()
def policy_rules(
    input_dir: Path = typer.Option(Path("inbox"), "--input", exists=True, file_okay=False),
    output_dir: Path = typer.Option(Path("organized"), "--output"),
    config: Path = typer.Option(Path("config.yaml"), "--config"),
    processed_dir: Path = typer.Option(Path("processed"), "--processed"),
    errors_dir: Path = typer.Option(Path("errors"), "--errors"),
    form_lookup: Path = typer.Option(Path("form_lookup.json"), "--form-lookup", help="Policy-code lookup JSON."),
) -> None:
    """Split with inbox raw JSON policy codes, then local rules for uncoded pages."""
    process_policy_first(input_dir, output_dir, config, processed_dir, errors_dir, form_lookup, use_ai=False)


def process_policy_first(
    input_dir: Path,
    output_dir: Path,
    config: Path,
    processed_dir: Path,
    errors_dir: Path,
    form_lookup: Path,
    use_ai: bool,
) -> None:
    load_env_file()
    settings = load_settings(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    errors_dir.mkdir(parents=True, exist_ok=True)
    if not form_lookup.exists():
        raise typer.BadParameter(f"Policy-code lookup does not exist: {form_lookup}")

    files = [path for path in sorted(input_dir.iterdir()) if path.is_file() and path.name != ".gitkeep"]
    if not files:
        console.print("No input files found.")
        return

    all_outputs = []
    for file_path in files:
        try:
            outputs = process_file(
                file_path,
                output_dir,
                settings,
                errors_dir,
                use_ai=use_ai,
                raw_dir=input_dir,
                form_lookup=form_lookup,
            )
            all_outputs.extend(outputs)
            move_to_processed(file_path, processed_dir)
        except Exception as exc:
            review_dir = errors_dir / settings.review_folder
            review_dir.mkdir(parents=True, exist_ok=True)
            target = review_dir / file_path.name
            shutil.move(str(file_path), str(target))
            console.print(f"[red]Failed:[/] {file_path} -> {target}: {exc}")

    print_outputs(all_outputs)


def print_outputs(outputs) -> None:
    table = Table(title="Docusplit Results")
    table.add_column("Pages")
    table.add_column("Splitter")
    table.add_column("AI Model")
    table.add_column("Output")

    for item in outputs:
        metadata = read_sidecar_metadata(item.sidecar_file)
        table.add_row(
            f"{item.start_page}-{item.end_page}",
            str(metadata.get("splitter", "review")),
            str(metadata.get("ai_model", "-")),
            str(item.output_file),
        )

    console.print(table)


def read_sidecar_metadata(path: Path) -> dict:
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata")
        return metadata if isinstance(metadata, dict) else {}
    except Exception:
        return {}
