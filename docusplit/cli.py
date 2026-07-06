from __future__ import annotations

import shutil
from pathlib import Path

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

app = typer.Typer(help="Split, classify, rename, and organize document files.")
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
def preview(
    file: Path = typer.Option(..., "--file", exists=True, dir_okay=False),
    config: Path = typer.Option(Path("config.yaml"), "--config"),
) -> None:
    """Show how one file would be split and categorized without moving the source."""
    load_env_file()
    settings = load_settings(config)
    temp_output = Path(".docusplit_preview")
    temp_errors = temp_output / "errors"
    if temp_output.exists():
        shutil.rmtree(temp_output)
    outputs = process_file(file, temp_output / "organized", settings, temp_errors)
    print_outputs(outputs)
    shutil.rmtree(temp_output)


@app.command()
def process(
    input_dir: Path = typer.Option(Path("inbox"), "--input", exists=True, file_okay=False),
    output_dir: Path = typer.Option(Path("organized"), "--output"),
    config: Path = typer.Option(Path("config.yaml"), "--config"),
    processed_dir: Path = typer.Option(Path("processed"), "--processed"),
    errors_dir: Path = typer.Option(Path("errors"), "--errors"),
) -> None:
    """Process all files currently in the input folder."""
    load_env_file()
    settings = load_settings(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    errors_dir.mkdir(parents=True, exist_ok=True)

    files = [path for path in sorted(input_dir.iterdir()) if path.is_file() and path.name != ".gitkeep"]
    if not files:
        console.print("No input files found.")
        return

    all_outputs = []
    for file_path in files:
        try:
            outputs = process_file(file_path, output_dir, settings, errors_dir)
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
    table.add_column("Type")
    table.add_column("Confidence")
    table.add_column("Output")

    for item in outputs:
        table.add_row(
            f"{item.start_page}-{item.end_page}",
            item.classification.document_type,
            f"{item.classification.confidence:.2f}",
            str(item.output_file),
        )

    console.print(table)
