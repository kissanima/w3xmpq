# -*- coding: utf-8 -*-
"""The in-app archive diff — a real side-by-side view.

The old viewer computed a line diff but showed two uncoloured panes, had
no next/previous change, and rendered a BLP as a text placeholder.  This
one highlights changed lines inline from ``difflib`` opcodes, offers
\u25b2/\u25bc navigation between hunks, renders textures as images, and puts
a colour-coded change summary above the table.

The helper functions (:func:`build_rows`, :func:`line_diff`,
:func:`first_difference`) are pure and kept for the test suite / CLI.
"""

import difflib
import html
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPixmap, QTextCursor
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTextBrowser,
                               QVBoxLayout, QWidget)

from ..core.blp import open_blp
from . import theme
from .preview_pane import preview_text
from .tasks import TaskManager
from .workers import DiffWorker

GROUPS = ["differences only", "changed", "only in A", "only in B",
          "identical files"]

KIND_LABEL = {"changed": "changed", "only_a": "only in A",
              "only_b": "only in B", "same": "identical"}

KIND_COLOUR = {"changed": "warn", "only_a": "danger", "only_b": "success",
               "same": "muted"}

#: Summary chips in order, with their semantic colour token.
SUMMARY = (("changed", "changed", "warn"),
           ("only_a", "only in A", "danger"),
           ("only_b", "only in B", "success"),
           ("same_named", "identical", "muted"))


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
    """Line numbers of the first differing line, one per side."""
    if a_text is None or b_text is None:
        return None
    matcher = difflib.SequenceMatcher(None, a_text.splitlines(),
                                      b_text.splitlines(), autojunk=False)
    for tag, i1, _i2, j1, _j2 in matcher.get_opcodes():
        if tag != "equal":
            return i1, j1
    return None


def _line(text, bg=None, fg=None, anchor=None):
    escaped = html.escape(text) or "&nbsp;"
    style = "white-space:pre; padding:0 6px;"
    if bg:
        style += "background:%s;" % bg
    if fg:
        style += "color:%s;" % fg
    tag = ('<a name="%s"></a>' % anchor) if anchor else ""
    return '<div style="%s">%s%s</div>' % (style, tag, escaped)


def build_diff_html(a_text, b_text, tokens):
    """Return (html_a, html_b, changes) with inline highlights.

    ``changes`` holds (block_a, block_b) for each hunk; the shorter side
    is padded with blank lines so the two panes stay aligned.
    """
    a_lines = (a_text or "").splitlines()
    b_lines = (b_text or "").splitlines()
    matcher = difflib.SequenceMatcher(None, a_lines, b_lines, autojunk=False)
    ha, hb, changes = [], [], []
    block_a = block_b = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        la, lb = a_lines[i1:i2], b_lines[j1:j2]
        if tag == "equal":
            for ln in la:
                ha.append(_line(ln))
                block_a += 1
            for ln in lb:
                hb.append(_line(ln))
                block_b += 1
            continue
        hunk = len(changes)
        changes.append((block_a, block_b))
        n = max(len(la), len(lb), 1)
        la = la + [""] * (n - len(la))
        lb = lb + [""] * (n - len(lb))
        for k in range(n):
            anchor = "c%d" % hunk if k == 0 else None
            ha.append(_line(la[k], tokens["diff_del_bg"],
                            tokens["diff_del_fg"], anchor))
            hb.append(_line(lb[k], tokens["diff_add_bg"],
                            tokens["diff_add_fg"], anchor))
            block_a += 1
            block_b += 1
    return "".join(ha), "".join(hb), changes


class DiffView(QWidget):
    """Side-by-side comparison of two archives, in a tab."""

    status = Signal(str)
    title_changed = Signal()
    busy = Signal(bool)

    def __init__(self, path_a, path_b, tasks=None, parent=None):
        super().__init__(parent)
        self.path_a = path_a
        self.path_b = path_b
        self.tasks = tasks or TaskManager(self)
        self._job = None
        self.result = None
        self.rows = []
        self._changes = []
        self._change_index = -1
        self._build_ui()

    # ------------------------------------------------------------ title
    @property
    def title(self):
        return "%s \u2194 %s" % (os.path.basename(self.path_a),
                                 os.path.basename(self.path_b))

    def summary(self):
        if not self.result:
            return "%s\n%s" % (self.path_a, self.path_b)
        return "%s\n%s\n%d changed, %d only in A, %d only in B, %d identical" % (
            self.path_a, self.path_b, len(self.result["changed"]),
            len(self.result["only_a"]), len(self.result["only_b"]),
            len(self.result["same_named"]))

    @property
    def worker(self):
        job = self._job
        return job.worker if job is not None and job.active else None

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)

        self.header = QLabel("Comparing <b>%s</b> with <b>%s</b>\u2026"
                             % (os.path.basename(self.path_a),
                                os.path.basename(self.path_b)))
        self.header.setWordWrap(True)
        theme.set_role(self.header, "headline")
        layout.addWidget(self.header)

        self.summary_bar = QFrame()
        theme.set_role(self.summary_bar, "strip")
        sbox = QHBoxLayout(self.summary_bar)
        sbox.setContentsMargins(10, 5, 10, 5)
        sbox.setSpacing(14)
        self.summary_labels = {}
        for key, label, _token in SUMMARY:
            lab = QLabel("\u25cf %s 0" % label)
            self.summary_labels[key] = lab
            sbox.addWidget(lab)
        sbox.addStretch(1)
        layout.addWidget(self.summary_bar)
        self._paint_summary()

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("filter by file name\u2026")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filters)
        self.group_combo = QComboBox()
        self.group_combo.addItems(GROUPS)
        self.group_combo.currentIndexChanged.connect(self._apply_filters)
        self.counts = QLabel("")
        self.prev_btn = QPushButton("\u25b2")
        self.prev_btn.setFixedWidth(30)
        self.prev_btn.setToolTip("Previous change (F2 / Shift+F3)")
        self.prev_btn.clicked.connect(self.previous_change)
        self.next_btn = QPushButton("\u25bc")
        self.next_btn.setFixedWidth(30)
        self.next_btn.setToolTip("Next change (F3)")
        self.next_btn.clicked.connect(self.next_change)
        self.change_label = QLabel("no changes")
        theme.set_role(self.change_label, "dim")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.filter_edit, 1)
        row.addWidget(self.group_combo)
        row.addWidget(self.counts)
        row.addWidget(self.prev_btn)
        row.addWidget(self.next_btn)
        row.addWidget(self.change_label)
        layout.addLayout(row)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Status", "Name", "A size", "B size", "\u0394", "A sha", "B sha"])
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
        self.stack_a, self.pane_a, self.image_a = self._pane(font)
        self.stack_b, self.pane_b, self.image_b = self._pane(font)
        panes = QSplitter()
        panes.addWidget(self.stack_a)
        panes.addWidget(self.stack_b)
        panes.setSizes([500, 500])

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(4)
        lower_layout.addLayout(labels)
        lower_layout.addWidget(panes, 1)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(lower)
        split.setSizes([250, 380])
        layout.addWidget(split, 1)

    @staticmethod
    def _pane(font):
        stack = QStackedWidget()
        text = QTextBrowser()
        text.setReadOnly(True)
        text.setFont(font)
        text.setLineWrapMode(QTextBrowser.NoWrap)
        text.setOpenLinks(False)
        stack.addWidget(text)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)
        image = QLabel("No image")
        image.setAlignment(Qt.AlignCenter)
        scroll.setWidget(image)
        stack.addWidget(scroll)
        return stack, text, image

    # -------------------------------------------------------- scanning
    def start(self):
        self.status.emit("Comparing %s with %s\u2026"
                         % (os.path.basename(self.path_a),
                            os.path.basename(self.path_b)))
        self.busy.emit(True)
        self._job = self.tasks.submit(
            "Compare %s \u2194 %s" % (os.path.basename(self.path_a),
                                      os.path.basename(self.path_b)),
            DiffWorker(self.path_a, self.path_b, with_data=True),
            on_done=self._on_result, on_failed=self._on_failed,
            owner="diff")

    def _on_result(self, result):
        self.result = result
        self.rows = build_rows(result)
        self._fill_table()
        meta_a, meta_b = result["meta_a"], result["meta_b"]
        self.header.setText(
            "<b>%s</b> (%d blocks, %d recovered) \u2192 <b>%s</b> "
            "(%d blocks, %d recovered)"
            % (os.path.basename(self.path_a), meta_a["blocks"], meta_a["ok"],
               os.path.basename(self.path_b), meta_b["blocks"], meta_b["ok"]))
        self._paint_summary()
        self.counts.setText("%d row(s)" % len(self.rows))
        self.status.emit("%d differences \u2014 %s"
                         % (len(result["changed"]) + len(result["only_a"]) +
                            len(result["only_b"]), self.title))
        self.title_changed.emit()
        self.busy.emit(False)
        for r in range(self.table.rowCount()):
            if not self.table.isRowHidden(r):
                self.table.selectRow(r)
                break

    def _on_failed(self, err):
        self.header.setText("Could not compare these archives.")
        self.status.emit("Diff failed: %s" % err)
        self.busy.emit(False)

    def _paint_summary(self):
        t = theme.tokens()
        result = self.result or {}
        for key, label, token in SUMMARY:
            n = len(result.get(key) or [])
            lab = self.summary_labels[key]
            lab.setText("\u25cf %d %s" % (n, label))
            lab.setStyleSheet("QLabel { color: %s; font-weight: 600; }"
                              % t[token])

    # ---------------------------------------------------------- table
    def _fill_table(self):
        self.table.setRowCount(len(self.rows))
        palette = theme.tokens()
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
                    item.setForeground(QColor(palette[KIND_COLOUR[row["kind"]]]))
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

    # ---------------------------------------------------------- panes
    def _show_selected(self):
        row = self._row_at(self.table.currentRow())
        if row is None:
            return
        name = row["name"]
        self.label_a.setText("<b>A</b> \u2014 %s" % html.escape(name))
        self.label_b.setText("<b>B</b> \u2014 %s" % html.escape(name))
        text_a = _entry_text(row["a"])
        text_b = _entry_text(row["b"])
        self._changes = []
        self._change_index = -1

        if _is_blp(row["a"]) or _is_blp(row["b"]):
            self._show_side(self.stack_a, self.pane_a, self.image_a,
                            row["a"], text_a, "(not in A)")
            self._show_side(self.stack_b, self.pane_b, self.image_b,
                            row["b"], text_b, "(not in B)")
            self.diff_label.setText("texture comparison")
            self.change_label.setText("images")
            return

        t = theme.tokens()
        html_a, html_b, self._changes = build_diff_html(text_a, text_b, t)
        self.stack_a.setCurrentIndex(0)
        self.stack_b.setCurrentIndex(0)
        self.pane_a.setHtml(_as_document(html_a, "(not in A)"
                                         if text_a is None else None))
        self.pane_b.setHtml(_as_document(html_b, "(not in B)"
                                         if text_b is None else None))
        counts = line_diff(text_a, text_b)
        if counts is None:
            self.diff_label.setText("")
        else:
            added, removed = counts
            self.diff_label.setText(
                "<span style='color:%s'>+%d</span> "
                "<span style='color:%s'>\u2212%d</span> lines"
                % (t["success"], added, t["danger"], removed))
        self._update_change_label()
        if self._changes:
            self.next_change()

    def _show_side(self, stack, pane, image_label, entry, text,
                   placeholder):
        pixmap = _blp_pixmap(entry)
        if pixmap is not None:
            image_label.setPixmap(pixmap)
            stack.setCurrentIndex(1)
        else:
            pane.setHtml(_as_document(
                "".join(_line(ln) for ln in (text or "").splitlines()),
                placeholder if text is None else None))
            stack.setCurrentIndex(0)

    @staticmethod
    def _scroll_to(pane, line):
        cursor = pane.textCursor()
        cursor.movePosition(QTextCursor.Start)
        if line:
            cursor.movePosition(QTextCursor.Down, QTextCursor.MoveAnchor,
                                line)
        pane.setTextCursor(cursor)
        # QTextBrowser has ensureCursorVisible(), not QPlainTextEdit's
        # centerCursor().  scrollToAnchor() below does the precise jump.
        pane.ensureCursorVisible()

    def _goto_change(self, index):
        if not self._changes:
            return
        self._change_index = index % len(self._changes)
        a, b = self._changes[self._change_index]
        self._scroll_to(self.pane_a, a)
        self._scroll_to(self.pane_b, b)
        anchor = "c%d" % self._change_index
        self.pane_a.scrollToAnchor(anchor)
        self.pane_b.scrollToAnchor(anchor)
        self._update_change_label()

    def next_change(self):
        self._goto_change((self._change_index + 1) % max(len(self._changes), 1))

    def previous_change(self):
        self._goto_change((self._change_index - 1) % max(len(self._changes), 1))

    def _update_change_label(self):
        if not self._changes:
            self.change_label.setText("no changes")
        else:
            self.change_label.setText("change %d / %d"
                                      % (self._change_index + 1,
                                         len(self._changes)))
        for w in (self.prev_btn, self.next_btn):
            w.setEnabled(bool(self._changes))

    # ------------------------------------------------------------ theme
    def on_theme_changed(self):
        self._fill_table()
        self._paint_summary()
        if self.table.currentRow() >= 0:
            self._show_selected()

    # ---------------------------------------------------------- closing
    def shutdown(self):
        if self._job is not None:
            self.tasks.cancel(self._job)


def _as_document(body, placeholder=None):
    t = theme.tokens()
    if placeholder is not None:
        body = "".join(_line(ln) for ln in placeholder.splitlines())
    return ('<html><body style="background:%s;color:%s;'
            'font-family:monospace;">%s</body></html>'
            % (t["surface"], t["text"], body))


def _fmt_size(value):
    return "" if value is None else "{:,}".format(value)


def _is_blp(entry):
    data = (entry or {}).get("data") or b""
    return data[:4] in (b"BLP1", b"BLP2")


def _blp_pixmap(entry):
    """Render one side of a texture change; None when it is not a BLP."""
    data = (entry or {}).get("data") or b""
    if data[:4] not in (b"BLP1", b"BLP2"):
        return None
    try:
        blp = open_blp(data)
        if blp.is_jpeg:
            image = QImage()
            if not image.loadFromData(blp.jpeg_bytes(0)):
                return None
        else:
            image = QImage.fromData(blp.png_bytes(0))
        if image.isNull():
            return None
        return QPixmap.fromImage(image.convertToFormat(QImage.Format_ARGB32))
    except Exception:                                    # noqa: BLE001
        return None


def _entry_text(entry):
    """Previewable text for one side of a row (None when absent)."""
    if not entry or entry.get("data") is None:
        return None
    return preview_text(entry.get("name") or "", entry["data"])
