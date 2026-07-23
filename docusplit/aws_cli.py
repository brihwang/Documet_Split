from __future__ import annotations

from pathlib import Path

from PyPDF2 import PdfReader
from rich.console import Console
from rich.table import Table
import typer

from .aws_splitter import DEFAULT_BEDROCK_MODEL, AwsSplitResult, split_with_bedrock
from .cli import load_env_file
from .config import load_settings
from .extractor import extract_pdf_text
from .organizer import (
    write_sidecar,
    write_split_pdf,
    write_split_plan,
    write_split_textract_json,
)
from .policy_codes import extract_raw_pages


app = typer.Typer(help="Split PDFs or Textract JSON with AWS Bedrock boundary segmentation.")
console = Console()


@app.callback()
def main() -> None:
    """AWS Bedrock document-boundary commands."""


@app.command("split")
def split(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(Path("aws_organized"), "--output", "-o"),
    config: Path = typer.Option(Path("config.yaml"), "--config"),
    model: str = typer.Option(DEFAULT_BEDROCK_MODEL, "--model"),
    region: str | None = typer.Option(None, "--region"),
    profile: str | None = typer.Option(None, "--profile"),
    context_pages: int = typer.Option(1, "--context-pages", min=0, max=5),
    text_only: bool = typer.Option(False, "--text-only", help="Do not send rendered page images."),
) -> None:
    """Classify each page as start/continue, then write the resulting page ranges."""
    load_env_file()
    settings = load_settings(config)
    files = input_files(input_path)
    if not files:
        raise typer.BadParameter("Input contains no PDF or JSON files.")

    table = Table(title="AWS Bedrock Split Results")
    table.add_column("Input")
    table.add_column("Pages")
    table.add_column("Type")
    table.add_column("Output")
    for path in files:
        pages = extract_pdf_text(path) if path.suffix.lower() == ".pdf" else extract_raw_pages(path)
        result = split_with_bedrock(
            pages,
            settings,
            source_pdf=path if path.suffix.lower() == ".pdf" else None,
            model=model,
            region=region,
            profile=profile,
            context_pages=context_pages,
            multimodal=not text_only,
        )
        outputs = write_outputs(path, output_dir, result)
        for candidate, output in zip(result.candidates, outputs, strict=True):
            doc_type = result.classifications[candidate.start_page - 1].doc_type
            table.add_row(
                path.name,
                f"{candidate.start_page}-{candidate.end_page}",
                doc_type,
                str(output),
            )
    console.print(table)


def input_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() not in {".pdf", ".json"}:
            raise typer.BadParameter("Input must be a PDF, a Textract-style JSON file, or a directory.")
        return [path]
    return [
        candidate
        for candidate in sorted(path.iterdir())
        if candidate.is_file()
        and candidate.suffix.lower() in {".pdf", ".json"}
        and candidate.name != "manifest.json"
    ]


def write_outputs(source: Path, output_dir: Path, result: AwsSplitResult) -> list[Path]:
    metadata: dict[str, object] = {
        "splitter": "aws_bedrock_page_boundary",
        "classification_method": "multimodalPageLevelClassification"
        if result.multimodal
        else "textPageLevelClassification",
        "section_splitting": "llm_determined",
        "model": result.model,
        "document_count": len(result.candidates),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "page_classifications": [
            {
                "page": item.page_number,
                "doc_type": item.doc_type,
                "document_boundary": item.document_boundary,
                "confidence": item.confidence,
                "reason": item.reason,
            }
            for item in result.classifications
        ],
    }
    if source.suffix.lower() == ".json":
        classification_by_page = {
            item.page_number: item.doc_type for item in result.classifications
        }
        document_types = [
            classification_by_page[candidate.start_page]
            for candidate in result.candidates
        ]
        outputs = write_split_textract_json(
            source,
            result.candidates,
            document_types,
            output_dir,
        )
        plan = write_split_plan(
            source,
            result.candidates,
            metadata,
            output_dir,
            document_outputs=outputs,
        )
        metadata["split_plan"] = str(plan)
        return outputs

    reader = PdfReader(str(source))
    outputs: list[Path] = []
    for candidate in result.candidates:
        output = write_split_pdf(
            source, reader, candidate.start_page, candidate.end_page, output_dir
        )
        write_sidecar(
            output, source, candidate.start_page, candidate.end_page, metadata
        )
        outputs.append(output)
    return outputs


if __name__ == "__main__":
    app()
