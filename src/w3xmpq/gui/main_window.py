# -*- coding: utf-8 -*-
"""w3xmpq GUI — main window.

Layout:
  ┌ banner (map name / author / tileset / verdict) ┐
  ├ file table ──────────────────┬ preview pane  ──┤
  │ block / name / size / flags  │ hex or text     │
  └ status bar (progress) ───────┴─────────────────┘

Everything heavy runs on QThread workers (workers.py); this module only
wires results into widgets.
"""

import os
import re
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import __version__
from ..core.w3x_header import is_w3x, parse_header
from ..core.report import build_report, render_report
from ..core.safety import scan_safety, render_safety
from .workers import (BatchWorker, DiffWorker, ExtractWorker, RebuildWorker,
                      ScanWorker)

ARCHIVE_FILTER = "WC3 maps & MPQ archives (*.w3x *.w3m *.mpq);;All files (*)"

TEXT_EXT = (".j", ".txt", ".ai", ".md", ".csv", ".json", ".xml", ".ini",
            ".wct", ".wtg")
HEX_PREVIEW_LIMIT = 8 * 1024      # bytes shown in the hex pane
TEXT_PREVIEW_LIMIT = 200 * 1024   # bytes shown in the text pane

FLAGS_SHORT = [(0x80000000, "E"), (0x00000200, "Z"), (0x00010000, "K"),
               (0x01000000, "S"), (0x04000000, "C"), (0x00040000, "P")]


def _flags_str(flags):
    return "".join(c for bit, c in FLAGS_SHORT if flags & bit) or "-"


def _hexdump(data, limit=HEX_PREVIEW_LIMIT, width=16):
    rows = []
    for off in range(0, min(len(data), limit), width):
        chunk = data[off:off + width]
        hx = " ".join("%02x" % b for b in chunk)
        hx = hx.ljust(width * 3 - 1)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append("%08x  %s  %s" % (off, hx, asc))
    if len(data) > limit:
        rows.append("... (%d more bytes)" % (len(data) - limit))
    return "\n".join(rows)


def _is_text(name, data):
    if name and name.lower().endswith(TEXT_EXT):
        return True
    if not data:
        return False
    sample = data[:512]
    printable = sum(1 for b in sample
                    if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(sample) > 0.85


class FileTable(QTableWidget):
    """Table of scanned blocks. Stores entry dicts by row."""

    def __init__(self, parent=None):
        super().__init__(0, 6, parent)
        self.entries = []
        self._setup()

    def _setup(self):
        self.setHorizontalHeaderLabels(
            ["Block", "Name", "Size", "Packed", "Flags", "Status"])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        header = self.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

    def load_entries(self, entries):
        self.entries = entries
        self.setRowCount(len(entries))
        for row, e in enumerate(entries):
            vals = [str(e["block"]),
                    e["name"] or "<unnamed>",
                    "{:,}".format(e["size"]),
                    "{:,}".format(e["archived_size"]),
                    _flags_str(e["flags"]),
                    e["status"]]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if col in (0, 2, 3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if e["status"] != "ok":
                    item.setForeground(Qt.red)
                elif col == 1 and not e["name"]:
                    item.setForeground(Qt.gray)
                self.setItem(row, col, item)

    def entry_at(self, row):
        return self.entries[row] if 0 <= row < len(self.entries) else None


class FolderTree(QTreeWidget):
    """Left pane: folders of the archive, 7-zip style.

    Each item carries its full folder path (Qt.UserRole). Selecting a
    folder asks the main window to filter the file table to it; the
    top-level "(all files)" item clears the filter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setMaximumWidth(260)
        self.itemSelectionChanged.connect(self._emit_selection)

    def _emit_selection(self):
        items = self.selectedItems()
        if items:
            win = self.window()
            if hasattr(win, "apply_folder_filter"):
                win.apply_folder_filter(items[0].data(0, Qt.UserRole))

    def load_entries(self, entries):
        """Rebuild the folder hierarchy from entry names."""
        self.blockSignals(True)
        self.clear()
        root_item = QTreeWidgetItem(["(all files)"])
        root_item.setData(0, Qt.UserRole, None)
        self.addTopLevelItem(root_item)
        nodes = {None: root_item}
        folders = set()
        for e in entries:
            name = e.get("name")
            if not name:
                continue
            parts = re.split(r"[\\/]", name)
            for i in range(1, len(parts)):
                folders.add("\\".join(parts[:i]))
        for f in sorted(folders):
            parent_path, _, leaf = f.rpartition("\\")
            parent = nodes.get(parent_path, root_item)
            item = QTreeWidgetItem([leaf + "/"])
            item.setData(0, Qt.UserRole, f)
            parent.addChild(item)
            nodes[f] = item
        self.expandAll()
        self.setCurrentItem(root_item)
        self.blockSignals(False)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_path = None
        self.current_entries = None
        self.current_folder = None      # None = all files
        self.worker = None
        self._build_ui()

    # ------------------------------------------------------------ UI setup
    def _build_ui(self):
        self.setWindowTitle("w3xmpq " + __version__)
        self.resize(1100, 700)
        self.setAcceptDrops(True)

        # Banner
        self.banner = QLabel(
            "Open a .w3x / .w3m / .mpq file (Ctrl+O) or drag & drop it "
            "here — browse it like a zip: click a file to preview, "
            "double-click to focus the preview, right-click to extract.")
        self.banner.setStyleSheet(
            "QLabel { padding: 8px; background: palette(midlight);"
            " border-radius: 4px; }")
        self.banner.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.banner.setWordWrap(True)

        # Folder tree + file table + preview (7-zip layout)
        self.folders = FolderTree()

        self.table = FileTable()
        self.table.itemSelectionChanged.connect(self._preview_selected)
        self.table.cellDoubleClicked.connect(self._focus_preview)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        self.preview.setFont(font)
        self.preview.setPlaceholderText(
            "Select a file to preview it here (text files as text, "
            "everything else as a hex dump).")

        splitter = QSplitter()
        splitter.addWidget(self.folders)
        splitter.addWidget(self.table)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([180, 470, 450])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self.banner)
        layout.addWidget(splitter)
        self.setCentralWidget(central)

        self.statusBar().showMessage("Ready")

        # Menus / toolbar
        open_act = QAction("&Open…", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self._open_dialog)
        extract_act = QAction("&Extract…", self)
        extract_act.setShortcut("Ctrl+E")
        extract_act.triggered.connect(self._extract)
        extract_sel_act = QAction("Extract &selected…", self)
        extract_sel_act.setShortcut("Ctrl+Shift+E")
        extract_sel_act.triggered.connect(self._extract_selected)
        quit_act = QAction("E&xit", self)
        quit_act.triggered.connect(self.close)

        report_act = QAction("&Deprotection report", self)
        report_act.triggered.connect(self._report)
        scan_act = QAction("&Safety scan", self)
        scan_act.triggered.connect(self._scan)
        rebuild_act = QAction("&Rebuild (WorldEdit-ready)…", self)
        rebuild_act.triggered.connect(self._rebuild)
        diff_act = QAction("&Diff two archives…", self)
        diff_act.triggered.connect(self._diff)
        batch_act = QAction("&Batch extract folder…", self)
        batch_act.triggered.connect(self._batch)
        about_act = QAction("&About", self)
        about_act.triggered.connect(self._about)

        menu_file = self.menuBar().addMenu("&File")
        menu_file.addAction(open_act)
        menu_file.addAction(extract_act)
        menu_file.addAction(extract_sel_act)
        menu_file.addSeparator()
        menu_file.addAction(quit_act)
        menu_tools = self.menuBar().addMenu("&Tools")
        for a in (report_act, scan_act, rebuild_act, None, diff_act, batch_act):
            if a is None:
                menu_tools.addSeparator()
            else:
                menu_tools.addAction(a)
        menu_help = self.menuBar().addMenu("&Help")
        menu_help.addAction(about_act)

        tb = self.addToolBar("main")
        tb.setMovable(False)
        self._actions = []
        for a in (open_act, extract_act, extract_sel_act, report_act,
                  scan_act, rebuild_act, diff_act, batch_act):
            tb.addAction(a)
            self._actions.append(a)

        # Only tools that need a loaded archive start disabled.
        for a in self._actions[1:]:
            a.setEnabled(False)

    def _set_actions_enabled(self, on):
        for a in self._actions[1:]:
            a.setEnabled(on)

    # ------------------------------------------------------------ opening
    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open archive", "", ARCHIVE_FILTER)
        if path:
            self.open_archive(path)

    def open_archive(self, path):
        if self.worker is not None:
            QMessageBox.information(
                self, "Busy", "A task is running — wait for it to finish.")
            return
        self.current_path = path
        self.statusBar().showMessage("Scanning %s…" % os.path.basename(path))
        self.banner.setText("Scanning %s…" % path)
        self.worker = ScanWorker(path)
        self.worker.result_ready.connect(self._on_scanned)
        self.worker.failed.connect(self._on_task_failed)
        self.worker.start()

    def _on_scanned(self, entries):
        self.worker = None
        self.current_entries = entries
        self.current_folder = None
        self.table.load_entries(entries)
        self.folders.load_entries(entries)
        self.preview.clear()
        self._set_actions_enabled(True)
        self._refresh_banner()
        ok = sum(1 for e in entries if e["status"] == "ok")
        failed = len(entries) - ok
        self.statusBar().showMessage(
            "%d blocks: %d recovered, %d failed — %s"
            % (len(entries), ok, failed, self.current_path))
        # Zip-like feel: show the first recovered file right away.
        for r in range(self.table.rowCount()):
            if self.table.item(r, 5).text() == "ok" \
                    and not self.table.isRowHidden(r):
                self.table.selectRow(r)
                break

    # ------------------------------------------------------- folder filter
    def apply_folder_filter(self, folder):
        """Show only files under `folder` (None = everything)."""
        self.current_folder = folder
        for r, e in enumerate(self.table.entries):
            name = e.get("name")
            if folder is None:
                self.table.setRowHidden(r, False)
            elif not name:
                self.table.setRowHidden(r, True)   # unnamed: root only
            else:
                self.table.setRowHidden(
                    r, not name.replace("/", "\\").startswith(
                        folder + "\\"))
        # Keep a visible selection so preview/extract stay usable.
        if self.table.currentRow() < 0 or \
                self.table.isRowHidden(self.table.currentRow()):
            self.preview.clear()
            for r in range(self.table.rowCount()):
                if not self.table.isRowHidden(r) \
                        and self.table.item(r, 5).text() == "ok":
                    self.table.selectRow(r)
                    break
        shown = sum(1 for r in range(self.table.rowCount())
                    if not self.table.isRowHidden(r))
        label = "(all files)" if folder is None else folder + "\\"
        self.statusBar().showMessage("%s — %d file(s)" % (label, shown))

    def _refresh_banner(self):
        path = self.current_path
        parts = ["<b>%s</b>" % os.path.basename(path)]
        if is_w3x(path):
            try:
                h = parse_header(path)
                parts.append("Map: <b>%s</b>" % h["name"])
                if h.get("author"):
                    parts.append("by %s" % h["author"])
                parts.append("tileset %s · %d×%d tiles"
                             % (h.get("tileset", "?"), h.get("width", 0),
                                h.get("height", 0)))
            except Exception:
                pass
        if self.current_entries is not None:
            ok = sum(1 for e in self.current_entries if e["status"] == "ok")
            parts.append("%d/%d blocks recovered"
                         % (ok, len(self.current_entries)))
        self.banner.setText(" · ".join(str(p) for p in parts))

    # ------------------------------------------------------------ preview
    def _preview_selected(self):
        row = self.table.currentRow()
        e = self.table.entry_at(row)
        if e is None or e["status"] != "ok" or e.get("data") is None:
            self.preview.setPlainText("")
            return
        name, data = e["name"], e["data"]
        if _is_text(name, data):
            text = data[:TEXT_PREVIEW_LIMIT].decode("utf-8", "replace")
            if len(data) > TEXT_PREVIEW_LIMIT:
                text += "\n… (truncated)"
            self.preview.setPlainText(text)
        else:
            self.preview.setPlainText(
                "%d bytes — hex dump of first %d:\n\n%s"
                % (len(data), min(len(data), HEX_PREVIEW_LIMIT),
                   _hexdump(data)))

    # ------------------------------------------------------------ extract
    def _extract(self):
        if not self._require_archive():
            return
        outdir = QFileDialog.getExistingDirectory(
            self, "Extract into folder")
        if not outdir:
            return
        self._run("Extracting to %s…" % outdir,
                  ExtractWorker(self.current_path, outdir),
                  on_done=lambda m: self._extract_done(m, outdir))

    def _selected_names(self):
        """Names of the selected, successfully recovered files."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        names = []
        for r in rows:
            e = self.table.entry_at(r)
            if e and e["status"] == "ok" and e["name"]:
                names.append(e["name"])
        return names

    def _extract_selected(self):
        if not self._require_archive():
            return
        names = self._selected_names()
        if not names:
            QMessageBox.information(
                self, "Nothing selected",
                "Select one or more recovered files in the table first.")
            return
        outdir = QFileDialog.getExistingDirectory(
            self, "Extract %d selected file(s) into folder" % len(names))
        if not outdir:
            return
        # extract_archive matches `pattern` (regex) against resolved names.
        pattern = "|".join(re.escape(n) for n in names)
        self._run("Extracting %d selected file(s)…" % len(names),
                  ExtractWorker(self.current_path, outdir, pattern=pattern),
                  on_done=lambda m: self._extract_done(m, outdir))

    def _extract_done(self, manifest, outdir):
        got = sum(1 for r in manifest if r.get("extracted"))
        failed = sum(1 for r in manifest if r["status"] != "ok")
        QMessageBox.information(
            self, "Extraction finished",
            "Extracted %d file(s) (%d failed) to:\n%s\n\n"
            "A manifest.json with SHA-256 hashes was written alongside."
            % (got, failed, outdir))

    # ------------------------------------------------- zip-style browsing
    def _focus_preview(self, row, _col):
        e = self.table.entry_at(row)
        if e and e["status"] == "ok":
            self.preview.setFocus()
            self.statusBar().showMessage(
                "Previewing %s (%s) — use Extract selected… to save it."
                % (e["name"] or "<unnamed>",
                   "text" if _is_text(e["name"], e.get("data") or b"")
                   else "hex"))

    def _table_menu(self, pos):
        from PySide6.QtGui import QGuiApplication
        menu = QMenu(self)
        e = self.table.entry_at(self.table.rowAt(pos.y()))
        if e and e["status"] == "ok":
            menu.addAction("Preview", self._focus_preview_row)
            menu.addAction("Extract selected…",
                           self._extract_selected)
            menu.addAction("Copy name",
                           lambda: QGuiApplication.clipboard().setText(
                               e["name"] or ""))
        else:
            menu.addAction("Extract selected…", self._extract_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _focus_preview_row(self):
        self._focus_preview(self.table.currentRow(), 0)

    # ------------------------------------------------------------ report
    def _report(self):
        if not self._require_archive():
            return
        self._run("Building deprotection report…",
                  _FnWorker(build_report, self.current_path),
                  on_done=lambda rep: _TextDialog(
                      self, "Deprotection report",
                      render_report(rep)).exec())

    # ------------------------------------------------------------ scan
    def _scan(self):
        if not self._require_archive():
            return
        self._run("Running safety scan…",
                  _FnWorker(scan_safety, self.current_path),
                  on_done=lambda res: _TextDialog(
                      self, "Map safety scan",
                      render_safety(res)).exec())

    # ------------------------------------------------------------ rebuild
    def _rebuild(self):
        if not self._require_archive():
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "Save rebuilt map as", "rebuilt_" +
            os.path.basename(self.current_path), "WC3 map (*.w3x)")
        if not out:
            return
        self._run("Rebuilding…", RebuildWorker(self.current_path, out),
                  on_done=lambda res: QMessageBox.information(
                      self, "Rebuild finished",
                      "Wrote %s\n\nThe rebuilt map is a standard archive "
                      "WorldEdit can open. The original was not modified."
                      % res.get("out_path", out)))

    # ------------------------------------------------------------ diff
    def _diff(self):
        dlg = _DiffDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        a, b = dlg.path_a, dlg.path_b
        self._run("Diffing…", DiffWorker(a, b),
                  on_done=lambda res: _TextDialog(
                      self, "Archive diff", _render_diff(a, b, res)).exec())

    # ------------------------------------------------------------ batch
    def _batch(self):
        dlg = _BatchDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._run("Batch extracting…",
                  BatchWorker(dlg.search_dir, dlg.outdir),
                  on_done=lambda res: _TextDialog(
                      self, "Batch extract",
                      _render_batch(dlg.search_dir, res)).exec())

    # ------------------------------------------------------------ plumbing
    def _require_archive(self):
        if self.current_path is None:
            QMessageBox.information(self, "No archive",
                                    "Open an archive first.")
            return False
        return True

    def _run(self, message, worker, on_done):
        if self.worker is not None:
            QMessageBox.information(
                self, "Busy", "A task is running — wait for it to finish.")
            return
        self.statusBar().showMessage(message)
        self.setEnabled(False)
        self.worker = worker
        self._on_done = on_done

        def done(result):
            self.setEnabled(True)
            self.worker = None
            self.statusBar().showMessage("Ready")
            on_done(result)

        def failed(err):
            self.setEnabled(True)
            self.worker = None
            self.statusBar().showMessage("Ready")
            QMessageBox.critical(self, "Task failed", err)

        worker.result_ready.connect(done)
        worker.failed.connect(failed)
        worker.start()

    def _on_task_failed(self, err):
        self.worker = None
        self.current_path = None
        self.statusBar().showMessage("Ready")
        self.banner.setText("Could not read that file — see the error "
                            "dialog for details.")
        QMessageBox.critical(self, "Could not open archive", err)

    def _about(self):
        QMessageBox.about(
            self, "About w3xmpq",
            "<b>w3xmpq %s</b><br><br>"
            "Open any Warcraft III map or MPQ archive — recovers "
            "encrypted files via a known-plaintext attack, no listfile "
            "needed.<br><br>"
            "Read-only: the tool never modifies your files.<br>"
            "<a href='https://github.com/kissanima/w3xmpq'>"
            "github.com/kissanima/w3xmpq</a>" % __version__)

    # ------------------------------------------------------------ drag&drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and os.path.splitext(path)[1].lower() in (
                    ".w3x", ".w3m", ".mpq"):
                self.open_archive(path)
                break


class _FnWorker(ScanWorker):
    """Runs an arbitrary core function that takes (path) and returns a dict."""

    def __init__(self, fn, path, parent=None):
        super().__init__(path, parent=parent)
        self._fn = fn

    def run(self):
        try:
            self.result_ready.emit(self._fn(self.path))
        except Exception as e:
            self.failed.emit(str(e))


class _TextDialog(QDialog):
    def __init__(self, parent, title, text):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 520)
        lay = QVBoxLayout(self)
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        edit.setFont(font)
        lay.addWidget(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class _DiffDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Diff two archives")
        self.path_a = self.path_b = None
        form = QFormLayout(self)
        self.edit_a = QLineEdit()
        self.edit_b = QLineEdit()
        for label, edit in (("Archive A", self.edit_a),
                            ("Archive B", self.edit_b)):
            row = QHBoxLayout()
            row.addWidget(edit)
            btn = QPushButton("Browse…")
            btn.clicked.connect(lambda _=False, e=edit: self._browse(e))
            row.addWidget(btn)
            form.addRow(label, row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok |
                                   QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self, edit):
        path, _ = QFileDialog.getOpenFileName(self, "Open archive", "",
                                              ARCHIVE_FILTER)
        if path:
            edit.setText(path)

    def _accept(self):
        self.path_a, self.path_b = self.edit_a.text(), self.edit_b.text()
        if self.path_a and self.path_b:
            self.accept()


class _BatchDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Batch extract a folder")
        self.search_dir = self.outdir = None
        form = QFormLayout(self)
        self.edit_src = QLineEdit()
        self.edit_out = QLineEdit()
        form.addRow("Folder containing maps", self._pick_row(self.edit_src))
        form.addRow("Output folder", self._pick_row(self.edit_out, dir_mode=True))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok |
                                   QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _pick_row(self, edit, dir_mode=False):
        row = QHBoxLayout()
        row.addWidget(edit)
        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda _=False, e=edit, d=dir_mode:
                            self._browse(e, d))
        row.addWidget(btn)
        w = QWidget()
        w.setLayout(row)
        return w

    def _browse(self, edit, dir_mode):
        if dir_mode:
            path = QFileDialog.getExistingDirectory(self, "Choose folder")
        else:
            path = QFileDialog.getExistingDirectory(self, "Choose folder")
        if path:
            edit.setText(path)

    def _accept(self):
        self.search_dir = self.edit_src.text()
        self.outdir = self.edit_out.text()
        if self.search_dir and self.outdir:
            self.accept()


def _render_diff(a, b, res):
    lines = ["Diff: %s  vs  %s" % (a, b),
             "common files: %d" % res.get("common", 0), ""]
    for title, key in (("Only in A", "only_a"), ("Only in B", "only_b"),
                       ("Changed", "changed")):
        items = res.get(key, [])
        lines.append("%s (%d):" % (title, len(items)))
        for name, sha in items[:200]:
            lines.append("  %s  %s…" % (name, (sha or "")[:12]))
        if len(items) > 200:
            lines.append("  … %d more" % (len(items) - 200))
        lines.append("")
    return "\n".join(lines)


def _render_batch(root, results):
    lines = ["Batch extract: %s — %d archives" % (root, len(results)), ""]
    for r in results:
        lines.append("  %-14s %s" % (r.get("status", "?"),
                                     r.get("path", "?")))
    lines.append("")
    lines.append("Index written: index.csv / index.json in the output folder.")
    return "\n".join(lines)


def main(argv=None):
    # Accept either real sys.argv or an explicit list (the CLI `gui`
    # subcommand passes just the archive path).
    args = list(sys.argv[1:]) if argv is None else list(argv)
    # Handle --version before any Qt machinery: release CI smoke-tests the
    # frozen binary with this flag, and it must work headless.
    if "--version" in args or "-V" in args:
        print("w3xmpq %s (GUI)" % __version__)
        return 0
    qt_args = [sys.argv[0]] + args
    app = QApplication(qt_args)
    app.setApplicationName("w3xmpq")
    app.setOrganizationName("w3xmpq")
    win = MainWindow()
    win.show()
    # File passed on the command line is opened immediately.
    for arg in args:
        if os.path.splitext(arg)[1].lower() in (".w3x", ".w3m", ".mpq") \
                and os.path.isfile(arg):
            win.open_archive(arg)
            break
    sys.exit(app.exec())
