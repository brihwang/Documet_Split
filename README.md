# Docusplit Local

A local CLI that splits multi-document PDFs, classifies each document, renames it, and routes it into configurable folders.

## Quick Start

```bash
python3 -m docusplit init
python3 -m docusplit process --input inbox --output organized --config config.yaml
python3 -m docusplit preview --file path/to/file.pdf --config config.yaml
```

The tool works without an API key using local rules. For better document boundaries, categories, and names, copy `.env.example` to `.env` and set `OPENAI_API_KEY`.

## Folder Flow

- `inbox/`: place incoming PDFs here.
- `organized/`: split and categorized PDFs are written here.
- `processed/`: originals are moved here after successful processing.
- `errors/review_needed/`: low-confidence or failed results go here with JSON sidecars.

## Optional Setup For Full Quality

These are placeholders until you install them:

- `openai`: enables AI boundary detection, classification, and naming.
- `pytesseract` and `PyMuPDF`: enable OCR for scanned PDFs. The system already has the `tesseract` binary, but Python bindings and a reliable PDF renderer are still needed.

Install later with:

```bash
python3 -m pip install openai pytesseract PyMuPDF
```

## Configuration

Edit `config.yaml` to add categories, keyword hints, filename templates, and output folder templates. Folder templates can use `{type}`, `{sender}`, `{date}`, and `{year}`.
