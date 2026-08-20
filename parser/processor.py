"""
Bulk PDF processing: converts one or many PDF files to Markdown.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .extractor import extract_pdf
from .converter import pages_to_markdown


def process_file(
    src: str | Path,
    out_dir: str | Path,
    include_page_breaks: bool = False,
    progress_cb: Callable[[int, int], None] | None = None,
    log_cb: Callable[[str], None] | None = None,
) -> Path:
    """
    Convert a single PDF to Markdown.

    Returns the path of the written .md file.
    """
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / src.with_suffix(".md").name

    if log_cb:
        log_cb(f"Processing: {src.name}")

    pages = extract_pdf(str(src), progress_cb=progress_cb)
    md = pages_to_markdown(pages, include_page_breaks=include_page_breaks)

    out_path.write_text(md, encoding="utf-8")

    if log_cb:
        log_cb(f"  -> {out_path}")

    return out_path


def process_folder(
    src_dir: str | Path,
    out_dir: str | Path,
    include_page_breaks: bool = False,
    file_progress_cb: Callable[[int, int], None] | None = None,
    page_progress_cb: Callable[[int, int], None] | None = None,
    log_cb: Callable[[str], None] | None = None,
) -> list[Path]:
    """
    Convert all PDFs in src_dir to Markdown files in out_dir.

    file_progress_cb(completed_files, total_files)
    page_progress_cb(current_page, total_pages)  (reset for each file)
    """
    src_dir = Path(src_dir)
    pdfs = sorted(src_dir.glob("*.pdf"))

    if not pdfs:
        if log_cb:
            log_cb(f"No PDF files found in {src_dir}")
        return []

    results: list[Path] = []
    total = len(pdfs)

    for idx, pdf in enumerate(pdfs, 1):
        out = process_file(
            pdf,
            out_dir,
            include_page_breaks=include_page_breaks,
            progress_cb=page_progress_cb,
            log_cb=log_cb,
        )
        results.append(out)
        if file_progress_cb:
            file_progress_cb(idx, total)

    return results
