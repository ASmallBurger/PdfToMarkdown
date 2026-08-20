"""
PdfToMarkdown GUI.

A modern Tkinter UI built on customtkinter, with drag-and-drop support via
tkinterdnd2 and a file queue showing per-file status.

Layout:
    ┌──────────────────────────────────────────────┐
    │  Header (title + theme toggle)               │
    │  Drop-zone (drag PDFs here / browse buttons) │
    │  Output-folder picker                        │
    │  Queue (file list with status icons)         │
    │  Progress bar + status label                 │
    │  Options + action buttons                    │
    └──────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD


APP_VERSION = "1.0"
APP_TITLE = "PDF → Markdown"
PREFS_FILE = Path.home() / ".pdftomarkdown_prefs.json"

# Status icons for the queue list
STATUS_PENDING = "○"
STATUS_ACTIVE = "▶"
STATUS_DONE = "✓"
STATUS_ERROR = "✕"


# ---------------------------------------------------------------------------
# Small data type for queue rows
# ---------------------------------------------------------------------------

@dataclass
class QueueItem:
    path: Path
    status: str = "pending"   # pending | active | done | error
    message: str = ""
    pages: int = 0


# ---------------------------------------------------------------------------
# Preferences (last-used folders)
# ---------------------------------------------------------------------------

def _load_prefs() -> dict:
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_prefs(data: dict) -> None:
    try:
        PREFS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class App(ctk.CTk, TkinterDnD.DnDWrapper):
    """customtkinter window with tkinterdnd2 drag-drop support."""

    def __init__(self):
        super().__init__()
        # Wire drag-drop into the customtkinter root
        self.TkdndVersion = TkinterDnD._require(self)

        # Theme
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title(f"{APP_TITLE}  ·  v{APP_VERSION}")
        self.geometry("780x640")
        self.minsize(680, 560)

        # State
        self._queue_items: list[QueueItem] = []
        self._row_widgets: dict[int, dict] = {}  # idx -> {"icon":..., "name":..., "info":...}
        self._msg_queue: queue.Queue = queue.Queue()
        self._converting = False
        self._prefs = _load_prefs()

        self._build_ui()

        # Restore last output folder
        last_out = self._prefs.get("output_dir", "")
        if last_out:
            self._out_var.set(last_out)

        # Start polling worker messages
        self.after(100, self._poll_messages)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)   # queue area expands

        # ── Header ─────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=APP_TITLE,
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self._theme_btn = ctk.CTkSegmentedButton(
            header,
            values=["Light", "Dark", "System"],
            command=self._on_theme_change,
            width=200,
        )
        self._theme_btn.set(self._prefs.get("theme", "System"))
        self._theme_btn.grid(row=0, column=1, sticky="e")

        # ── Drop zone ──────────────────────────────────────────────────
        self._drop_frame = ctk.CTkFrame(
            self, height=110, corner_radius=12, border_width=2,
        )
        self._drop_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(8, 6))
        self._drop_frame.grid_propagate(False)
        self._drop_frame.grid_columnconfigure(0, weight=1)
        self._drop_frame.grid_rowconfigure(0, weight=1)
        self._drop_frame.grid_rowconfigure(1, weight=0)

        self._drop_label = ctk.CTkLabel(
            self._drop_frame,
            text="Drop PDF files or a folder here",
            font=ctk.CTkFont(size=14),
        )
        self._drop_label.grid(row=0, column=0, pady=(14, 2))

        btn_row = ctk.CTkFrame(self._drop_frame, fg_color="transparent")
        btn_row.grid(row=1, column=0, pady=(0, 12))
        ctk.CTkButton(
            btn_row, text="Browse files…", width=130,
            command=self._pick_files,
        ).grid(row=0, column=0, padx=6)
        ctk.CTkButton(
            btn_row, text="Browse folder…", width=130,
            command=self._pick_folder,
        ).grid(row=0, column=1, padx=6)
        ctk.CTkButton(
            btn_row, text="Clear queue", width=110,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
            border_color=("gray70", "gray40"),
            hover_color=("gray90", "gray25"),
            command=self._clear_queue,
        ).grid(row=0, column=2, padx=6)

        # Register drag-drop on the drop frame and its children
        for widget in (self._drop_frame, self._drop_label):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

        # ── Output folder ──────────────────────────────────────────────
        out_frame = ctk.CTkFrame(self, fg_color="transparent")
        out_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(2, 6))
        out_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(out_frame, text="Output:", width=70, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        self._out_var = ctk.StringVar(value="")
        self._out_entry = ctk.CTkEntry(out_frame, textvariable=self._out_var)
        self._out_entry.grid(row=0, column=1, sticky="ew", padx=(4, 8))
        ctk.CTkButton(
            out_frame, text="Choose…", width=90,
            command=self._pick_out_folder,
        ).grid(row=0, column=2)

        # ── Queue (scrollable) ─────────────────────────────────────────
        queue_label_row = ctk.CTkFrame(self, fg_color="transparent")
        queue_label_row.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 0))
        queue_label_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            queue_label_row, text="Queue",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self._queue_count_label = ctk.CTkLabel(
            queue_label_row, text="0 files",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"),
        )
        self._queue_count_label.grid(row=0, column=1, sticky="e")

        self._queue_view = ctk.CTkScrollableFrame(self, height=170)
        self._queue_view.grid(row=4, column=0, sticky="nsew", padx=20, pady=(2, 6))
        self._queue_view.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self.grid_rowconfigure(3, weight=0)

        self._empty_label = ctk.CTkLabel(
            self._queue_view, text="(no files added yet)",
            text_color=("gray50", "gray50"),
        )
        self._empty_label.grid(row=0, column=0, pady=20)

        # ── Progress + status ──────────────────────────────────────────
        prog_frame = ctk.CTkFrame(self, fg_color="transparent")
        prog_frame.grid(row=5, column=0, sticky="ew", padx=20, pady=(4, 4))
        prog_frame.grid_columnconfigure(0, weight=1)

        self._status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(
            prog_frame, textvariable=self._status_var, anchor="w",
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, sticky="w")

        self._progress = ctk.CTkProgressBar(prog_frame, height=10)
        self._progress.set(0)
        self._progress.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        # ── Options + actions ──────────────────────────────────────────
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.grid(row=6, column=0, sticky="ew", padx=20, pady=(8, 16))
        action_frame.grid_columnconfigure(0, weight=1)

        self._page_breaks_var = ctk.BooleanVar(
            value=self._prefs.get("page_breaks", False)
        )
        ctk.CTkCheckBox(
            action_frame,
            text="Insert page-break markers in output",
            variable=self._page_breaks_var,
        ).grid(row=0, column=0, sticky="w")

        self._convert_btn = ctk.CTkButton(
            action_frame, text="Convert all", width=130,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start_conversion,
        )
        self._convert_btn.grid(row=0, column=1, padx=(8, 4))

        self._open_out_btn = ctk.CTkButton(
            action_frame, text="Open output", width=110,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
            border_color=("gray70", "gray40"),
            hover_color=("gray90", "gray25"),
            command=self._open_output_folder,
        )
        self._open_out_btn.grid(row=0, column=2, padx=(4, 0))

    # ------------------------------------------------------------------
    # Theme handling
    # ------------------------------------------------------------------

    def _on_theme_change(self, value: str):
        ctk.set_appearance_mode(value)
        self._prefs["theme"] = value
        _save_prefs(self._prefs)

    # ------------------------------------------------------------------
    # Drag-and-drop handler
    # ------------------------------------------------------------------

    def _on_drop(self, event):
        """tkinterdnd2 returns a brace-enclosed string of paths for multi-file drops."""
        raw = event.data
        paths = self._parse_dropped_paths(raw)
        self._add_paths(paths)

    @staticmethod
    def _parse_dropped_paths(raw: str) -> list[str]:
        """
        DnD returns paths like:  {/path/with spaces/a.pdf} /path/no-spaces/b.pdf
        Split respecting brace grouping.
        """
        out, buf, in_brace = [], "", False
        for ch in raw:
            if ch == "{":
                in_brace = True
                continue
            if ch == "}":
                in_brace = False
                continue
            if ch == " " and not in_brace:
                if buf:
                    out.append(buf)
                    buf = ""
                continue
            buf += ch
        if buf:
            out.append(buf)
        return out

    # ------------------------------------------------------------------
    # File pickers
    # ------------------------------------------------------------------

    def _pick_files(self):
        last_dir = self._prefs.get("source_dir", "")
        paths = filedialog.askopenfilenames(
            title="Select PDF files",
            initialdir=last_dir or None,
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if paths:
            self._prefs["source_dir"] = str(Path(paths[0]).parent)
            _save_prefs(self._prefs)
            self._add_paths(list(paths))

    def _pick_folder(self):
        last_dir = self._prefs.get("source_dir", "")
        folder = filedialog.askdirectory(
            title="Select folder containing PDFs",
            initialdir=last_dir or None,
        )
        if folder:
            self._prefs["source_dir"] = folder
            _save_prefs(self._prefs)
            self._add_paths([folder])

    def _pick_out_folder(self):
        last_dir = self._out_var.get() or self._prefs.get("output_dir", "")
        folder = filedialog.askdirectory(
            title="Choose output folder",
            initialdir=last_dir or None,
        )
        if folder:
            self._out_var.set(folder)
            self._prefs["output_dir"] = folder
            _save_prefs(self._prefs)

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _add_paths(self, paths: list[str]):
        added = 0
        for raw in paths:
            p = Path(raw.strip())
            if not p.exists():
                continue
            if p.is_dir():
                pdfs = sorted(p.glob("*.pdf"))
                for pdf in pdfs:
                    if self._add_one(pdf):
                        added += 1
            elif p.suffix.lower() == ".pdf":
                if self._add_one(p):
                    added += 1

        if added:
            self._refresh_queue_view()
            self._status_var.set(f"Added {added} file(s) to queue")

    def _add_one(self, path: Path) -> bool:
        if any(item.path == path for item in self._queue_items):
            return False
        self._queue_items.append(QueueItem(path=path))
        return True

    def _clear_queue(self):
        if self._converting:
            return
        self._queue_items.clear()
        self._refresh_queue_view()
        self._progress.set(0)
        self._status_var.set("Ready")

    def _refresh_queue_view(self):
        # Wipe existing rows
        for child in self._queue_view.winfo_children():
            child.destroy()
        self._row_widgets.clear()

        if not self._queue_items:
            self._empty_label = ctk.CTkLabel(
                self._queue_view, text="(no files added yet)",
                text_color=("gray50", "gray50"),
            )
            self._empty_label.grid(row=0, column=0, pady=20)
            self._queue_count_label.configure(text="0 files")
            return

        for idx, item in enumerate(self._queue_items):
            self._build_row(idx, item)

        self._queue_count_label.configure(text=f"{len(self._queue_items)} files")

    def _build_row(self, idx: int, item: QueueItem):
        icon = ctk.CTkLabel(
            self._queue_view, text=STATUS_PENDING, width=24,
            font=ctk.CTkFont(size=14),
        )
        icon.grid(row=idx, column=0, sticky="w", padx=(4, 6), pady=2)

        name = ctk.CTkLabel(
            self._queue_view, text=item.path.name, anchor="w",
        )
        name.grid(row=idx, column=1, sticky="ew", pady=2)

        info = ctk.CTkLabel(
            self._queue_view, text="", anchor="e",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
        )
        info.grid(row=idx, column=2, sticky="e", padx=(6, 4), pady=2)

        self._row_widgets[idx] = {"icon": icon, "name": name, "info": info}
        self._update_row(idx, item)

    def _update_row(self, idx: int, item: QueueItem):
        widgets = self._row_widgets.get(idx)
        if not widgets:
            return
        icon_map = {
            "pending": (STATUS_PENDING, ("gray50", "gray60")),
            "active": (STATUS_ACTIVE, ("#1f6aa5", "#3a86ff")),
            "done": (STATUS_DONE, ("#0a8b3a", "#2ecc71")),
            "error": (STATUS_ERROR, ("#b32d2d", "#e74c3c")),
        }
        ch, color = icon_map.get(item.status, (STATUS_PENDING, ("gray50", "gray60")))
        widgets["icon"].configure(text=ch, text_color=color)
        widgets["info"].configure(text=item.message)

    # ------------------------------------------------------------------
    # Conversion (worker thread)
    # ------------------------------------------------------------------

    def _start_conversion(self):
        if self._converting:
            return
        if not self._queue_items:
            messagebox.showwarning(
                "Empty queue",
                "Add some PDF files to the queue first."
            )
            return
        out = self._out_var.get().strip()
        if not out:
            messagebox.showwarning(
                "No output folder",
                "Please choose an output folder."
            )
            return

        out_path = Path(out)
        try:
            out_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("Cannot create output folder", str(exc))
            return

        self._prefs["output_dir"] = str(out_path)
        self._prefs["page_breaks"] = self._page_breaks_var.get()
        _save_prefs(self._prefs)

        # Reset all items to pending
        for item in self._queue_items:
            item.status = "pending"
            item.message = ""
        self._refresh_queue_view()

        self._converting = True
        self._convert_btn.configure(state="disabled", text="Converting…")
        self._progress.set(0)

        thread = threading.Thread(
            target=self._run_conversion,
            args=(out_path, self._page_breaks_var.get()),
            daemon=True,
        )
        thread.start()

    def _run_conversion(self, out_dir: Path, page_breaks: bool):
        # Imported here so importing the GUI module doesn't pull in pdfplumber
        from parser.processor import process_file

        q = self._msg_queue
        total = len(self._queue_items)

        for idx, item in enumerate(list(self._queue_items)):
            q.put(("status", f"File {idx + 1} of {total}  ·  {item.path.name}"))
            q.put(("row", idx, "active", "converting…"))

            page_state = {"current": 0, "total": 0}

            def page_cb(cur: int, tot: int, _idx=idx, _state=page_state):
                _state["current"] = cur
                _state["total"] = tot
                q.put((
                    "status",
                    f"File {_idx + 1} of {total}  ·  Page {cur} of {tot}  "
                    f"·  {self._queue_items[_idx].path.name}"
                ))
                # Combined progress: completed files + fraction of current
                file_frac = cur / tot if tot else 0
                overall = (_idx + file_frac) / total
                q.put(("progress", overall))

            try:
                process_file(
                    item.path, out_dir,
                    include_page_breaks=page_breaks,
                    progress_cb=page_cb,
                )
                pages = page_state["total"] or page_state["current"]
                msg = f"{pages} page{'s' if pages != 1 else ''}"
                q.put(("row", idx, "done", msg))
            except Exception as exc:
                q.put(("row", idx, "error", _short_error(exc)))

            q.put(("progress", (idx + 1) / total))

        q.put(("done", out_dir))

    # ------------------------------------------------------------------
    # Worker → UI message pump
    # ------------------------------------------------------------------

    def _poll_messages(self):
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self._status_var.set(msg[1])
                elif kind == "progress":
                    self._progress.set(min(max(msg[1], 0), 1))
                elif kind == "row":
                    _, idx, status, message = msg
                    if 0 <= idx < len(self._queue_items):
                        self._queue_items[idx].status = status
                        self._queue_items[idx].message = message
                        self._update_row(idx, self._queue_items[idx])
                elif kind == "done":
                    self._on_done(msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_messages)

    def _on_done(self, out_dir: Path):
        self._converting = False
        self._convert_btn.configure(state="normal", text="Convert all")
        self._progress.set(1)

        ok = sum(1 for it in self._queue_items if it.status == "done")
        bad = sum(1 for it in self._queue_items if it.status == "error")

        if bad == 0:
            self._status_var.set(f"Done · {ok} file(s) converted")
            messagebox.showinfo(
                "Conversion complete",
                f"{ok} file(s) converted to:\n\n{out_dir}",
            )
        else:
            self._status_var.set(f"Finished · {ok} ok · {bad} failed")
            messagebox.showwarning(
                "Conversion finished with errors",
                f"{ok} succeeded, {bad} failed.\n\n"
                "Check the queue list: errored files have a red mark.",
            )

    # ------------------------------------------------------------------
    # Open output folder in OS file manager
    # ------------------------------------------------------------------

    def _open_output_folder(self):
        path = self._out_var.get().strip()
        if not path or not Path(path).exists():
            messagebox.showwarning(
                "No output folder",
                "Choose a valid output folder first."
            )
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Could not open folder", str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_error(exc: Exception) -> str:
    """Convert exceptions to short user-friendly messages."""
    text = str(exc).strip()
    lower = text.lower()
    if "password" in lower or "encrypted" in lower:
        return "encrypted PDF"
    if "not a pdf" in lower or "syntax" in lower:
        return "invalid or corrupt PDF"
    if not text:
        return type(exc).__name__
    if len(text) > 60:
        return text[:57] + "…"
    return text
