"""
Entry point for PdfToMarkdown.

GUI mode:        python main.py
Headless mode:   python main.py --cli <source> <output_dir> [--page-breaks]
"""

from __future__ import annotations

import sys


def _cli(args: list[str]):
    import argparse
    from pathlib import Path
    from parser.processor import process_file, process_folder

    p = argparse.ArgumentParser(description="Convert PDF(s) to Markdown.")
    p.add_argument("source", help="PDF file or folder containing PDFs")
    p.add_argument("output", help="Output directory")
    p.add_argument("--page-breaks", action="store_true", help="Insert page-break markers")
    ns = p.parse_args(args)

    src = Path(ns.source)
    out = Path(ns.output)

    def log(msg: str):
        print(msg)

    def page_prog(cur: int, total: int):
        print(f"  page {cur}/{total}", end="\r", flush=True)

    if src.is_file():
        process_file(src, out, include_page_breaks=ns.page_breaks,
                     progress_cb=page_prog, log_cb=log)
    elif src.is_dir():
        results = process_folder(src, out, include_page_breaks=ns.page_breaks,
                                 page_progress_cb=page_prog, log_cb=log)
        print(f"\nDone. {len(results)} file(s) converted.")
    else:
        print(f"ERROR: {src} is not a file or directory.", file=sys.stderr)
        sys.exit(1)


def _gui():
    from gui.app import App
    app = App()
    app.mainloop()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--cli":
        _cli(args[1:])
    else:
        _gui()
