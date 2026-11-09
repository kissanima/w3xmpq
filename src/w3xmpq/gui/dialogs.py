# -*- coding: utf-8 -*-
"""Small dialogs and helpers kept apart from the window modules.

The redesigned UI no longer uses modal text dumps for Report/Safety and no
longer needs a two-field compare picker, but these widgets are still
useful from the CLI/embedding side and are kept for compatibility.
"""

import os

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from .workers import FnWorker                            # noqa: F401

ARCHIVE_FILTER = "WC3 maps & MPQ archives (*.w3x *.w3m *.mpq);;All files (*)"


class TextDialog(QDialog):
    """A read-only monospace report in a window."""

    def __init__(self, parent, title, text):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 520)
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(text)
        self.edit.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        self.edit.setFont(font)
        lay.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


def _row_with_browse(edit, on_browse):
    row = QHBoxLayout()
    row.addWidget(edit)
    btn = QPushButton("Browse…")
    btn.clicked.connect(lambda _=False: on_browse())
    row.addWidget(btn)
    w = QWidget()
    w.setLayout(row)
    return w


class DiffPickDialog(QDialog):
    """Pick the two archives to compare."""

    def __init__(self, parent, path_a=None):
        super().__init__(parent)
        self.setWindowTitle("Compare two archives")
        self.path_a = self.path_b = None
        form = QFormLayout(self)
        self.edit_a = QLineEdit(path_a or "")
        self.edit_b = QLineEdit()
        form.addRow("Archive A", _row_with_browse(
            self.edit_a, lambda: self._browse(self.edit_a)))
        form.addRow("Archive B", _row_with_browse(
            self.edit_b, lambda: self._browse(self.edit_b)))
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


class BatchDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Batch extract a folder")
        self.search_dir = self.outdir = None
        form = QFormLayout(self)
        self.edit_src = QLineEdit()
        self.edit_out = QLineEdit()
        form.addRow("Folder containing maps", _row_with_browse(
            self.edit_src, lambda: self._browse(self.edit_src)))
        form.addRow("Output folder", _row_with_browse(
            self.edit_out, lambda: self._browse(self.edit_out)))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok |
                                   QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self, edit):
        path = QFileDialog.getExistingDirectory(self, "Choose folder")
        if path:
            edit.setText(path)

    def _accept(self):
        self.search_dir = self.edit_src.text()
        self.outdir = self.edit_out.text()
        if self.search_dir and self.outdir:
            self.accept()


def render_batch(root, results):
    lines = ["Batch extract: %s — %d archives" % (root, len(results)), ""]
    for r in results:
        lines.append("  %-14s %s" % (r.get("status", "?"),
                                     r.get("path", "?")))
    lines.append("")
    lines.append("Index written: index.csv / index.json in the output folder.")
    return "\n".join(lines)


def open_folder(path):
    """Reveal `path` in the system file manager."""
    import subprocess
    import sys
    folder = os.path.dirname(os.path.abspath(path))
    if sys.platform.startswith("win"):
        os.startfile(folder)                            # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])
