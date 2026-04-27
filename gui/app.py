"""
Tkinter GUI for PdfToMarkdown.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF → Markdown")
        self.resizable(False, False)
        self._queue: queue.Queue = queue.Queue()
        self._build_ui()
        self._poll_queue()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        PAD = {"padx": 10, "pady": 6}

        # ── Source ──────────────────────────────────────────────────────
        src_frame = ttk.LabelFrame(self, text="Source")
        src_frame.grid(row=0, column=0, columnspan=3, sticky="ew", **PAD)

        self._src_var = tk.StringVar()
        ttk.Entry(src_frame, textvariable=self._src_var, width=52).grid(
            row=0, column=0, padx=(8, 4), pady=6
        )
        ttk.Button(src_frame, text="File…", command=self._pick_file).grid(
            row=0, column=1, padx=2
        )
        ttk.Button(src_frame, text="Folder…", command=self._pick_src_folder).grid(
            row=0, column=2, padx=(2, 8)
        )

        # ── Output ──────────────────────────────────────────────────────
        out_frame = ttk.LabelFrame(self, text="Output folder")
        out_frame.grid(row=1, column=0, columnspan=3, sticky="ew", **PAD)

        self._out_var = tk.StringVar()
        ttk.Entry(out_frame, textvariable=self._out_var, width=52).grid(
            row=0, column=0, padx=(8, 4), pady=6
        )
        ttk.Button(out_frame, text="Browse…", command=self._pick_out_folder).grid(
            row=0, column=1, padx=(2, 8)
        )

        # ── Options ─────────────────────────────────────────────────────
        opt_frame = ttk.Frame(self)
        opt_frame.grid(row=2, column=0, columnspan=3, sticky="w", padx=10)

        self._page_breaks_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt_frame, text="Insert page-break markers", variable=self._page_breaks_var
        ).grid(row=0, column=0, sticky="w")

        # ── Progress ────────────────────────────────────────────────────
        self._file_progress = ttk.Progressbar(self, length=440, mode="determinate")
        self._file_progress.grid(row=3, column=0, columnspan=3, padx=10, pady=(8, 0))

        self._page_progress = ttk.Progressbar(
            self, length=440, mode="determinate", style="Accent.Horizontal.TProgressbar"
        )
        self._page_progress.grid(row=4, column=0, columnspan=3, padx=10, pady=(4, 0))

        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self._status_var, anchor="w").grid(
            row=5, column=0, columnspan=3, sticky="w", padx=12
        )

        # ── Log ─────────────────────────────────────────────────────────
        self._log = scrolledtext.ScrolledText(
            self, width=62, height=12, state="disabled", font=("Consolas", 9)
        )
        self._log.grid(row=6, column=0, columnspan=3, padx=10, pady=6)

        # ── Buttons ─────────────────────────────────────────────────────
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=7, column=0, columnspan=3, pady=(0, 10))

        self._run_btn = ttk.Button(btn_frame, text="Convert", command=self._start)
        self._run_btn.grid(row=0, column=0, padx=6)
        ttk.Button(btn_frame, text="Clear log", command=self._clear_log).grid(
            row=0, column=1, padx=6
        )

    # ------------------------------------------------------------------
    # Pickers
    # ------------------------------------------------------------------

    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="Select PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._src_var.set(path)

    def _pick_src_folder(self):
        path = filedialog.askdirectory(title="Select folder with PDFs")
        if path:
            self._src_var.set(path)

    def _pick_out_folder(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self._out_var.set(path)

    # ------------------------------------------------------------------
    # Queue-based thread communication
    # ------------------------------------------------------------------

    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                self._handle_msg(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _handle_msg(self, msg: dict):
        kind = msg["kind"]
        if kind == "log":
            self._append_log(msg["text"])
        elif kind == "status":
            self._status_var.set(msg["text"])
        elif kind == "file_progress":
            self._file_progress["maximum"] = msg["total"]
            self._file_progress["value"] = msg["current"]
        elif kind == "page_progress":
            self._page_progress["maximum"] = msg["total"]
            self._page_progress["value"] = msg["current"]
        elif kind == "done":
            self._run_btn.configure(state="normal")
            self._status_var.set(msg["text"])
            messagebox.showinfo("Done", msg["text"])

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def _append_log(self, text: str):
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def _start(self):
        src = self._src_var.get().strip()
        out = self._out_var.get().strip()

        if not src:
            messagebox.showwarning("Missing source", "Please select a source file or folder.")
            return
        if not out:
            messagebox.showwarning("Missing output", "Please select an output folder.")
            return

        self._run_btn.configure(state="disabled")
        self._file_progress["value"] = 0
        self._page_progress["value"] = 0
        self._status_var.set("Working…")

        include_breaks = self._page_breaks_var.get()
        thread = threading.Thread(
            target=self._run_conversion,
            args=(src, out, include_breaks),
            daemon=True,
        )
        thread.start()

    def _run_conversion(self, src: str, out: str, include_breaks: bool):
        from parser.processor import process_file, process_folder

        q = self._queue

        def log(text: str):
            q.put({"kind": "log", "text": text})

        def file_prog(current: int, total: int):
            q.put({"kind": "file_progress", "current": current, "total": total})

        def page_prog(current: int, total: int):
            q.put({"kind": "page_progress", "current": current, "total": total})

        try:
            src_path = Path(src)
            if src_path.is_file() and src_path.suffix.lower() == ".pdf":
                process_file(
                    src_path,
                    out,
                    include_page_breaks=include_breaks,
                    progress_cb=page_prog,
                    log_cb=log,
                )
                file_prog(1, 1)
                q.put({"kind": "done", "text": "Conversion complete."})

            elif src_path.is_dir():
                results = process_folder(
                    src_path,
                    out,
                    include_page_breaks=include_breaks,
                    file_progress_cb=file_prog,
                    page_progress_cb=page_prog,
                    log_cb=log,
                )
                q.put({
                    "kind": "done",
                    "text": f"Done. {len(results)} file(s) converted."
                })
            else:
                q.put({"kind": "log", "text": f"ERROR: Not a PDF or folder: {src}"})
                q.put({"kind": "done", "text": "Aborted — see log."})

        except Exception as exc:
            q.put({"kind": "log", "text": f"ERROR: {exc}"})
            q.put({"kind": "done", "text": "Failed — see log."})
