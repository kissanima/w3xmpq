# -*- coding: utf-8 -*-
"""The in-app archive diff.

Comparing two maps used to open a text dialog listing counts. This is a
proper view: a change table, a filter, and the two versions of a file
side by side with a line-level difference count.

It lives in a tab like an archive does, so a diff stays open next to the
maps it compares.
"""

import difflib
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCursor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPlainTextEdit, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import theme
from .archive_view import preview_text
from .workers import DiffWorker

#: What the group combo can show.
GROUPS = ["differences only", "changed", "only in A", "only in B",
          "identical files"]

KIND_LABEL = {"changed": "changed", "only_a": "only in A",
              "only_b": "only in B", "same": "identical"}

KIND_COLOUR = {"changed": "changed", "only_a": "bad", "only_b": "good",
               "same": "muted"}


def _short(sha):
    return (sha or "")[:12]


def build_rows(result):
    """Flatten a diff result into table rows (changed first)."""
    rows = []
    for c in result.get("changed", []):
        rows.append(dict(kind="changed", name=c["name"],
                         size_a=c.get("size_a"), size_b=c.get("size_b"),
                         sha_a=(c.get("a") or {}).get("sha256"),
                         sha_b=(c.get("b") or {}).get("sha256"),
                         a=c.get("a"), b=c.get("b")))
    for e in result.get("only_a", []):
        rows.append(dict(kind="only_a", name=e.get("name") or
                         "<block %d>" % e["block"], size_a=e["size"],
                         size_b=None, sha_a=e.get("sha256"), sha_b=None,
                         a=e, b=None))
    for e in result.get("only_b", []):
        rows.append(dict(kind="only_b", name=e.get("name") or
                         "<block %d>" % e["block"], size_a=None,
                         size_b=e["size"], sha_a=None,
                         sha_b=e.get("sha256"), a=None, b=e))
    for e in result.get("same_named", []):
        rows.append(dict(kind="same", name=e["name"], size_a=e.get("size"),
                         size_b=e.get("size"), sha_a=e.get("sha256"),
                         sha_b=e.get("sha256"), a=None, b=None))
    return rows


def line_diff(a_text, b_text):
    """(+added, -removed) line counts between two texts."""
    if a_text is None or b_text is None:
        return None
    a_lines = a_text.splitlines()
    b_lines = b_text.splitlines()
    added = removed = 0
    for line in difflib.unified_diff(a_lines, b_lines, n=0, lineterm=""):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def first_difference(a_text, b_text):
    """Line numbers of the first differing line, one per side.

    Used to scroll both panes to where the change actually is — a 4000
    line script should not open at line 1 and hide its one edited line.
    """
    if a_text is None or b_text is None:
        return None
    matcher = difflib.SequenceMatcher(None, a_text.splitlines(),
                                      b_text.splitlines(), autojunk=False)
    for tag, i1, _i2, j1, _j2 in matcher.get_opcodes():
        if tag != "equal":
            return i1, j1
    return None


class DiffView(QWidget):
    """Side-by-side comparison of two archives, in a tab."""

    status = Signal(str)
    title_changed = Signal()
    busy = Signal(bool)

    def __init__(self, path_a, path_b, parent=None):
        super().__init__(parent)
        self.path_a = path_a
        self.path_b = path_b
        self.worker = None
        self.result = None
        self.rows = []
        self._build_ui()

    # ------------------------------------------------------------ title
    @property
    def title(self):
        return "%s ↔ %s" % (os.path.basename(self.path_a),
                            os.path.basename(self.path_b))

    def summary(self):
        if not self.result:
            return "%s\n%s" % (self.path_a, self.path_b)
        return "%s\n%s\n%d changed, %d only in A, %d only in B, %d identical" % (
            self.path_a, self.path_b, len(self.result["changed"]),
            len(self.result["only_a"]), len(self.result["only_b"]),
            len(self.result["same_named"]))

    # ------------------------------------------------------------ UI setup
    def _build_ui(self):
        self.header = QLabel("Comparing <b>%s</b> with <b>%s</b>…"
                             % (os.path.basename(self.path_a),
                                os.path.basename(self.path_b)))
        self.header.setWordWrap(True)
        self.header.setStyleSheet(
            "QLabel { padding: 8px; background: palette(midlight);"
            " border-radius: 4px; }")
        self.header.setMaximumHeight(64)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("filter by file name…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filters)
        self.group_combo = QComboBox()
        self.group_combo.addItems(GROUPS)
        self.group_combo.currentIndexChanged.connect(self._apply_filters)
        self.counts = QLabel("")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.filter_edit, 1)
        row.addWidget(self.group_combo)
        row.addWidget(self.counts)
        row_widget = QWidget()
        row_widget.setLayout(row)
        row_widget.setSizePolicy(row_widget.sizePolicy().horizontalPolicy(),
                                 row_widget.sizePolicy().verticalPolicy())

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Status", "Name", "A size", "B size", "Δ", "A sha", "B sha"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (0, 2, 3, 4, 5, 6):
            head.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._show_selected)

        self.label_a = QLabel("A")
        self.label_b = QLabel("B")
        self.diff_label = QLabel("")
        self.diff_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        labels = QHBoxLayout()
        labels.setSpacing(8)
        labels.addWidget(self.label_a, 1)
        labels.addWidget(self.label_b, 1)
        labels.addWidget(self.diff_label)

        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        self.pane_a = QPlainTextEdit()
        self.pane_b = QPlainTextEdit()
        for pane in (self.pane_a, self.pane_b):
            pane.setReadOnly(True)
            pane.setFont(font)
            pane.setPlaceholderText("select a file above")
        panes = QSplitter()
        panes.addWidget(self.pane_a)
        panes.addWidget(self.pane_b)
        panes.setSizes([500, 500])

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(4)
        lower_layout.addLayout(labels)
        lower_layout.addWidget(panes)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(lower)
        split.setSizes([250, 380])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self.header)
        layout.addWidget(row_widget)
        layout.addWidget(split)

    # ------------------------------------------------------------ scanning
    def start(self):
        self.status.emit("Comparing %s with %s…"
                         % (os.path.basename(self.path_a),
                            os.path.basename(self.path_b)))
        self.worker = DiffWorker(self.path_a, self.path_b, with_data=True)
        self.worker.result_ready.connect(self._on_result)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(
            lambda w=self.worker: self._release_worker(w))
        self.busy.emit(True)
        self.worker.start()

    def _release_worker(self, worker):
        if self.worker is worker:
            self.worker = None
            self.busy.emit(False)

    def _on_result(self, result):
        self.result = result
        self.rows = build_rows(result)
        self._fill_table()
        meta_a, meta_b = result["meta_a"], result["meta_b"]
        self.header.setText(
            "<b>%s</b> (%d blocks, %d recovered) → <b>%s</b> "
            "(%d blocks, %d recovered) · <b>%d</b> changed · "
            "<b>%d</b> only in A · <b>%d</b> only in B · "
            "<b>%d</b> identical"
            % (os.path.basename(self.path_a), meta_a["blocks"], meta_a["ok"],
               os.path.basename(self.path_b), meta_b["blocks"], meta_b["ok"],
               len(result["changed"]), len(result["only_a"]),
               len(result["only_b"]), len(result["same_named"])))
        self.counts.setText("%d row(s)" % len(self.rows))
        self.status.emit("%d differences — %s"
                         % (len(result["changed"]) + len(result["only_a"]) +
                            len(result["only_b"]), self.title))
        self.title_changed.emit()
        # Land on the first real difference.
        for r in range(self.table.rowCount()):
            if not self.table.isRowHidden(r):
                self.table.selectRow(r)
                break

    def _on_failed(self, err):
        self.header.setText("Could not compare these archives.")
        self.status.emit("Diff failed")
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "Could not compare", err)

    # ------------------------------------------------------------ table
    def _fill_table(self):
        self.table.setRowCount(len(self.rows))
        palette = theme.colors()
        for i, row in enumerate(self.rows):
            delta = ""
            if row["size_a"] is not None and row["size_b"] is not None:
                d = row["size_b"] - row["size_a"]
                delta = ("%+d" % d) if d else "0"
            cells = [KIND_LABEL[row["kind"]], row["name"],
                     _fmt_size(row["size_a"]), _fmt_size(row["size_b"]),
                     delta, _short(row["sha_a"]), _short(row["sha_b"])]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, i)
                if col in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 0:
                    item.setForeground(
                        QColor(palette[KIND_COLOUR[row["kind"]]]))
                self.table.setItem(i, col, item)
        self._apply_filters()

    def _row_at(self, visual_row):
        item = self.table.item(visual_row, 0)
        if item is None:
            return None
        idx = item.data(Qt.UserRole)
        if idx is None or not (0 <= idx < len(self.rows)):
            return None
        return self.rows[idx]

    def _apply_filters(self):
        text = self.filter_edit.text().strip().lower()
        group = self.group_combo.currentText()
        shown = 0
        for r in range(self.table.rowCount()):
            row = self._row_at(r)
            if row is None:
                continue
            visible = True
            if group == "differences only":
                visible = row["kind"] != "same"
            elif group == "changed":
                visible = row["kind"] == "changed"
            elif group == "only in A":
                visible = row["kind"] == "only_a"
            elif group == "only in B":
                visible = row["kind"] == "only_b"
            elif group == "identical files":
                visible = row["kind"] == "same"
            if visible and text:
                visible = text in row["name"].lower()
            self.table.setRowHidden(r, not visible)
            shown += 1 if visible else 0
        self.counts.setText("%d of %d row(s)" % (shown, len(self.rows)))
        if shown:
            cur = self.table.currentRow()
            if cur < 0 or self.table.isRowHidden(cur):
                for r in range(self.table.rowCount()):
                    if not self.table.isRowHidden(r):
                        self.table.selectRow(r)
                        break

    # ------------------------------------------------------------ panes
    def _show_selected(self):
        row = self._row_at(self.table.currentRow())
        if row is None:
            return
        name = row["name"]
        self.label_a.setText("<b>A</b> — %s" % name)
        self.label_b.setText("<b>B</b> — %s" % name)
        text_a = _entry_text(row["a"])
        text_b = _entry_text(row["b"])
        self.pane_a.setPlainText(text_a if text_a is not None
                                 else "(not in A)")
        self.pane_b.setPlainText(text_b if text_b is not None
                                 else "(not in B)")
        counts = line_diff(text_a, text_b)
        if counts is None:
            self.diff_label.setText("")
        else:
            added, removed = counts
            self.diff_label.setText("<span style='color:%s'>+%d</span> "
                                    "<span style='color:%s'>−%d</span> lines"
                                    % (theme.colors()["good"], added,
                                       theme.colors()["bad"], removed))
        # Jump to the change instead of showing line 1 of a long file.
        spot = first_difference(text_a, text_b)
        if spot:
            self._scroll_to(self.pane_a, spot[0])
            self._scroll_to(self.pane_b, spot[1])

    @staticmethod
    def _scroll_to(pane, line):
        cursor = pane.textCursor()
        cursor.movePosition(QTextCursor.Start)
        if line:
            cursor.movePosition(QTextCursor.Down, QTextCursor.MoveAnchor, line)
        pane.setTextCursor(cursor)
        pane.centerCursor()

    # ------------------------------------------------------------ theme
    def on_theme_changed(self):
        self._fill_table()

    # ------------------------------------------------------------ closing
    def shutdown(self):
        worker = self.worker
        if worker is not None and worker.isRunning():
            worker.wait(3000)


def _fmt_size(value):
    return "" if value is None else "{:,}".format(value)


def _entry_text(entry):
    """Previewable text for one side of a row (None when absent)."""
    if not entry or entry.get("data") is None:
        return None
    data = entry["data"]
    name = entry.get("name") or ""
    if data[:4] in (b"BLP1", b"BLP2"):
        from ..core.blp import open_blp
        try:
            blp = open_blp(data)
            mip = blp.mipmaps[0] if blp.mipmaps else None
            if mip:
                return ("[%s texture %d×%d, %d mipmap level(s) — %d bytes]\n"
                        "Open the archive tab to see it rendered."
                        % (blp.kind.upper(), mip.width, mip.height,
                           len(blp.mipmaps), len(data)))
        except Exception:                                # noqa: BLE001
            pass
    return preview_text(name, data)
