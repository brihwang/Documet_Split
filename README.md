# Docusplit Local

A local CLI that splits multi-document PDFs into separate output PDFs.

## Quick Start

```bash
python -m docusplit init
python -m docusplit policy-ai --input inbox --output organized --config config.yaml
python -m docusplit policy-rules --input inbox --output organized --config config.yaml
```

For the synthetic case 3 JSON dataset, put the raw JSON files and `manifest.json` in `inbox/`; metrics print by default from the normal command:

```bash
python -m docusplit policy-ai --input inbox --output organized --config config.yaml
```

To try it, put PDFs and/or Textract raw JSON files in `inbox/`, run one of the policy-first commands, then check `organized/`. PDF inputs produce split PDFs. Raw JSON inputs produce `*.split_plan.json` files that list the document page ranges, so you can compare the split points directly against a manifest. Successfully processed inputs are moved to `processed/`.

The tool works without an API key using local rules. Multi-page PDFs are now treated as page-boundary problems, not just category-keyword problems: the local splitter compares page titles, field labels, visible page numbering, repeated document markers, content continuity, formatting consistency, logical end cues, and structural changes such as tables or key-value blocks. When AI is configured, `policy-ai` can decide split ranges for pages that do not have policy codes, with the local splitter as a fallback. Use `policy-rules` to bypass AI for uncoded pages.

The splitter follows a page-boundary workflow: each page is treated as a possible start page, inner/continue page, or end page. This helps separate adjacent documents of the same broad type when a fresh title, new identifier, completed prior document, or semantic/structural shift shows that a new document begins.

When Textract-style raw JSON is available, the processor checks every page for policy/form codes from `form_lookup.json` before using AI or local page-pattern rules. Matching uses an Aho-Corasick automaton over normalized lookup keys, so it scans each page once and handles hundreds of codes efficiently. A code only counts as a match when the normalized code is bounded by non-alphanumeric characters or page text edges, so a shorter code like `AB12` is not matched inside a longer code like `AB123`. Pages with a matched code are grouped by the lookup `requirement_type`; contiguous uncoded page runs are passed through AI with `policy-ai` or local rules with `policy-rules`. Raw files are matched from `inbox/` by PDF name using names like `packet.pdf.json`, `packet.json`, `packet.raw.json`, or `packet_raw.json`.

For AI setup, see `AI_OPTIONS.md`. The short version:

- `AI_PROVIDER=rules`: no AI.
- `AI_PROVIDER=llmgateway`: one gateway integration for all AI providers/models.

The default LLM Gateway model is `claude-sonnet-4.6`. To force only that model, set `LLM_GATEWAY_MODEL=claude-sonnet-4.6` and leave `LLM_GATEWAY_FALLBACK_MODELS` empty.

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
