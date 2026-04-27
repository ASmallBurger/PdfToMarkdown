"""
PDF content extractor.

Extraction pipeline per page:
  1. Detect bordered tables and record their bounding boxes.
  2. Analyse character-level font sizes to establish the body-text baseline.
  3. Extract words outside table regions, cluster into lines/paragraphs.
  4. Classify paragraphs as headings (H1/H2/H3) or body text.
  5. Reconstruct reading order: detect columns, sort top-to-bottom per column.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Generator

import pdfplumber


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class TableBlock:
    rows: list[list[str]]
    page_num: int
    bbox: tuple[float, float, float, float]  # x0, top, x1, bottom


@dataclass
class TextBlock:
    text: str
    page_num: int
    bbox: tuple[float, float, float, float]
    font_size: float
    is_bold: bool
    block_type: str = "paragraph"   # paragraph | h1 | h2 | h3 | list_item
    heading_level: int = 0           # 1-3 for headings, 0 otherwise


@dataclass
class PageContent:
    page_num: int
    blocks: list[TableBlock | TextBlock] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BOLD_PATTERN = re.compile(r"bold|black|heavy|extrabold", re.IGNORECASE)
_LIST_BULLETS = re.compile(r"^[•‣●◦–\-\*]\s+|^\d+[\.\)]\s+")


def _is_bold(fontname: str) -> bool:
    return bool(_BOLD_PATTERN.search(fontname))


def _bbox_overlap(a: tuple, b: tuple) -> bool:
    """Return True if two (x0, top, x1, bottom) boxes overlap."""
    ax0, at, ax1, ab = a
    bx0, bt, bx1, bb = b
    return ax0 < bx1 and ax1 > bx0 and at < bb and ab > bt


def _point_in_bbox(x: float, y: float, bbox: tuple, margin: float = 2.0) -> bool:
    x0, top, x1, bottom = bbox
    return (x0 - margin) <= x <= (x1 + margin) and (top - margin) <= y <= (bottom + margin)


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

def _detect_columns(words: list[dict]) -> list[tuple[float, float]]:
    """
    Return a list of (x_left, x_right) column bands sorted left-to-right.

    Strategy: project word centres onto the x-axis, look for a clear gap
    wider than 10 % of page width that splits words into left / right halves.
    Falls back to single-column if no such gap exists.
    """
    if not words:
        return [(0, 1e9)]

    xs = sorted(w["x0"] for w in words)
    page_w = max(w["x1"] for w in words) - min(w["x0"] for w in words)
    gap_threshold = page_w * 0.10

    # Find gaps between consecutive x0 values
    gaps = []
    for i in range(1, len(xs)):
        gap = xs[i] - xs[i - 1]
        if gap > gap_threshold:
            gaps.append((gap, (xs[i - 1] + xs[i]) / 2))

    if not gaps:
        return [(0, 1e9)]

    # Use the single largest gap as column divider (handles 2-column layouts)
    _, split_x = max(gaps)
    left_words = [w for w in words if w["x0"] < split_x]
    right_words = [w for w in words if w["x0"] >= split_x]

    if not left_words or not right_words:
        return [(0, 1e9)]

    left_band = (min(w["x0"] for w in left_words), split_x)
    right_band = (split_x, max(w["x1"] for w in right_words) + 1)
    return [left_band, right_band]


def _column_index(x: float, columns: list[tuple[float, float]]) -> int:
    for i, (left, right) in enumerate(columns):
        if left <= x < right:
            return i
    return len(columns) - 1


# ---------------------------------------------------------------------------
# Font-size baseline
# ---------------------------------------------------------------------------

def _body_font_size(chars: list[dict]) -> float:
    """Median character font size across the page — used as body baseline."""
    sizes = [c["size"] for c in chars if c.get("size", 0) > 0]
    if not sizes:
        return 10.0
    return statistics.median(sizes)


# ---------------------------------------------------------------------------
# Word → line → paragraph clustering
# ---------------------------------------------------------------------------

def _cluster_into_lines(words: list[dict], y_tolerance: float = 3.0) -> list[list[dict]]:
    """Group words that share approximately the same vertical midpoint."""
    if not words:
        return []
    words = sorted(words, key=lambda w: (round(w["top"] / y_tolerance), w["x0"]))
    lines: list[list[dict]] = []
    current_line: list[dict] = [words[0]]
    current_y = words[0]["top"]

    for w in words[1:]:
        if abs(w["top"] - current_y) <= y_tolerance:
            current_line.append(w)
        else:
            lines.append(current_line)
            current_line = [w]
            current_y = w["top"]
    lines.append(current_line)
    return lines


def _line_median_size(line: list[dict]) -> float:
    sizes = [w.get("size", 0) for w in line if w.get("size", 0) > 0]
    return statistics.median(sizes) if sizes else 0.0


def _cluster_into_paragraphs(
    lines: list[list[dict]], line_gap_multiplier: float = 1.6
) -> list[list[list[dict]]]:
    """
    Group lines into paragraphs.

    Split when either:
    - vertical gap > line_gap_multiplier × typical gap, OR
    - font size changes by more than 8 % between consecutive lines
      (heading-to-body or body-to-heading transitions).
    """
    if not lines:
        return []

    tops = [line[0]["top"] for line in lines]
    gaps = [tops[i + 1] - tops[i] for i in range(len(tops) - 1)]
    typical_gap = statistics.median(gaps) if gaps else 12.0

    paragraphs: list[list[list[dict]]] = []
    current_para = [lines[0]]

    for i in range(1, len(lines)):
        gap = lines[i][0]["top"] - lines[i - 1][0]["top"]
        prev_size = _line_median_size(lines[i - 1])
        curr_size = _line_median_size(lines[i])

        size_jump = (
            prev_size > 0
            and curr_size > 0
            and abs(curr_size - prev_size) / max(prev_size, curr_size) > 0.08
        )

        if gap > typical_gap * line_gap_multiplier or size_jump:
            paragraphs.append(current_para)
            current_para = [lines[i]]
        else:
            current_para.append(lines[i])

    paragraphs.append(current_para)
    return paragraphs


# ---------------------------------------------------------------------------
# Document-level heading size map
# ---------------------------------------------------------------------------

def _build_heading_size_map(
    all_chars: list[dict], body_size: float, cluster_tol: float = 0.08
) -> dict[float, int]:
    """
    Analyse every character across the whole document to build a mapping
    {rounded_size -> heading_level (1|2|3)}.

    Sizes within cluster_tol (8 %) of each other are collapsed into one level.
    The largest cluster becomes H1, second H2, third H3.
    """
    above_body = [
        round(c["size"], 1)
        for c in all_chars
        if c.get("size", 0) > body_size * 1.04
    ]
    if not above_body:
        return {}

    unique_sizes = sorted(set(above_body), reverse=True)

    # Cluster nearby sizes
    clusters: list[list[float]] = []
    for s in unique_sizes:
        placed = False
        for cluster in clusters:
            rep = cluster[0]
            if abs(s - rep) / max(s, rep) <= cluster_tol:
                cluster.append(s)
                placed = True
                break
        if not placed:
            clusters.append([s])

    size_map: dict[float, int] = {}
    for level, cluster in enumerate(clusters[:3], start=1):
        for s in cluster:
            size_map[s] = level

    return size_map


def _lookup_heading_level(size: float, size_map: dict[float, int]) -> int | None:
    """Return heading level for a given size, or None if not a heading."""
    rounded = round(size, 1)
    if rounded in size_map:
        return size_map[rounded]
    # Fuzzy lookup: nearest key within 5 %
    for k, v in size_map.items():
        if abs(k - size) / max(k, size) <= 0.05:
            return v
    return None


# ---------------------------------------------------------------------------
# Heading classification
# ---------------------------------------------------------------------------

def _classify_paragraph(
    para_lines: list[list[dict]],
    body_size: float,
    page_chars: list[dict],
    heading_size_map: dict[float, int],
) -> tuple[str, int, float, bool]:
    """
    Return (block_type, heading_level, dominant_font_size, is_bold).
    """
    all_text = " ".join(w["text"] for line in para_lines for w in line).strip()
    sizes: list[float] = []
    bold_count = 0
    word_count = 0

    for line in para_lines:
        for w in line:
            word_count += 1
            wx0, wt, wx1, wb = w["x0"], w["top"], w["x1"], w["bottom"]
            matching = [
                c for c in page_chars
                if c.get("size", 0) > 0
                and wx0 - 1 <= c["x0"] <= wx1 + 1
                and wt - 2 <= c["top"] <= wb + 2
            ]
            if matching:
                sizes.append(statistics.median(c["size"] for c in matching))
                if any(_is_bold(c.get("fontname", "")) for c in matching):
                    bold_count += 1

    dominant_size = statistics.median(sizes) if sizes else body_size
    is_bold = bold_count > word_count * 0.5
    is_upper = all_text.isupper() and len(all_text) > 2

    # Primary: document-level size map
    h_level = _lookup_heading_level(dominant_size, heading_size_map)
    if h_level is not None:
        return "heading", h_level, dominant_size, is_bold

    # Fallback for bold-only or all-caps headings at body size
    ratio = dominant_size / body_size if body_size > 0 else 1.0
    if (is_bold and ratio >= 0.95 and len(all_text.split()) <= 12) or is_upper:
        return "heading", 3, dominant_size, is_bold

    if _LIST_BULLETS.match(all_text):
        return "list_item", 0, dominant_size, is_bold

    return "paragraph", 0, dominant_size, is_bold


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

def _extract_tables(page: Any, page_num: int) -> list[TableBlock]:
    tables = []
    try:
        for tbl in page.find_tables(table_settings={"vertical_strategy": "lines",
                                                     "horizontal_strategy": "lines"}):
            data = tbl.extract()
            if not data:
                continue
            # Normalise None cells to empty string
            cleaned = [
                [cell if cell is not None else "" for cell in row]
                for row in data
            ]
            tables.append(TableBlock(rows=cleaned, page_num=page_num, bbox=tbl.bbox))
    except Exception:
        pass
    return tables


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------

def extract_page(
    page: Any,
    page_num: int,
    heading_size_map: dict[float, int] | None = None,
    body_size: float | None = None,
) -> PageContent:
    content = PageContent(page_num=page_num)

    # 1. Tables
    table_blocks = _extract_tables(page, page_num)
    table_bboxes = [t.bbox for t in table_blocks]

    # 2. Font baseline from all chars on page (use doc-level value if provided)
    chars = page.chars or []
    if body_size is None:
        body_size = _body_font_size(chars)
    if heading_size_map is None:
        heading_size_map = {}

    # 3. Words outside table regions
    try:
        words = page.extract_words(
            x_tolerance=3,
            y_tolerance=3,
            keep_blank_chars=False,
            use_text_flow=True,
            extra_attrs=["fontname", "size"],
        )
    except Exception:
        words = []

    # Filter out words inside any table bounding box
    free_words = [
        w for w in words
        if not any(_point_in_bbox(w["x0"], w["top"], bbox) for bbox in table_bboxes)
    ]

    # 4. Detect columns and assign each word a column index
    columns = _detect_columns(free_words)
    for w in free_words:
        w["_col"] = _column_index(w["x0"], columns)

    # 5. Sort words: by column, then top, then left
    free_words.sort(key=lambda w: (w["_col"], w["top"], w["x0"]))

    # Process each column independently, preserving order
    col_groups: dict[int, list[dict]] = {}
    for w in free_words:
        col_groups.setdefault(w["_col"], []).append(w)

    text_blocks: list[TextBlock] = []
    for col_idx in sorted(col_groups):
        col_words = col_groups[col_idx]
        lines = _cluster_into_lines(col_words)
        paragraphs = _cluster_into_paragraphs(lines)

        for para_lines in paragraphs:
            raw_text = " ".join(
                " ".join(w["text"] for w in line)
                for line in para_lines
            ).strip()
            if not raw_text:
                continue

            block_type, h_level, font_size, is_bold = _classify_paragraph(
                para_lines, body_size, chars, heading_size_map
            )

            # Bounding box of the whole paragraph
            all_ws = [w for line in para_lines for w in line]
            bbox = (
                min(w["x0"] for w in all_ws),
                min(w["top"] for w in all_ws),
                max(w["x1"] for w in all_ws),
                max(w["bottom"] for w in all_ws),
            )

            tb = TextBlock(
                text=raw_text,
                page_num=page_num,
                bbox=bbox,
                font_size=font_size,
                is_bold=is_bold,
                block_type=block_type,
                heading_level=h_level,
            )
            text_blocks.append(tb)

    # 6. Merge tables and text blocks in vertical reading order
    #    Use the top-y of each block's bbox for ordering.
    all_items: list[tuple[float, int, TableBlock | TextBlock]] = []
    for tb in text_blocks:
        all_items.append((tb.bbox[1], 0, tb))
    for tbl in table_blocks:
        all_items.append((tbl.bbox[1], 1, tbl))

    all_items.sort(key=lambda x: (x[0], x[1]))
    content.blocks = [item for _, _, item in all_items]
    return content


def extract_pdf(path: str, progress_cb=None) -> list[PageContent]:
    """
    Two-pass extraction:
      Pass 1 — collect all chars to build document-level body size + heading map.
      Pass 2 — extract each page using the shared map.
    progress_cb(current_page, total_pages) is called after each page.
    """
    pages: list[PageContent] = []
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)

        # Pass 1: document-level font analysis
        all_chars: list[dict] = []
        for page in pdf.pages:
            all_chars.extend(page.chars or [])

        doc_body_size = _body_font_size(all_chars)
        heading_size_map = _build_heading_size_map(all_chars, doc_body_size)

        # Pass 2: page extraction
        for i, page in enumerate(pdf.pages):
            pages.append(
                extract_page(page, i + 1,
                             heading_size_map=heading_size_map,
                             body_size=doc_body_size)
            )
            if progress_cb:
                progress_cb(i + 1, total)

    return pages
