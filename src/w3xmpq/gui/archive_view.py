# -*- coding: utf-8 -*-
"""One archive, one pane.

:class:`ArchiveView` composes the widgets that belong to a *single* open
archive: the summary strip, filter chips, folder tree, model-backed file
table, preview pane and analysis drawer.  The 946-line "does everything"
module is gone; each of those lives in its own file now.

    MainWindow (tab host + shared TaskManager)
      └ ArchiveView
          ├ SummaryStrip        verdict + primary actions
          ├ FilterChips        counts from the model
          ├ QSplitter          FolderTree │ FileTable │ PreviewPane
          └ AnalysisDrawer     Report / Safety / Tasks

Per-archive state (entries, selection, filters, layout) lives here; nothing
leaks between tabs.  Background work goes through the shared
:class:`~w3xmpq.gui.tasks.TaskManager`, so opening a second map or running
a rebuild never blocks browsing this one.
"""

import os
import re

from PySide6.QtCore import Qt, QByteArray, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLineEdit, QMenu,
                               QSplitter, QVBoxLayout, QWidget)

from ..core import filetypes
from ..core.report import build_report, render_report
from ..core.safety import scan_safety, render_safety
from . import theme
from .analysis_drawer import AnalysisDrawer
from .chips import FilterChips
from .dialogs import ARCHIVE_FILTER, open_folder
from .file_model import FileTable
from .folder_tree import FolderTree
from .preview_pane import PreviewPane, preview_text            # noqa: F401
from .summary_strip import SummaryStrip
from .tasks import TaskManager
from .workers import (ExtractWorker, FnWorker, RebuildWorker, ScanWorker)

__all__ = ["ArchiveView", "ARCHIVE_FILTER", "preview_text"]


class ArchiveView(QWidget):
    """Everything about one open archive, ready to sit in a tab."""

    status = Signal(str)
    busy = Signal(bool)
    title_changed = Signal()
    loaded = Signal()
    open_failed = Signal(str)

    def __init__(self, path, settings=None, tasks=None, layout=None,
                 parent=None):
        super().__init__(parent)
        self.current_path = path
        self.current_entries = None
        self.current_folder = None
        self.settings = settings
        self.tasks = tasks or TaskManager(self)
        self._scan_job = None
        self._report = None
        self._safety = None
        self._build_ui()
        if layout:
            self.restore_layout_state(layout)
        self.summary_strip.set_scanning(path)

    # ------------------------------------------------------------ title
    @property
    def title(self):
        return os.path.basename(self.current_path or "archive")

    def summary(self):
        if not self.current_entries:
            return self.current_path or ""
        ok = sum(1 for e in self.current_entries
                 if not filetypes.is_failed(e))
        return "%s\n%d of %d blocks recovered" % (
            self.current_path, ok, len(self.current_entries))

    @property
    def worker(self):
        """The active scan thread, or None (kept for callers/tests)."""
        job = self._scan_job
        return job.worker if job is not None and job.active else None

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        self.summary_strip = SummaryStrip()
        self.chips = FilterChips()
        self.folders = FolderTree()
        self.table = FileTable()
        self.preview = PreviewPane()
        self.drawer = AnalysisDrawer(self.tasks, owner=self.current_path)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("filter files\u2026 (Ctrl+F)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filters)
        self._filter_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._filter_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._filter_shortcut.activated.connect(self.filter_edit.setFocus)

        self.table.selectionModel().selectionChanged.connect(
            lambda _sel, _old: self._preview_selected())
        self.table.doubleClicked.connect(self._focus_preview)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.chips.changed.connect(self._apply_filters)
        self.folders.folder_selected.connect(self.apply_folder_filter)
        self.preview.save_requested.connect(self.save_preview)
        self.preview.status.connect(self.status.emit)
        if self.drawer is not None:
            self.drawer.file_requested.connect(self.jump_to)

        self.summary_strip.rebuild_clicked.connect(self.rebuild)
        self.summary_strip.extract_all_clicked.connect(self.extract)
        self.summary_strip.extract_selected_clicked.connect(
            self.extract_selected)
        self.summary_strip.export_clicked.connect(self.export_table)
        self.summary_strip.safety_clicked.connect(self.safety_scan)
        self.summary_strip.report_clicked.connect(self.report)

        self.splitter = QSplitter()
        self.splitter.addWidget(self.folders)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setSizes([180, 470, 450])

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addWidget(self.chips, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)
        layout.addWidget(self.summary_strip)
        layout.addLayout(filter_row)
        layout.addWidget(self.splitter, 1)
        if self.drawer is not None:
            layout.addWidget(self.drawer)

    # --------------------------------------------------------- scanning
    def start_scan(self):
        self.status.emit("Scanning %s\u2026"
                         % os.path.basename(self.current_path))
        self.summary_strip.set_scanning(self.current_path)
        worker = ScanWorker(self.current_path)
        self.busy.emit(True)
        self._scan_job = self.tasks.submit(
            "Scan %s" % os.path.basename(self.current_path), worker,
            on_done=self._on_scanned, on_failed=self._on_task_failed,
            owner=self.current_path)

    def cancel_scan(self):
        if self._scan_job is not None:
            self.tasks.cancel(self._scan_job)
            self.status.emit("Cancelling scan\u2026")

    def _on_scanned(self, entries):
        self.current_entries = entries
        self.current_folder = None
        self.table.load_entries(entries)
        self.folders.load_entries(entries)
        self.chips.set_counts(self.table.counts())
        self.preview.clear()
        self.summary_strip.set_metadata(self.current_path)
        self.summary_strip.set_entries(entries)
        self.summary_strip.set_safety(running=True)
        self.table.select_first_ok()
        self._apply_filters()
        ok = sum(1 for e in entries if not filetypes.is_failed(e))
        self.status.emit("%d blocks: %d recovered, %d failed \u2014 %s"
                         % (len(entries), ok, len(entries) - ok,
                            self.current_path))
        self.busy.emit(False)
        self.title_changed.emit()
        self.loaded.emit()
        self._run_analysis()

    def _on_task_failed(self, err):
        self.summary_strip.headline.setText("Could not read this archive")
        self.summary_strip.detail.setText("See the Tasks tab for details.")
        self.busy.emit(False)
        self.open_failed.emit(err)

    # --------------------------------------------------------- analysis
    def _run_analysis(self):
        """Report + safety run automatically, reusing the scan in memory."""
        entries = self.current_entries
        if self.drawer is not None:
            self.drawer.set_safety(None, running=True)
        self.summary_strip.set_safety(running=True)

        def analyse(path, ent=entries):
            return (build_report(path, entries=ent),
                    scan_safety(path, entries=ent))

        self.tasks.submit(
            "Analyse %s" % os.path.basename(self.current_path),
            FnWorker(analyse, self.current_path),
            on_done=self._on_analysis,
            on_failed=lambda err: self.status.emit("Analysis failed: %s"
                                                   % err),
            owner=self.current_path)

    def _on_analysis(self, result):
        report, safety = result
        self._report, self._safety = report, safety
        self.summary_strip.set_safety(safety)
        self.summary_strip.set_report_available(True)
        if self.drawer is not None:
            self.drawer.set_report(report)
            self.drawer.set_safety(safety)
        self.status.emit("Analysis ready: %d finding(s), %d safety note(s)"
                         % (len(report.get("findings") or []),
                            len((safety or {}).get("findings") or [])))

    def report(self):
        if not self._require_archive():
            return
        if self.drawer is not None:
            self.drawer.open_report()
        if self._report is None:
            self._run_analysis()
        self.status.emit("Deprotection report: %s"
                         % (self._report or {}).get("verdict", "building\u2026"))

    def safety_scan(self):
        if not self._require_archive():
            return
        if self.drawer is not None:
            self.drawer.open_safety()
        if self._safety is None:
            self._run_analysis()

    # --------------------------------------------------------- filters
    def apply_folder_filter(self, folder):
        self.current_folder = folder
        self._apply_filters()

    def _apply_filters(self):
        self.table.set_filter(text=self.filter_edit.text(),
                              folder=self.current_folder,
                              category=self.chips.current())
        if not self.table.is_row_visible(self.table.currentIndex().row()):
            self.preview.clear()
            self.table.select_first_ok()
        shown = self.table.row_count()
        label = "(all files)" if self.current_folder is None else \
            self.current_folder + "\\"
        if self.filter_edit.text().strip():
            label += " matching \u201c%s\u201d" % self.filter_edit.text()
        self.status.emit("%s \u2014 %d of %d file(s)"
                         % (label, shown, self.table.source_count()))

    def jump_to(self, token):
        """Select a file named by a report link (`block:N` or a file name)."""
        block = None
        if token.startswith("block:"):
            try:
                block = int(token.split(":", 1)[1])
            except ValueError:
                block = None
        # A link should always land on its file, so clear whatever filter
        # was hiding it first.
        self.chips.set_current("all")
        self.filter_edit.blockSignals(True)
        self.filter_edit.clear()
        self.filter_edit.blockSignals(False)
        self.current_folder = None
        self.table.set_filter(folder=None)
        for r in range(self.table.row_count()):
            e = self.table.entry_at(r)
            if e is None:
                continue
            if (block is not None and e["block"] == block) or \
                    (block is None and (e.get("name") or "") == token):
                self.table.select_entry(e)
                self.preview.setFocus()
                return True
        self.status.emit("Not in the archive: %s" % token)
        return False

    # --------------------------------------------------------- preview
    def _preview_selected(self):
        e = self.table.current_entry()
        self.preview.set_entry(e)

    def _focus_preview(self, _index=None):
        e = self.table.current_entry()
        if e is not None and not filetypes.is_failed(e):
            self.preview.setFocus()
            self.status.emit(
                "Previewing %s (%s)"
                % (filetypes.display_name(e),
                   filetypes.detect(e.get("name"),
                                    e.get("data") or b"").label))

    def _table_menu(self, pos):
        menu = QMenu(self)
        row = self.table.rowAt(pos.y())
        e = self.table.entry_at(row)
        menu.addAction("Preview", self._focus_preview)
        menu.addAction("Extract selected\u2026", self.extract_selected)
        menu.addAction("Save as\u2026", lambda: self.save_preview(e))
        menu.addSeparator()
        menu.addAction("Copy name", lambda: QGuiApplication.clipboard()
                       .setText(filetypes.display_name(e or {})))
        menu.addSeparator()
        adv = menu.addAction("Advanced columns")
        adv.setCheckable(True)
        adv.setChecked(self.table.advanced)
        adv.triggered.connect(self.table.set_advanced)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ---------------------------------------------------------- extract
    def _last_dir(self):
        return self.settings.value("last_dir", "") if self.settings else ""

    def _run(self, label, worker, on_done=None, on_failed=None):
        return self.tasks.submit(label, worker, on_done=on_done,
                                 on_failed=on_failed,
                                 owner=self.current_path)

    def extract(self):
        if not self._require_archive():
            return
        outdir = QFileDialog.getExistingDirectory(
            self, "Extract into folder", self._last_dir())
        if not outdir:
            return
        if self.settings:
            self.settings.setValue("last_dir", outdir)
        self._run("Extract all \u2192 %s" % os.path.basename(outdir),
                  ExtractWorker(self.current_path, outdir),
                  on_done=lambda m: self._extract_done(m, outdir))

    def selected_entries(self):
        return [e for e in self.table.selected_entries()
                if not filetypes.is_failed(e)]

    def _selected_names(self):
        """Names of selected, recovered files that have a real name."""
        return [e["name"] for e in self.selected_entries()
                if e.get("name")]

    def _selected_blocks(self):
        """Block numbers of selected files — works for unnamed files too."""
        return [e["block"] for e in self.selected_entries()]

    def extract_selected(self):
        if not self._require_archive():
            return
        blocks = self._selected_blocks()
        if not blocks:
            self.status.emit("Select one or more recovered files first.")
            return
        outdir = QFileDialog.getExistingDirectory(
            self, "Extract %d selected file(s) into folder" % len(blocks),
            self._last_dir())
        if not outdir:
            return
        if self.settings:
            self.settings.setValue("last_dir", outdir)
        # Block numbers, not a name regex: a protected map's unnamed files
        # are exactly the ones you most want to pull out.
        self._run("Extract %d file(s) \u2192 %s"
                  % (len(blocks), os.path.basename(outdir)),
                  ExtractWorker(self.current_path, outdir, blocks=blocks),
                  on_done=lambda m: self._extract_done(m, outdir))

    def _extract_done(self, manifest, outdir):
        got = sum(1 for r in manifest if r.get("extracted"))
        failed = sum(1 for r in manifest if r["status"] != "ok")
        self.status.emit("Extracted %d file(s) (%d failed) to %s"
                         % (got, failed, outdir))

    # ------------------------------------------------------ file actions
    def save_preview(self, entry=None):
        """Save the selected file's bytes without extracting the archive."""
        e = entry if entry is not None else self.table.current_entry()
        if e is None or filetypes.is_failed(e) or e.get("data") is None:
            self.status.emit("Nothing to save \u2014 select a recovered file.")
            return
        suggested = filetypes.entry_name(e).replace("\\", "_")
        out, _ = QFileDialog.getSaveFileName(self, "Save file as", suggested)
        if not out:
            return
        try:
            self._save_entry_to(e, out)
        except OSError as exc:
            self.status.emit("Could not save: %s" % exc)
            return
        self.status.emit("Saved %s" % out)

    def _save_entry_to(self, entry, path):
        with open(path, "wb") as f:
            f.write(entry["data"])
        return len(entry["data"])

    def open_containing_folder(self):
        if not self.current_path:
            return
        try:
            open_folder(self.current_path)
        except Exception as exc:                       # noqa: BLE001
            self.status.emit("Could not open folder: %s" % exc)

    def export_table(self):
        if not self.current_entries:
            return
        path, _sel = QFileDialog.getSaveFileName(
            self, "Export file table", "files.json",
            "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        try:
            count = self._write_table(path)
        except OSError as exc:
            self.status.emit("Could not export: %s" % exc)
            return
        self.status.emit("Exported %d rows to %s" % (count, path))

    def _table_rows(self):
        rows = []
        for e in self.current_entries or []:
            rows.append(dict(
                block=e["block"], name=e["name"] or "", size=e["size"],
                archived_size=e["archived_size"], flags=e["flags"],
                status=e["status"], name_source=e.get("name_source"),
                key_method=e.get("key_method"), sha256=e.get("sha256"),
                detected_type=filetypes.detect(
                    e.get("name"), e.get("data") or b"").key))
        return rows

    def _write_table(self, path):
        rows = self._table_rows()
        if path.lower().endswith(".csv"):
            import csv
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        else:
            import json
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=1)
        return len(rows)

    # ----------------------------------------------------------- rebuild
    def rebuild(self):
        if not self._require_archive():
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "Save rebuilt map as",
            "rebuilt_" + os.path.basename(self.current_path),
            "WC3 map (*.w3x)")
        if not out:
            return

        def done(res):
            self.status.emit(
                "Rebuilt %s \u2014 %d files. The original was not modified."
                % (res.get("out_path", out), res.get("count", 0)))

        self._run("Rebuild \u2192 %s" % os.path.basename(out),
                  RebuildWorker(self.current_path, out), on_done=done,
                  on_failed=lambda err: self.status.emit(
                      "Rebuild failed: %s" % err))

    # ---------------------------------------------------------- plumbing
    def _require_archive(self):
        if self.current_path is None:
            self.status.emit("Open an archive first.")
            return False
        return True

    def layout_state(self):
        """Remembered per-archive view state."""
        state = dict(
            splitter=bytes(self.splitter.saveState()).hex(),
            chip=self.chips.current(),
            advanced=self.table.advanced,
            drawer=self.drawer.expanded if self.drawer else False,
            drawer_tab=self.drawer.tabs.currentIndex() if self.drawer else 0,
            preview_mode=self.preview.mode,
            find=self.preview.find_btn.isChecked(),
        )
        return state

    def restore_layout_state(self, state):
        if not isinstance(state, dict):
            return
        raw = state.get("splitter")
        if raw:
            # QSettings cannot round-trip a raw QByteArray on every Qt
            # build, so layout_state() stores it as hex.  Older sessions
            # may still hold bytes / QByteArray — accept those too.
            if isinstance(raw, str):
                state_bytes = QByteArray.fromHex(raw.encode("ascii"))
            elif isinstance(raw, QByteArray):
                state_bytes = QByteArray(raw)
            else:
                state_bytes = QByteArray(bytes(raw))
            self.splitter.restoreState(state_bytes)
        chip = state.get("chip")
        if chip:
            self.chips.set_current(chip)
        if "advanced" in state:
            self.table.set_advanced(state["advanced"])
        if self.drawer is not None:
            self.drawer.set_expanded(bool(state.get("drawer")))
            self.drawer.tabs.setCurrentIndex(int(state.get("drawer_tab", 0)))
        if state.get("preview_mode"):
            self.preview.set_mode(state["preview_mode"])
        self.preview.set_find_visible(bool(state.get("find")))

    def on_theme_changed(self):
        for widget in (self.summary_strip, self.chips, self.preview,
                       self.drawer):
            if widget is not None:
                widget.apply_theme()
        self.table.apply_theme()

    def shutdown(self):
        """Cancel this tab's jobs before the widget is destroyed."""
        if self.tasks is not None:
            self.tasks.cancel_owner(self.current_path)

    # ---------------------------------------------------- compatibility
    @property
    def banner(self):
        """The headline label (kept for older callers)."""
        return self.summary_strip.headline
