# -*- coding: utf-8 -*-
"""Batch extraction as its own tab, with a per-map results table.

The old flow was: modal folder picker \u2192 wait \u2192 modal monospace text
dump that disappeared on Close.  Here the results stay in a tab you can
return to, sort and copy, and the run is a cancellable background job.
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .workers import BatchWorker

COLUMNS = ("#", "Map", "Status", "Recovered", "Failed", "Output", "Detail")


class BatchView(QWidget):
    """One batch run and its results, in a tab."""

    status = Signal(str)
    busy = Signal(bool)
    title_changed = Signal()

    def __init__(self, tasks, settings=None, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.settings = settings
        self._job = None
        self.results = []
        self._build_ui()

    @property
    def title(self):
        return "Batch extract"

    def summary(self):
        return "Batch extraction \u2014 %d map(s) processed" % len(self.results)

    @property
    def worker(self):
        job = self._job
        return job.worker if job is not None and job.active else None

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        heading = QLabel("<h2>Batch extract</h2>")
        layout.addWidget(heading)
        hint = QLabel("Extract every .w3x / .w3m / .mpq under a folder, "
                      "one output folder per map, with an index.csv.")
        theme.set_role(hint, "dim")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        for attr, label in (("src", "Folder containing maps"),
                            ("out", "Output folder")):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            edit = QLineEdit()
            edit.setPlaceholderText(label)
            setattr(self, attr + "_edit", edit)
            row.addWidget(edit, 1)
            btn = QPushButton("Browse\u2026")
            btn.clicked.connect(lambda _=False, e=edit: self._browse(e))
            row.addWidget(btn)
            layout.addLayout(row)

        actions = QHBoxLayout()
        self.run_btn = QPushButton("Run batch")
        theme.set_role(self.run_btn, "accent")
        self.run_btn.clicked.connect(self.run)
        actions.addWidget(self.run_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        actions.addWidget(self.cancel_btn)
        self.count_label = QLabel("")
        theme.set_role(self.count_label, "dim")
        actions.addWidget(self.count_label, 1)
        layout.addLayout(actions)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

    def _browse(self, edit):
        path = QFileDialog.getExistingDirectory(self, "Choose folder",
                                                edit.text())
        if path:
            edit.setText(path)

    def run(self):
        src, out = self.src_edit.text().strip(), self.out_edit.text().strip()
        if not src or not out:
            self.status.emit("Choose both a source and an output folder.")
            return
        if self.settings:
            self.settings.setValue("batch_dir", src)
            self.settings.setValue("batch_out", out)
        self.results = []
        self.table.setRowCount(0)
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.count_label.setText("Running\u2026")
        self.busy.emit(True)
        self._job = self.tasks.submit(
            "Batch \u2192 %s" % os.path.basename(out),
            BatchWorker(src, out), on_done=self._on_done,
            on_failed=self._on_failed, owner="batch")

    def cancel(self):
        if self._job is not None:
            self.tasks.cancel(self._job)

    def _on_done(self, results):
        self.results = results
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(results))
        t = theme.tokens()
        for i, r in enumerate(results):
            values = [str(r.get("n", i + 1)),
                      os.path.basename(r.get("source", "")),
                      r.get("status", "?"),
                      str(r.get("ok", 0)), str(r.get("failed", 0)),
                      r.get("outdir", ""), r.get("error") or ""]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 2:
                    colour = {"ok": t["success"], "partial": t["warn"],
                              "error": t["danger"]}.get(r.get("status"),
                                                        t["muted"])
                    item.setForeground(QColor(colour))
                self.table.setItem(i, col, item)
        self.table.setSortingEnabled(True)
        ok = sum(1 for r in results if r.get("status") == "ok")
        self.count_label.setText("%d map(s), %d clean" % (len(results), ok))
        self.status.emit("Batch finished: %d map(s)" % len(results))
        self._finish()

    def _on_failed(self, err):
        self.count_label.setText("Failed: %s" % err)
        self.status.emit("Batch failed: %s" % err)
        self._finish()

    def _finish(self):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.busy.emit(False)
        self.title_changed.emit()

    def set_default_folders(self, src=None, out=None):
        if src:
            self.src_edit.setText(src)
        if out:
            self.out_edit.setText(out)

    def on_theme_changed(self):
        theme.repolish(self.run_btn)
        theme.repolish(self.count_label)

    def shutdown(self):
        self.cancel()
