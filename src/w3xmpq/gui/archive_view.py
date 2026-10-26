# -*- coding: utf-8 -*-
"""One archive, one pane.

:class:`ArchiveView` is everything that belongs to a *single* open
archive: the banner, the filter row, the folder tree, the file table and
the preview.  :class:`~w3xmpq.gui.main_window.MainWindow` hosts any
number of them in tabs, so all per-archive state (scan worker, entries,
selection, filters, preview) lives here and nothing leaks between tabs.

The widget talks to its host through signals — it never reaches for
``self.window()``:

    status(str)      a message for the status bar
    busy(bool)       a background task started / finished
    title_changed()  the tab label should be refreshed
    loaded()         the scan finished successfully
    open_failed(str) the archive could not be read
"""

import os
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (QColor, QFont, QImage, QKeySequence, QPixmap,
                           QShortcut, QTextDocument)
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.blp import open_blp
from ..core.report import build_report, render_report
from ..core.safety import scan_safety, render_safety
from ..core.w3x_header import is_w3x, parse_header
from . import theme
from .dialogs import ARCHIVE_FILTER, FnWorker, TextDialog, open_folder
from .jass_highlight import JassHighlighter, is_jass
from .workers import ExtractWorker, RebuildWorker, ScanWorker

TEXT_EXT = (".j", ".txt", ".ai", ".md", ".csv", ".json", ".xml", ".ini",
            ".wct", ".wtg")
HEX_PREVIEW_LIMIT = 8 * 1024      # bytes shown in the hex pane
TEXT_PREVIEW_LIMIT = 200 * 1024   # bytes shown in the text pane

FLAGS_SHORT = [(0x80000000, "E"), (0x00000200, "Z"), (0x00010000, "K"),
               (0x01000000, "S"), (0x04000000, "C"), (0x00040000, "P")]

SHOW_MODES = ["all files", "named only", "unnamed only", "failed only",
              "encrypted only"]

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


def preview_text(name, data):
    """Text shown for a file in a preview pane (text or hex dump)."""
    if _is_text(name, data):
        text = data[:TEXT_PREVIEW_LIMIT].decode("utf-8", "replace")
        if len(data) > TEXT_PREVIEW_LIMIT:
            text += "\n… (truncated)"
        return text
    return ("%d bytes — hex dump of first %d:\n\n%s"
            % (len(data), min(len(data), HEX_PREVIEW_LIMIT), _hexdump(data)))


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
        palette = theme.colors()
        bad, muted = QColor(palette["bad"]), QColor(palette["muted"])
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
                    item.setForeground(bad)
                elif col == 1 and not e["name"]:
                    item.setForeground(muted)
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

    def reload_keeping_selection(self):
        """Rebuild the rows (new colours) without losing the selection.

        Rebuilding clears the table, which would otherwise fire a
        selection change and throw the preview back to the first file —
        the theme toggle must not look like "you clicked another file".
        """
        entry = self.entry_at(self.currentRow())
        self.blockSignals(True)
        self.load_entries(self.entries)
        self.blockSignals(False)
        if entry is None:
            return
        for r in range(self.rowCount()):
            if self.entry_at(r) is entry:
                self.selectRow(r)
                break

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
    folder asks the view to filter the file table to it; the top-level
    "(all files)" item clears the filter.
    """

    folder_selected = Signal(object)      # str or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setMaximumWidth(260)
        self.itemSelectionChanged.connect(self._emit_selection)

    def _emit_selection(self):
        items = self.selectedItems()
        if items:
            self.folder_selected.emit(items[0].data(0, Qt.UserRole))

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


class ArchiveView(QWidget):
    """Everything about one open archive, ready to sit in a tab."""

    status = Signal(str)
    busy = Signal(bool)
    title_changed = Signal()
    loaded = Signal()
    open_failed = Signal(str)

    def __init__(self, path, settings=None, show_filter=0, parent=None):
        super().__init__(parent)
        self.current_path = path
        self.current_entries = None
        self.current_folder = None      # None = all files
        self.worker = None
        self._highlighter = None        # JASS syntax highlighter (preview)
        self.settings = settings
        self._show_filter = show_filter
        self._build_ui()

    # ------------------------------------------------------------ title
    @property
    def title(self):
        return os.path.basename(self.current_path or "archive")

    def summary(self):
        """One-line description for the tab tooltip."""
        if not self.current_entries:
            return self.current_path or ""
        ok = sum(1 for e in self.current_entries if e["status"] == "ok")
        return "%s\n%d of %d blocks recovered" % (
            self.current_path, ok, len(self.current_entries))

    # ------------------------------------------------------------ UI setup
    def _build_ui(self):
        self.banner = QLabel(
            "Scanning %s…" % self.current_path)
        self.banner.setStyleSheet(
            "QLabel { padding: 8px; background: palette(midlight);"
            " border-radius: 4px; }")
        self.banner.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.banner.setWordWrap(True)
        # Keep the banner compact so the file table gets the screen space.
        self.banner.setMaximumHeight(64)

        self.folders = FolderTree()
        self.folders.folder_selected.connect(self.apply_folder_filter)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("filter files… (Ctrl+F)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filters)
        # Scoped to this pane: with several tabs open, a window-level
        # shortcut would be ambiguous and fire on the wrong archive.
        self._filter_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._filter_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._filter_shortcut.activated.connect(self.filter_edit.setFocus)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setVisible(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_scan)

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
            "textures as pictures, everything else as a hex dump).")

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
        # Keep a reference to the shortcut: a QShortcut that is garbage
        # collected while its parent lives crashes Qt.
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        self._find_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
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
        self.show_combo.addItems(SHOW_MODES)
        if 0 <= self._show_filter < self.show_combo.count():
            self.show_combo.setCurrentIndex(self._show_filter)
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self.banner)
        layout.addWidget(top_row_widget)
        layout.addWidget(splitter)

    # ------------------------------------------------------------ scanning
    def start_scan(self):
        self.status.emit("Scanning %s…" % os.path.basename(self.current_path))
        self.banner.setText("Scanning %s…" % self.current_path)
        self.progress.setRange(0, 0)          # busy indicator
        self.progress.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self.worker = ScanWorker(self.current_path)
        self.worker.result_ready.connect(self._on_scanned)
        self.worker.failed.connect(self._on_task_failed)
        self.worker.progress.connect(self._on_scan_progress)
        # Keep the worker alive until the thread has really finished —
        # dropping the reference from inside the result handler destroys
        # the QThread while run() is still on the stack, which crashes Qt.
        self.worker.finished.connect(
            lambda w=self.worker: self._release_worker(w))
        self.busy.emit(True)
        self.worker.start()

    def _release_worker(self, worker):
        """Forget a finished worker (QThread.finished == run() returned)."""
        if self.worker is worker:
            self.worker = None
            self.busy.emit(False)

    def _on_scan_progress(self, done, total):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.status.emit("Scanning… %d / %d blocks" % (done, total))

    def cancel_scan(self):
        if self.worker is not None and hasattr(self.worker, "cancel"):
            self.worker.cancel()
            self.status.emit("Cancelling…")
            self.cancel_btn.setEnabled(False)

    def _on_scanned(self, entries):
        self.current_entries = entries
        self.current_folder = None
        self.table.load_entries(entries)
        self.folders.load_entries(entries)
        self.preview.clear()
        self._show_text_page()
        self._refresh_banner()
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        ok = sum(1 for e in entries if e["status"] == "ok")
        failed = len(entries) - ok
        self.status.emit("%d blocks: %d recovered, %d failed — %s"
                         % (len(entries), ok, failed, self.current_path))
        # Zip-like feel: show the first recovered file right away.
        for r in range(self.table.rowCount()):
            if self.table.item(r, 6).text() == "ok" \
                    and not self.table.isRowHidden(r):
                self.table.selectRow(r)
                break
        self.title_changed.emit()
        self.loaded.emit()

    def _on_task_failed(self, err):
        self.current_path = None
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.banner.setText("Could not read that file — see the error "
                            "dialog for details.")
        self.open_failed.emit(err)

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
        self.status.emit("%s — %d of %d file(s)"
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
            self.status.emit(
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
    def _last_dir(self):
        return self.settings.value("last_dir", "") if self.settings else ""

    def extract(self):
        if not self._require_archive():
            return
        outdir = QFileDialog.getExistingDirectory(
            self, "Extract into folder", self._last_dir())
        if not outdir:
            return
        if self.settings:
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

    def extract_selected(self):
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
            self.status.emit(
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
            menu.addAction("Extract selected…", self.extract_selected)
            menu.addAction("Copy name",
                           lambda: QGuiApplication.clipboard().setText(
                               e["name"] or ""))
        else:
            menu.addAction("Extract selected…", self.extract_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _focus_preview_row(self):
        self._focus_preview(self.table.currentRow(), 0)

    # ------------------------------------------------- file actions
    def _current_entry(self):
        """The entry behind the current selection (if any)."""
        row = self.table.currentRow()
        return self.table.entry_at(row)

    def save_preview(self):
        """Save the selected file's bytes without extracting the archive."""
        e = self._current_entry()
        if e is None or e["status"] != "ok" or e.get("data") is None:
            QMessageBox.information(self, "Nothing to save",
                                    "Select a recovered file first.")
            return
        suggested = (e["name"] or ("block_%03d" % e["block"])).replace(
            "\\", "_")
        out, _ = QFileDialog.getSaveFileName(self, "Save file as", suggested)
        if not out:
            return
        try:
            self._save_entry_to(e, out)
        except OSError as exc:
            QMessageBox.critical(self, "Could not save", str(exc))
            return
        self.status.emit("Saved %s" % out)

    def _save_entry_to(self, entry, path):
        """Write one recovered entry to `path`. Returns bytes written."""
        with open(path, "wb") as f:
            f.write(entry["data"])
        return len(entry["data"])

    def open_containing_folder(self):
        if not self.current_path:
            return
        try:
            open_folder(self.current_path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open folder", str(exc))

    def export_table(self):
        """Export the recovered file table as CSV or JSON."""
        if not self.current_entries:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self, "Export file table", "files.json",
            "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        try:
            count = self._write_table(path)
        except OSError as exc:
            QMessageBox.critical(self, "Could not export", str(exc))
            return
        self.status.emit("Exported %d rows to %s" % (count, path))

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

    # ------------------------------------------------------------ report
    def report(self):
        if not self._require_archive():
            return
        self._run("Building deprotection report…",
                  FnWorker(build_report, self.current_path),
                  on_done=lambda rep: TextDialog(
                      self, "Deprotection report",
                      render_report(rep)).exec())

    # ------------------------------------------------------------ scan
    def safety_scan(self):
        if not self._require_archive():
            return
        self._run("Running safety scan…",
                  FnWorker(scan_safety, self.current_path),
                  on_done=lambda res: TextDialog(
                      self, "Map safety scan",
                      render_safety(res)).exec())

    # ------------------------------------------------------------ rebuild
    def rebuild(self):
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
        self.status.emit(message)
        self.worker = worker
        self._on_done = on_done
        worker.result_ready.connect(on_done)
        worker.failed.connect(
            lambda err: QMessageBox.critical(self, "Task failed", err))
        # Release the worker only once the thread has really finished.
        worker.finished.connect(lambda w=worker: self._release_worker(w))
        self.busy.emit(True)
        worker.start()

    # ------------------------------------------------------------ theme
    def on_theme_changed(self):
        """Repaint the parts that choose colours by hand."""
        if self.current_entries:
            self.table.reload_keeping_selection()
        if self.preview_stack.currentIndex() == 0 and self._highlighter:
            self._preview_selected()

    # ------------------------------------------------------------ closing
    def shutdown(self):
        """Stop the background task before the widget is destroyed."""
        worker = self.worker
        if worker is None:
            return
        if hasattr(worker, "cancel"):
            worker.cancel()
        if worker.isRunning():
            worker.wait(3000)
