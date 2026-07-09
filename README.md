# Docusplit Local

A local CLI that splits multi-document PDFs into separate output PDFs.

## Quick Start

```bash
python -m docusplit init
python -m docusplit process --input inbox --output organized --config config.yaml
python -m docusplit process --input inbox --output organized --config config.yaml --rules-only
python -m docusplit process --input inbox --raw-dir raw --form-lookup form_lookup.json --rules-only
```

To try it, put PDFs or files in `inbox/`, run the `process` command, then check `organized/`. The original input files are moved to `processed/` after a successful run.

The tool works without an API key using local rules. Multi-page PDFs are now treated as page-boundary problems, not just category-keyword problems: the local splitter compares page titles, field labels, visible page numbering, repeated document markers, content continuity, formatting consistency, logical end cues, and structural changes such as tables or key-value blocks. When AI is configured, it can decide the split ranges for any multi-page PDF, with the local splitter as a fallback.

Use `--rules-only` with `process` to bypass AI for that run even when `.env` is configured for LLM Gateway.

The splitter follows a page-boundary workflow: each page is treated as a possible start page, inner/continue page, or end page. This helps separate adjacent documents of the same broad type when a fresh title, new identifier, completed prior document, or semantic/structural shift shows that a new document begins.

When Textract-style raw JSON is available, the processor checks every page for policy/form codes from `form_lookup.json` before using AI or local page-pattern rules. Matching uses an Aho-Corasick automaton over normalized lookup keys, so it scans each page once and handles hundreds of codes efficiently. Pages with a matched code are grouped by the lookup `requirement_type`; contiguous uncoded page runs are passed through the existing local splitter. Raw files are matched by PDF name from `--raw-dir` using names like `packet.pdf.json`, `packet.json`, `packet.raw.json`, or `packet_raw.json`.

For AI setup, see `AI_OPTIONS.md`. The short version:

- `AI_PROVIDER=rules`: no AI.
- `AI_PROVIDER=llmgateway`: one gateway integration for all AI providers/models.

## Folder Flow

- `inbox/`: place incoming PDFs here.
- `organized/`: split PDFs are written here.
- `processed/`: originals are moved here after successful processing.
- `errors/review_needed/`: failed or unsupported files go here with JSON sidecars.

## Optional Setup For Full Quality

These are placeholders until you install them:

- `openai`: used only as the OpenAI-compatible Python client for LLM Gateway.
- `pytesseract` and `PyMuPDF`: enable OCR for scanned PDFs. The system already has the `tesseract` binary, but Python bindings and a reliable PDF renderer are still needed.

Install later with:

```bash
python3 -m pip install openai pytesseract PyMuPDF
```

## Configuration

Edit `config.yaml` to tune the local fallback splitter's category keyword hints. The current processing flow does not classify or route PDFs by category; it writes split PDFs directly to the output folder.
