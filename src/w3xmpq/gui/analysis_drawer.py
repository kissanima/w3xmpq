# -*- coding: utf-8 -*-
"""The collapsible details drawer: Report / Safety / Tasks.

The two most valuable analyses used to be modal, monospace text dumps that
vanished the moment you closed them.  Here they are structured sections
with severity icons, persisted in a bottom drawer (or a dedicated area you
can keep open while browsing), and their file references are clickable —
clicking one selects that file in the table.
"""

import html
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QScrollArea, QSizePolicy,
                               QTabWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import theme

SEVERITY_ROLE = {"high": "severity-high", "warning": "severity-warning",
                 "info": "severity-info", "error": "severity-high"}
SEVERITY_ICON = {"high": "\u26d4", "warning": "\u26a0", "info": "\u2139"}
_FILE_TOKEN = re.compile(
    r"(?<![\w<])(war3map[_A-Za-z0-9]*\.(?:j|w3[abdeqtu]|wtg|wct|wts|imp|doo|blp)"
    r"|Scripts\\war3map\.j|\([A-Za-z]+\))")


class _Section(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        theme.set_role(self, "strip")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(10, 7, 10, 7)
        self.box.setSpacing(4)
        self.title = QLabel("<b>%s</b>" % html.escape(title))
        self.box.addWidget(self.title)
        self._content = QVBoxLayout()
        self._content.setSpacing(3)
        self.box.addLayout(self._content)

    def add(self, widget):
        self._content.addWidget(widget)
        return widget

    def clear_content(self):
        while self._content.count():
            item = self._content.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()


def _rich(text):
    """Turn file names in a sentence into clickable anchors."""
    out, pos = [], 0
    for m in _FILE_TOKEN.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        token = m.group(0)
        out.append('<a href="%s" style="text-decoration:underline">%s</a>'
                   % (html.escape(token, quote=True), html.escape(token)))
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


class AnalysisDrawer(QFrame):
    """Collapsible bottom drawer with three tabs."""

    file_requested = Signal(str)
    visibility_changed = Signal(bool)

    def __init__(self, manager, owner=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.owner = owner
        self._report = None
        self._safety = None
        self._build_ui()
        manager.job_added.connect(lambda _j: self._sync_tasks())
        manager.job_changed.connect(lambda _j: self._sync_tasks())
        self.collapse()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        theme.set_role(self, "drawer")

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 3, 8, 3)
        bar.setSpacing(6)
        self.toggle = QPushButton("\u25b8 Details")
        self.toggle.setCheckable(True)
        self.toggle.setFlat(True)
        self.toggle.clicked.connect(self.set_expanded)
        bar.addWidget(self.toggle)
        self.hint = QLabel("")
        theme.set_role(self.hint, "dim")
        bar.addWidget(self.hint, 1)
        outer.addLayout(bar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.report_page = self._scroll_page()
        self.safety_page = self._scroll_page()
        self.tasks_page = QWidget()
        tasks_layout = QVBoxLayout(self.tasks_page)
        self.tasks_table = QTableWidget(0, 3)
        self.tasks_table.setHorizontalHeaderLabels(["Task", "State", "Detail"])
        self.tasks_table.verticalHeader().setVisible(False)
        self.tasks_table.setEditTriggers(QTableWidget.NoEditTriggers)
        head = self.tasks_table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        tasks_layout.addWidget(self.tasks_table)
        self.tabs.addTab(self.report_page, "Report")
        self.tabs.addTab(self.safety_page, "Safety")
        self.tabs.addTab(self.tasks_page, "Tasks")
        outer.addWidget(self.tabs)
        self.tabs.setMaximumHeight(230)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    @staticmethod
    def _scroll_page():
        # The QScrollArea *is* the tab page.  An intermediate unparented
        # QWidget would be collected as soon as this function returns and
        # would delete the scroll area with it ("C++ object already
        # deleted" on addTab).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(8, 6, 8, 6)
        inner_layout.setSpacing(7)
        inner_layout.addStretch(1)
        scroll.inner_layout = inner_layout
        return scroll

    # --------------------------------------------------------- expand
    def set_expanded(self, on):
        self.toggle.setChecked(bool(on))
        self.tabs.setVisible(bool(on))
        self.toggle.setText("\u25be Details" if on else "\u25b8 Details")
        self.visibility_changed.emit(bool(on))

    def collapse(self):
        self.set_expanded(False)

    def open_tab(self, index):
        self.set_expanded(True)
        self.tabs.setCurrentIndex(index)

    def open_report(self):
        self.open_tab(0)

    def open_safety(self):
        self.open_tab(1)

    def open_tasks(self):
        self.open_tab(2)

    @property
    def expanded(self):
        return self.toggle.isChecked()

    # ---------------------------------------------------------- report
    def set_report(self, rep):
        self._report = rep
        self._fill(self.report_page, self._report_sections(rep))

    @staticmethod
    def _clear(page):
        layout = page.inner_layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _fill(self, page, sections):
        self._clear(page)
        layout = page.inner_layout
        for title, rows in sections:
            sec = _Section(title)
            for icon, text, detail in rows:
                rich = text if "<a " in text else _rich(text)
                label = QLabel(("%s %s" % (icon, rich)).strip())
                label.setWordWrap(True)
                label.setTextFormat(Qt.RichText)
                label.linkActivated.connect(self.file_requested.emit)
                if detail:
                    theme.set_role(label, detail)
                sec.add(label)
            layout.addWidget(sec)
        layout.addStretch(1)

    def _report_sections(self, rep):
        if rep is None:
            return [("Deprotection report",
                     [("", "Report not generated yet.", None)])]
        rows = [("", "%s" % html.escape(rep.get("verdict", "")),
                 "severity-info")]
        rows.append(("", "%d files recovered, %d failed"
                     % (rep.get("files_ok", 0), rep.get("files_failed", 0)),
                     None))
        verdict = [("Verdict", rows)]
        findings = []
        for f in rep.get("findings") or []:
            sev = f.get("severity", "info")
            icon = SEVERITY_ICON.get(sev, "\u2022")
            findings.append((icon, "%s — %s" % (f.get("title", ""), sev),
                             SEVERITY_ROLE.get(sev)))
            findings.append(("", f.get("detail", ""), None))
        verdict.append(("Findings (%d)" % len(rep.get("findings") or []),
                        findings or [("", "No protection patterns found.",
                                      "severity-info")]))
        unknown = []
        for u in sorted(rep.get("unknown") or [],
                        key=lambda x: -x["size"])[:20]:
            link = '<a href="block:%d">%s</a>' % (u["block"],
                                                   html.escape(u["name"]))
            unknown.append(("", "%s \u00b7 %d bytes \u00b7 entropy %.2f "
                            "\u00b7 looks like %s"
                            % (link, u["size"], u["entropy"],
                               html.escape(u["sniffed"] or "unknown")), None))
        if unknown:
            verdict.append(("Unnamed blocks", unknown))
        return verdict

    # ---------------------------------------------------------- safety
    def set_safety(self, res, running=False):
        self._safety = res
        if running:
            self._fill(self.safety_page,
                       [("Map safety scan",
                         [("", "Scanning the recovered script\u2026", None)])])
            return
        if res is None:
            self._fill(self.safety_page,
                       [("Map safety scan",
                         [("", "Safety scan not run yet.", None)])])
            return
        if res.get("note"):
            self._fill(self.safety_page,
                       [("Map safety scan", [("", res["note"], None)])])
            return
        rows = [("", "Script: %s (%d bytes)"
                 % (html.escape(res.get("script") or "?"),
                    res.get("size", 0)), None),
                ("", "Findings are for review; they are not a verdict.",
                 "severity-info")]
        sections = [("Map safety scan", rows)]
        found = []
        for f in res.get("findings") or []:
            sev = f.get("severity", "info")
            found.append((SEVERITY_ICON.get(sev, "\u2022"),
                          "%s — %d hit(s) (%s)"
                          % (f.get("label", ""), f.get("count", 0), sev),
                          SEVERITY_ROLE.get(sev)))
            found.append(("", f.get("explanation", ""), None))
        sections.append(("Findings", found or
                         [("\u2713", "No suspicious patterns found.",
                           "severity-info")]))
        stats = [(k, v) for k, v in sorted((res.get("stats") or {}).items(),
                                           key=lambda kv: -kv[1]) if v]
        sections.append(("Script statistics",
                         [("", "%s: %d" % (k, v), None)
                          for k, v in stats] or
                         [("", "No tracked natives found.", None)]))
        self._fill(self.safety_page, sections)

    # ----------------------------------------------------------- tasks
    def _sync_tasks(self):
        jobs = (self.manager.jobs_for(self.owner) if self.owner is not None
                else self.manager.jobs)
        self.tasks_table.setRowCount(len(jobs))
        t = theme.tokens()
        for i, job in enumerate(jobs):
            cells = [job.label, job.state, job.message]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 1:
                    colour = {"running": t["accent"], "done": t["success"],
                              "failed": t["danger"],
                              "cancelled": t["warn"]}.get(job.state,
                                                          t["muted"])
                    item.setForeground(QColor(colour))
                self.tasks_table.setItem(i, col, item)
        self.hint.setText("%d task(s), %d running"
                          % (len(jobs), len(self.manager.active_jobs())))

    def apply_theme(self):
        theme.repolish(self)
        theme.repolish(self.toggle)
        theme.repolish(self.hint)
        self._sync_tasks()
        self._fill(self.report_page, self._report_sections(self._report))
        self.set_safety(self._safety)
