# Docusplit Local

A local CLI that splits multi-document PDFs, classifies each document, renames it, and routes it into configurable folders.

## Quick Start

```bash
python -m docusplit init
python -m docusplit process --input inbox --output organized --config config.yaml
python -m docusplit preview --file path/to/file.pdf --config config.yaml
```

To try it, put PDFs or files in `inbox/`, run the `process` command, then check `organized/`. The original input files are moved to `processed/` after a successful run.

The tool works without an API key using local rules. To reduce cost, AI is not used for ordinary single-category PDFs. When AI is configured, it is only considered for PDFs where local rules detect multiple document types in the same source file, or where a locally detected document is too ambiguous to classify confidently.

For AI setup, see `AI_OPTIONS.md`. The short version:

- `AI_PROVIDER=rules`: no AI.
- `AI_PROVIDER=llmgateway`: one gateway integration for all AI providers/models.

## Folder Flow

- `inbox/`: place incoming PDFs here.
- `organized/`: split and categorized PDFs are written here.
- `processed/`: originals are moved here after successful processing.
- `errors/review_needed/`: low-confidence or failed results go here with JSON sidecars.

## Optional Setup For Full Quality

These are placeholders until you install them:

- `openai`: used only as the OpenAI-compatible Python client for LLM Gateway.
- `pytesseract` and `PyMuPDF`: enable OCR for scanned PDFs. The system already has the `tesseract` binary, but Python bindings and a reliable PDF renderer are still needed.

Install later with:

```bash
python3 -m pip install openai pytesseract PyMuPDF
```

## Configuration

Edit `config.yaml` to add categories, keyword hints, filename templates, and output folder templates. Folder templates can use `{type}`, `{date}`, and `{year}`.
