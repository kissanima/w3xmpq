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

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import (QAction, QFont, QImage, QKeySequence, QPixmap,
                           QShortcut, QTextDocument)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import __version__
from ..core.blp import open_blp
from ..core.w3x_header import is_w3x, parse_header
from ..core.report import build_report, render_report
from ..core.safety import scan_safety, render_safety
from .jass_highlight import JassHighlighter, is_jass
from .workers import (BatchWorker, DiffWorker, ExtractWorker, RebuildWorker,
                      ScanWorker)

ARCHIVE_FILTER = "WC3 maps & MPQ archives (*.w3x *.w3m *.mpq);;All files (*)"

TEXT_EXT = (".j", ".txt", ".ai", ".md", ".csv", ".json", ".xml", ".ini",
            ".wct", ".wtg")
HEX_PREVIEW_LIMIT = 8 * 1024      # bytes shown in the hex pane
TEXT_PREVIEW_LIMIT = 200 * 1024   # bytes shown in the text pane

FLAGS_SHORT = [(0x80000000, "E"), (0x00000200, "Z"), (0x00010000, "K"),
               (0x01000000, "S"), (0x04000000, "C"), (0x00040000, "P")]

SORT_ROLE = Qt.UserRole + 1      # hidden sort key
ENTRY_ROLE = Qt.UserRole + 2     # index into FileTable.entries


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


class FindEdit(QLineEdit):
    """Line edit that reports the Escape key (closes the find bar)."""
    escape_pressed = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.escape_pressed.emit()
            return
        super().keyPressEvent(event)


class SortItem(QTableWidgetItem):
    """Table item that sorts by a hidden key (case-insensitive for text)."""

    def __lt__(self, other):
        mine = self.data(SORT_ROLE)
        theirs = other.data(SORT_ROLE)
        if isinstance(mine, str) and isinstance(theirs, str):
            return mine.lower() < theirs.lower()
        try:
            return (mine if mine is not None else 0) < \
                   (theirs if theirs is not None else 0)
        except TypeError:
            return str(mine) < str(theirs)


class FileTable(QTableWidget):
    """Table of scanned blocks. Stores entry dicts by row.

    Rows keep a reference to their entry in SORT_ROLE/ENTRY_ROLE, so
    sorting by a column never desynchronises the table from the data.
    """

    def __init__(self, parent=None):
        super().__init__(0, 7, parent)
        self.entries = []
        self._setup()

    def _setup(self):
        self.setHorizontalHeaderLabels(
            ["Block", "Name", "Size", "Packed", "Flags", "Src", "Status"])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        # Extended: ctrl/shift-click to pick several files at once.
        self.setSelectionMode(QTableWidget.ExtendedSelection)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        header = self.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (0, 2, 3, 4, 5, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSortIndicator(2, Qt.DescendingOrder)   # size, biggest first

    def load_entries(self, entries):
        self.entries = entries
        self.setSortingEnabled(False)
        self.setRowCount(len(entries))
        for row, e in enumerate(entries):
            src = e.get("name_source") or "unknown"
            key = e.get("key_method") or "plain"
            vals = [str(e["block"]),
                    e["name"] or "<unnamed>",
                    "{:,}".format(e["size"]),
                    "{:,}".format(e["archived_size"]),
                    _flags_str(e["flags"]),
                    "%s/%s" % (src, key),
                    e["status"]]
            sort_keys = [e["block"], (e["name"] or "").lower(),
                         e["size"], e["archived_size"],
                         _flags_str(e["flags"]), src, e["status"]]
            for col, v in enumerate(vals):
                item = SortItem(v)
                item.setData(SORT_ROLE, sort_keys[col])
                item.setData(ENTRY_ROLE, row)
                if col in (0, 2, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if e["status"] != "ok":
                    item.setForeground(Qt.red)
                elif col == 1 and not e["name"]:
                    item.setForeground(Qt.gray)
                self.setItem(row, col, item)
        self.setSortingEnabled(True)

    def entry_at(self, row):
        """Entry dict for a visual row (follows the current sort order)."""
        item = self.item(row, 0)
        if item is None:
            return None
        idx = item.data(ENTRY_ROLE)
        if idx is None or not (0 <= idx < len(self.entries)):
            return None
        return self.entries[idx]

    def selected_entries(self):
        """All entries covered by the current selection (multi-select)."""
        rows = sorted({i.row() for i in self.selectedIndexes()})
        out = []
        for r in rows:
            e = self.entry_at(r)
            if e is not None:
                out.append(e)
        return out


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
        self._highlighter = None       # JASS syntax highlighter (preview)
        # Session memory: window geometry, splitter, last folders, recents.
        self.settings = QSettings("w3xmpq", "w3xmpq")
        self._build_ui()
        self._restore_session()

    def _restore_session(self):
        geom = self.settings.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        state = self.settings.value("splitter")
        if state is not None:
            self.splitter.restoreState(state)
        idx = self.settings.value("show_filter", 0, type=int)
        if 0 <= idx < self.show_combo.count():
            self.show_combo.setCurrentIndex(idx)

    def _save_session(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        self.settings.setValue("show_filter", self.show_combo.currentIndex())

    def closeEvent(self, event):
        self._save_session()
        super().closeEvent(event)

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
        # Keep the banner compact so the file table gets the screen space.
        self.banner.setMaximumHeight(64)

        # Folder tree + file table + preview (7-zip layout)
        self.folders = FolderTree()

        # Live filter + scan progress row
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("filter files… (Ctrl+F)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filters)
        self._filter_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._filter_shortcut.activated.connect(self.filter_edit.setFocus)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setVisible(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_scan)

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

        # In-file search bar (shown above the preview).
        self.find_edit = FindEdit()
        self.find_edit.setPlaceholderText("find in file (Ctrl+Shift+F)")
        self.find_edit.setVisible(False)
        self.find_edit.returnPressed.connect(self._find_next)
        self.find_edit.escape_pressed.connect(self._hide_find)
        self.find_count = QLabel("")
        self.find_count.setVisible(False)
        self.find_prev = QPushButton("<")
        self.find_prev.setVisible(False)
        self.find_prev.clicked.connect(lambda: self._find_next(True))
        self.find_next = QPushButton(">")
        self.find_next.setVisible(False)
        self.find_next.clicked.connect(self._find_next)
        self.find_edit.textChanged.connect(self._find_changed)
        # Keep a reference to the shortcut: a window-level QShortcut that is
        # garbage collected while the window lives crashes Qt.
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        self._find_shortcut.activated.connect(self._toggle_find)

        splitter = QSplitter()
        splitter.addWidget(self.folders)
        splitter.addWidget(self.table)
        preview_box = QWidget()
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)
        find_row = QHBoxLayout()
        find_row.setSpacing(4)
        find_row.addWidget(self.find_prev)
        find_row.addWidget(self.find_edit, 1)
        find_row.addWidget(self.find_next)
        find_row.addWidget(self.find_count)
        find_row_widget = QWidget()
        find_row_widget.setLayout(find_row)
        find_row_widget.setVisible(False)
        find_row_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # The preview is either text (scripts, hex dumps) or a picture
        # (.blp textures) — a stacked widget switches between them.
        self.preview_stack = QStackedWidget()
        text_page = QWidget()
        text_layout = QVBoxLayout(text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(find_row_widget)
        text_layout.addWidget(self.preview)

        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setAlignment(Qt.AlignCenter)
        self.image_label = QLabel("No image")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setBackgroundRole(self.image_label.backgroundRole())
        self.image_scroll.setWidget(self.image_label)

        self.preview_stack.addWidget(text_page)
        self.preview_stack.addWidget(self.image_scroll)
        preview_layout.addWidget(self.preview_stack)
        splitter.addWidget(preview_box)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([180, 470, 450])
        self.splitter = splitter
        self._find_row_widget = find_row_widget

        # Row above the panes: live filter on the left, scan progress on
        # the right (only visible while a scan runs).
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addWidget(self.filter_edit, 1)
        self.show_combo = QComboBox()
        self.show_combo.addItems(["all files", "named only", "unnamed only",
                                  "failed only", "encrypted only"])
        self.show_combo.setToolTip("Restrict the table to a subset")
        self.show_combo.currentIndexChanged.connect(self._apply_filters)
        top_row.addWidget(self.show_combo)
        top_row.addWidget(self.progress)
        top_row.addWidget(self.cancel_btn)
        top_row_widget = QWidget()
        top_row_widget.setLayout(top_row)
        # Keep the row compact — it must not absorb the vertical space
        # that belongs to the file table.
        top_row_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self.banner)
        layout.addWidget(top_row_widget)
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
        save_prev_act = QAction("Save pre&view as…", self)
        save_prev_act.setShortcut("Ctrl+S")
        save_prev_act.triggered.connect(self._save_preview)
        folder_act = QAction("Open containing &folder", self)
        folder_act.triggered.connect(self._open_containing_folder)
        export_act = QAction("&Export file table…", self)
        export_act.triggered.connect(self._export_table)

        menu_file = self.menuBar().addMenu("&File")
        menu_file.addAction(open_act)
        self.recent_menu = menu_file.addMenu("Open &recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        menu_file.addSeparator()
        menu_file.addAction(extract_act)
        menu_file.addAction(extract_sel_act)
        menu_file.addAction(save_prev_act)
        menu_file.addAction(export_act)
        menu_file.addAction(folder_act)
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
        self._remember_recent(path)
        self.statusBar().showMessage("Scanning %s…" % os.path.basename(path))
        self.banner.setText("Scanning %s…" % path)
        self.filter_edit.clear()
        self.progress.setRange(0, 0)          # busy indicator
        self.progress.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.worker = ScanWorker(path)
        self.worker.result_ready.connect(self._on_scanned)
        self.worker.failed.connect(self._on_task_failed)
        self.worker.progress.connect(self._on_scan_progress)
        # Keep the worker alive until the thread has really finished —
        # dropping the reference from inside the result handler destroys
        # the QThread while run() is still on the stack, which crashes Qt.
        self.worker.finished.connect(
            lambda w=self.worker: self._release_worker(w))
        self.worker.start()

    def _release_worker(self, worker):
        """Forget a finished worker (QThread.finished == run() returned)."""
        if self.worker is worker:
            self.worker = None

    def _on_scan_progress(self, done, total):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.statusBar().showMessage("Scanning… %d / %d blocks" % (done, total))

    def _cancel_scan(self):
        if self.worker is not None and hasattr(self.worker, "cancel"):
            self.worker.cancel()
            self.statusBar().showMessage("Cancelling…")
            self.cancel_btn.setEnabled(False)

    def _on_scanned(self, entries):
        self.current_entries = entries
        self.current_folder = None
        self.table.load_entries(entries)
        self.folders.load_entries(entries)
        self.preview.clear()
        self._show_text_page()
        self._set_actions_enabled(True)
        self._refresh_banner()
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(True)
        ok = sum(1 for e in entries if e["status"] == "ok")
        failed = len(entries) - ok
        self.statusBar().showMessage(
            "%d blocks: %d recovered, %d failed — %s"
            % (len(entries), ok, failed, self.current_path))
        # Zip-like feel: show the first recovered file right away.
        for r in range(self.table.rowCount()):
            if self.table.item(r, 6).text() == "ok" \
                    and not self.table.isRowHidden(r):
                self.table.selectRow(r)
                break

    # ------------------------------------------------------- folder filter
    def apply_folder_filter(self, folder):
        """Show only files under `folder` (None = everything)."""
        self.current_folder = folder
        self._apply_filters()

    def _apply_filters(self):
        """Combine folder selection, live text filter and the show combo."""
        folder = self.current_folder
        text = self.filter_edit.text().strip().lower()
        mode = self.show_combo.currentText() if hasattr(self, "show_combo") \
            else "all files"
        # Iterate *visual* rows — the table may be sorted, so the row index
        # is not the entry index.
        for r in range(self.table.rowCount()):
            e = self.table.entry_at(r)
            name = (e.get("name") if e else "") or ""
            visible = True
            if folder is not None:
                visible = bool(name) and name.replace(
                    "/", "\\").startswith(folder + "\\")
            if visible and text:
                visible = text in name.lower()
            if visible and mode != "all files" and e is not None:
                if mode == "named only":
                    visible = bool(name)
                elif mode == "unnamed only":
                    visible = not name
                elif mode == "failed only":
                    visible = e["status"] != "ok"
                elif mode == "encrypted only":
                    visible = bool(e["flags"] & 0x00010000)
            self.table.setRowHidden(r, not visible)
        # Keep a visible selection so preview/extract stay usable.
        if self.table.currentRow() < 0 or \
                self.table.isRowHidden(self.table.currentRow()):
            self.preview.clear()
            self._show_text_page()
            for r in range(self.table.rowCount()):
                if not self.table.isRowHidden(r) \
                        and self.table.item(r, 6).text() == "ok":
                    self.table.selectRow(r)
                    break
        shown = sum(1 for r in range(self.table.rowCount())
                    if not self.table.isRowHidden(r))
        label = "(all files)" if folder is None else folder + "\\"
        if text:
            label += " matching “%s”" % text
        self.statusBar().showMessage("%s — %d of %d file(s)"
                                     % (label, shown, self.table.rowCount()))

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
            self._show_text_page()
            return
        name, data = e["name"], e["data"]
        # A texture is recognised by its magic bytes, not only by its
        # name: protected maps destroy the original file names.
        if (name and name.lower().endswith(".blp")) or \
                data[:4] in (b"BLP1", b"BLP2"):
            if self._show_image(name, data):
                return
        if _is_text(name, data):
            text = data[:TEXT_PREVIEW_LIMIT].decode("utf-8", "replace")
            if len(data) > TEXT_PREVIEW_LIMIT:
                text += "\n… (truncated)"
            self._show_text_page()
            self.preview.setPlainText(text)
            self._apply_highlighter(name, text)
        else:
            self._show_text_page()
            self.preview.setPlainText(
                "%d bytes — hex dump of first %d:\n\n%s"
                % (len(data), min(len(data), HEX_PREVIEW_LIMIT),
                   _hexdump(data)))

    # ------------------------------------------------------ image preview
    def _show_text_page(self):
        self.preview_stack.setCurrentIndex(0)

    def _show_image(self, name, data):
        """Render a .blp texture into the preview pane.

        Returns True when the image could be shown.
        """
        try:
            blp = open_blp(data)
        except Exception as exc:                          # noqa: BLE001
            self._show_text_page()
            self.preview.setPlainText("Could not read %s:\n%s"
                                      % (name, exc))
            return False
        try:
            if blp.is_jpeg:
                # Warcraft III 1.22+ stores textures as a JPEG whose
                # frame header is split across the file; the decoder
                # stitches it back together.
                blob = blp.jpeg_bytes(0)
                image = QImage()
                if not image.loadFromData(blob):
                    raise ValueError("Qt could not decode the JPEG stream")
            else:
                image = QImage.fromData(blp.png_bytes(0))
                if image.isNull():
                    raise ValueError("unsupported BLP encoding")
        except Exception as exc:                          # noqa: BLE001
            self._show_text_page()
            self.preview.setPlainText("Could not render %s:\n%s"
                                      % (name, exc))
            return False
        image = image.convertToFormat(QImage.Format_ARGB32)
        pixmap = QPixmap.fromImage(image)
        self.image_label.setPixmap(pixmap.scaled(
            pixmap.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.image_scroll.setWidget(self.image_label)
        self.preview_stack.setCurrentIndex(1)
        mip = blp.mipmaps[0] if blp.mipmaps else None
        if mip:
            self.statusBar().showMessage(
                "%s — %dx%d %s, %d mipmap level(s)"
                % (name, mip.width, mip.height, blp.kind.upper(),
                   len(blp.mipmaps)))
        return True

    # ------------------------------------------------------- highlighting
    def _apply_highlighter(self, name, text):
        """Colour JASS sources; plain text for everything else."""
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
            self._highlighter = None
        if is_jass(name or ""):
            self._highlighter = JassHighlighter(self.preview.document())
            self.preview.setPlainText(text)

    # ------------------------------------------------- in-file search
    def _toggle_find(self):
        self._find_row_widget.setVisible(not self._find_row_widget.isVisible())
        for w in (self.find_edit, self.find_prev, self.find_next,
                  self.find_count):
            w.setVisible(self._find_row_widget.isVisible())
        if self._find_row_widget.isVisible():
            self.find_edit.setFocus()
            self.find_edit.selectAll()

    def _hide_find(self):
        self._find_row_widget.setVisible(False)
        for w in (self.find_edit, self.find_prev, self.find_next,
                  self.find_count):
            w.setVisible(False)

    def _find_changed(self, text):
        if not text:
            self.find_count.setText("")
            return
        self._find_next(backwards=True)

    def _find_next(self, backwards=False):
        needle = self.find_edit.text()
        if not needle:
            return
        if backwards:
            found = self.preview.find(needle, QTextDocument.FindBackward)
        else:
            found = self.preview.find(needle)
        if found:
            self.preview.setTextCursor(self.preview.textCursor())
            self.find_count.setText("found")
        else:
            self.find_count.setText("not found")

    # ------------------------------------------------------------ extract
    def _extract(self):
        if not self._require_archive():
            return
        outdir = QFileDialog.getExistingDirectory(
            self, "Extract into folder",
            self.settings.value("last_dir", ""))
        if not outdir:
            return
        self.settings.setValue("last_dir", outdir)
        self._run("Extracting to %s…" % outdir,
                  ExtractWorker(self.current_path, outdir),
                  on_done=lambda m: self._extract_done(m, outdir))

    def _selected_names(self):
        """Names of the selected, successfully recovered files."""
        names = []
        for e in self.table.selected_entries():
            if e["status"] == "ok" and e["name"]:
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

    # ------------------------------------------------- file actions
    def _current_entry(self):
        """The entry behind the current selection (if any)."""
        row = self.table.currentRow()
        return self.table.entry_at(row)

    def _save_preview(self):
        """Save the selected file's bytes without extracting the archive."""
        e = self._current_entry()
        if e is None or e["status"] != "ok" or e.get("data") is None:
            QMessageBox.information(self, "Nothing to save",
                                    "Select a recovered file first.")
            return
        suggested = (e["name"] or ("block_%03d" % e["block"])).replace("\\", "_")
        out, _ = QFileDialog.getSaveFileName(self, "Save file as", suggested)
        if not out:
            return
        try:
            self._save_entry_to(e, out)
        except OSError as exc:
            QMessageBox.critical(self, "Could not save", str(exc))
            return
        self.statusBar().showMessage("Saved %s" % out)

    def _save_entry_to(self, entry, path):
        """Write one recovered entry to `path`. Returns bytes written."""
        with open(path, "wb") as f:
            f.write(entry["data"])
        return len(entry["data"])

    def _open_containing_folder(self):
        if not self.current_path:
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(os.path.dirname(os.path.abspath(self.current_path)))
            elif sys.platform == "darwin":
                os.system('open "%s"' % os.path.dirname(
                    os.path.abspath(self.current_path)))
            else:
                os.system('xdg-open "%s"' % os.path.dirname(
                    os.path.abspath(self.current_path)))
        except Exception as exc:
            QMessageBox.critical(self, "Could not open folder", str(exc))

    def _export_table(self):
        """Export the recovered file table as CSV or JSON."""
        if not self.current_entries:
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Export file table", "files.json",
            "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        try:
            count = self._write_table(path)
        except OSError as exc:
            QMessageBox.critical(self, "Could not export", str(exc))
            return
        self.statusBar().showMessage("Exported %d rows to %s"
                                     % (count, path))

    def _table_rows(self):
        """The recovered file table as plain dicts (export format)."""
        rows = []
        for e in self.current_entries or []:
            rows.append(dict(
                block=e["block"], name=e["name"] or "", size=e["size"],
                archived_size=e["archived_size"],
                flags=e["flags"], status=e["status"],
                name_source=e.get("name_source"),
                key_method=e.get("key_method"), sha256=e.get("sha256")))
        return rows

    def _write_table(self, path):
        """Write the table to `path` (.csv or .json). Returns the row count."""
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

    # ------------------------------------------------- recent files
    def _fill_recent_menu(self):
        self.recent_menu.clear()
        for path in self.settings.value("recent", []) or []:
            act = QAction(path, self)
            act.triggered.connect(lambda _=False, p=path:
                                   self.open_archive(p))
            self.recent_menu.addAction(act)
        if not self.recent_menu.actions():
            act = QAction("(no recent files)", self)
            act.setEnabled(False)
            self.recent_menu.addAction(act)

    def _remember_recent(self, path):
        recent = [p for p in (self.settings.value("recent", []) or [])
                  if p != path]
        recent.insert(0, path)
        self.settings.setValue("recent", recent[:10])

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
            self.statusBar().showMessage("Ready")
            on_done(result)

        def failed(err):
            self.setEnabled(True)
            self.statusBar().showMessage("Ready")
            QMessageBox.critical(self, "Task failed", err)

        worker.result_ready.connect(done)
        worker.failed.connect(failed)
        # Release the worker only once the thread has really finished.
        worker.finished.connect(lambda w=worker: self._release_worker(w))
        worker.start()

    def _on_task_failed(self, err):
        self.current_path = None
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
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
