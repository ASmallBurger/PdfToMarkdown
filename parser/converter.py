"""
Convert extracted PageContent blocks to a Markdown string.
"""

from __future__ import annotations

import re
from .extractor import PageContent, TableBlock, TextBlock

_BULLET_STRIP = re.compile(r"^[•‣●◦]\s*")


def _escape_md(text: str) -> str:
    """Escape characters that have special meaning in Markdown tables."""
    return text.replace("|", "\\|")


def _table_to_md(tbl: TableBlock) -> str:
    if not tbl.rows:
        return ""
    rows = tbl.rows
    # Use first row as header
    header = rows[0]
    body = rows[1:]

    col_count = max(len(r) for r in rows)

    def pad(row: list[str], n: int) -> list[str]:
        return row + [""] * (n - len(row))

    header = pad(header, col_count)
    sep = ["---"] * col_count

    lines = []
    lines.append("| " + " | ".join(_escape_md(c) for c in header) + " |")
    lines.append("| " + " | ".join(sep) + " |")
    for row in body:
        row = pad(row, col_count)
        lines.append("| " + " | ".join(_escape_md(c) for c in row) + " |")

    return "\n".join(lines)


def _text_block_to_md(block: TextBlock) -> str:
    text = block.text.strip()
    if not text:
        return ""

    if block.block_type == "heading":
        prefix = "#" * block.heading_level
        return f"{prefix} {text}"

    if block.block_type == "list_item":
        # Normalise bullet to dash
        text = _BULLET_STRIP.sub("", text).strip()
        return f"- {text}"

    return text


def pages_to_markdown(pages: list[PageContent], include_page_breaks: bool = False) -> str:
    parts: list[str] = []

    for page in pages:
        if include_page_breaks and page.page_num > 1:
            parts.append(f"\n---\n*Page {page.page_num}*\n")

        prev_was_list = False
        for block in page.blocks:
            if isinstance(block, TableBlock):
                md = _table_to_md(block)
                prev_was_list = False
            else:
                md = _text_block_to_md(block)
                is_list = block.block_type == "list_item"
                # Add blank line before a list that follows non-list content
                if is_list and not prev_was_list and parts:
                    parts.append("")
                prev_was_list = is_list

            if md:
                parts.append(md)

    return "\n\n".join(p for p in parts if p.strip())
