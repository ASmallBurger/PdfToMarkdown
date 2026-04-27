# PdfToMarkdown

A CPU-only PDF-to-Markdown converter built for AI data extraction pipelines.
Reconstructs reading order, detects heading hierarchy, extracts bordered tables,
and processes PDFs in bulk — all locally, with no GPU, no Java, no Ghostscript,
and no data ever leaving your machine.

---

## Why this exists

Most PDF-to-text tools dump a wall of unstructured text that's painful to feed
into an LLM. PdfToMarkdown reconstructs the document's logical structure
(headings, paragraphs, lists, tables) so the output is immediately useful as
context for retrieval, embedding, or fine-tuning.

Key design goals:

- **CPU-only** — runs on any laptop, no accelerators required
- **Offline** — nothing is uploaded; useful for confidential documents
- **Spec-grounded** — based on PDF/A specification principles ([pdfa.org](https://pdfa.org/))
- **Bulk-ready** — point it at a folder, walk away, come back to a folder of `.md` files

---

## Features

| Feature | How it works |
|---|---|
| **Reading order reconstruction** | Detects multi-column layouts via x-coordinate gap analysis, then sorts blocks top-to-bottom within each column. |
| **Heading hierarchy (H1 / H2 / H3)** | Two-pass scan: collects every character's font size across the whole document, ranks unique sizes, and assigns the largest to H1, next to H2, third to H3. Falls back to bold-text and ALL-CAPS detection. |
| **Paragraph segmentation** | Splits on large vertical gaps **or** ≥ 8 % font-size changes between consecutive lines. |
| **Bordered table extraction** | Uses pdfplumber's lattice strategy (looks for actual ruling lines) — no Java or Ghostscript dependency. |
| **List detection** | Recognises bullet (`•‣●◦–-*`) and numbered (`1.`, `1)`) prefixes. |
| **Bulk processing** | Drop a folder of PDFs in, get a folder of Markdown files out, with per-file and per-page progress. |
| **GUI + CLI** | Tkinter GUI for manual use, headless `--cli` mode for scripting and automation. |

---

## Installation

Requires Python 3.10 or newer.

```bash
git clone https://github.com/ASmallBurger/PdfToMarkdown
cd PdfToMarkdown
pip install -r requirements.txt
```

That's it. Three pure-Python dependencies, all CPU-only:

- `pdfplumber` ≥ 0.11
- `pdfminer.six` ≥ 20221105
- `Pillow` ≥ 10.0

No Java. No Ghostscript. No GPU. No external services.

---

## Usage

### GUI mode

```bash
python main.py
```

A window appears with:

- A **source** picker (single PDF *or* a folder full of PDFs)
- An **output folder** picker
- A "page-break markers" toggle
- Live progress bars (file-level and page-level)
- A scrolling log of what's being processed

The conversion runs in a background thread, so the UI stays responsive even on
hundred-page PDFs.

### CLI mode

```bash
# Single file
python main.py --cli report.pdf out/

# Whole folder
python main.py --cli ./papers/ ./markdown/

# With page-break markers in the output
python main.py --cli report.pdf out/ --page-breaks
```

Each input `*.pdf` becomes `*.md` in the output directory.

---

## Project layout

```
PdfToMarkdown/
├── main.py                # Entry point — GUI launcher and --cli dispatcher
├── requirements.txt
├── parser/
│   ├── extractor.py       # Two-pass PDF extraction; reading order; headings; tables
│   ├── converter.py       # PageContent → Markdown string
│   └── processor.py       # Bulk-file orchestration + progress callbacks
└── gui/
    └── app.py             # Tkinter window (thread-safe via queue.Queue)
```

---

## How heading detection works

Most converters use a fixed font-size threshold (e.g. "anything ≥ 18 pt is a
heading"), which falls apart on documents with non-standard sizing.
PdfToMarkdown does it relatively, in two passes:

1. **Pass 1** — read every character on every page, compute the median size
   (this is the body text baseline), then collect every distinct size larger
   than the baseline.
2. **Pass 2** — cluster nearby sizes (within 8 %), sort the clusters
   descending, and map them to heading levels: largest → H1, next → H2, third
   → H3.

So if your document has 22-pt section titles and 16-pt subheadings, those
become H1 and H2 — even though neither matches a hardcoded threshold.

A bold-only fallback catches headings that are body-sized but visually
emphasised (e.g. inline section labels).

---

## How table extraction works

Tables are detected using pdfplumber's **lattice strategy**, which looks for
actual ruling lines drawn in the PDF. This is reliable for bordered tables
(financial reports, scientific papers, forms) and avoids the heuristic
guesswork that "stream" strategies need.

Words that fall inside a detected table's bounding box are excluded from the
text-block extraction, so you never get duplicated content.

Currently borderless tables are not detected as tables — they fall through to
the regular text-extraction path.

---

## Limitations

- **Borderless tables** are not detected as tables (treated as paragraphs).
- **Scanned PDFs / images** are not OCR'd. If the PDF is just embedded images
  with no text layer, output will be empty. Run an OCR pass first
  (e.g. `ocrmypdf`) to add a text layer.
- **Complex multi-column layouts** with > 2 columns may have imperfect
  reading order.
- **Math/equations** are extracted as plain text in whatever Unicode the PDF
  embeds; no LaTeX reconstruction.
- **Footnotes and headers/footers** are not separated from body text.

---

## Roadmap

- Borderless table detection
- Optional OCR pre-pass via `ocrmypdf`
- Image extraction with `![]()` references
- Footnote / header / footer separation
- Standalone executable builds (Windows `.exe`, Mac `.app`)

---

## License

TBD.
