# -*- coding: utf-8 -*-
"""The archive's summary strip — the headline, not a one-line banner.

The old UI buried "X/Y blocks recovered" in a dot-separated label and put
seven equal-weight text buttons in a toolbar.  This widget makes the
*verdict* the largest thing on screen, shows it as a progress bar, and
gives the three outcomes a user actually came for their own buttons:

    [Rebuild for WorldEdit]  [Extract all ▾]  [Safety: 2 warnings] [Report]

Rebuild is the accent action; safety is a badge that opens the analysis
drawer (and is filled automatically after the scan).
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu,
                               QProgressBar, QPushButton, QSizePolicy,
                               QToolButton, QVBoxLayout)

from ..core import filetypes
from ..core.w3x_header import is_w3x, parse_header
from . import theme


class SummaryStrip(QFrame):
    """Map metadata + recovery verdict + primary actions."""

    rebuild_clicked = Signal()
    extract_all_clicked = Signal()
    extract_selected_clicked = Signal()
    export_clicked = Signal()
    safety_clicked = Signal()
    report_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        theme.set_role(self, "strip")
        self._entries = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(7)

        self.meta = QLabel("")
        theme.set_role(self.meta, "dim")
        self.meta.setWordWrap(True)
        layout.addWidget(self.meta)

        verdict_row = QHBoxLayout()
        verdict_row.setSpacing(10)
        self.headline = QLabel("Opening archive…")
        theme.set_role(self.headline, "headline")
        font = self.headline.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        self.headline.setFont(font)
        self.detail = QLabel("")
        theme.set_role(self.detail, "dim")
        self.progress = QProgressBar()
        self.progress.setProperty("w3role", "recovery")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(210)
        self.progress.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        verdict_row.addWidget(self.headline, 1)
        verdict_row.addWidget(self.detail)
        verdict_row.addWidget(self.progress)
        layout.addLayout(verdict_row)

        actions = QHBoxLayout()
        actions.setSpacing(7)
        self.rebuild_btn = QPushButton("Rebuild for WorldEdit")
        theme.set_role(self.rebuild_btn, "accent")
        self.rebuild_btn.setToolTip(
            "Write a clean, World-Edit-openable copy of this map. "
            "The original is never modified.")
        self.rebuild_btn.clicked.connect(self.rebuild_clicked.emit)
        actions.addWidget(self.rebuild_btn)

        self.extract_btn = QToolButton()
        self.extract_btn.setText("Extract all")
        self.extract_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.extract_btn.setPopupMode(QToolButton.MenuButtonPopup)
        theme.set_role(self.extract_btn, "ghost")
        menu = QMenu(self.extract_btn)
        menu.addAction("Extract everything…", self.extract_all_clicked.emit)
        menu.addAction("Extract selected…", self.extract_selected_clicked.emit)
        menu.addSeparator()
        menu.addAction("Export file table…", self.export_clicked.emit)
        self.extract_btn.setMenu(menu)
        self.extract_btn.clicked.connect(self.extract_all_clicked.emit)
        actions.addWidget(self.extract_btn)

        self.safety_btn = QPushButton("Safety: scanning…")
        theme.set_role(self.safety_btn, "badge")
        self.safety_btn.setToolTip("Open the safety scan in the details drawer")
        self.safety_btn.clicked.connect(self.safety_clicked.emit)
        actions.addWidget(self.safety_btn)

        self.report_btn = QPushButton("Report")
        theme.set_role(self.report_btn, "ghost")
        self.report_btn.setToolTip(
            "Open the deprotection report in the details drawer")
        self.report_btn.clicked.connect(self.report_clicked.emit)
        actions.addWidget(self.report_btn)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    # ------------------------------------------------------------ data
    def set_scanning(self, path):
        self.meta.setText(os.path.basename(path or ""))
        self.headline.setText("Scanning archive…")
        self.detail.setText("")
        self.progress.setRange(0, 0)
        self.safety_btn.setText("Safety: pending")
        self._entries = None

    def set_metadata(self, path):
        """Show the map's own name/author/tileset/size when it has a header."""
        name = os.path.basename(path or "")
        if path and is_w3x(path):
            try:
                h = parse_header(path)
                bits = []
                title = h.get("name") or name
                bits.append("<b>%s</b>" % _esc(title))
                if h.get("author"):
                    bits.append("by %s" % _esc(h["author"]))
                bits.append("%s tileset" % _esc(h.get("tileset_name", "?")))
                bits.append("%d\u00d7%d tiles" % (h.get("width", 0),
                                                  h.get("height", 0)))
                self.meta.setText("\u00b7 ".join(bits))
                return
            except Exception:                            # noqa: BLE001
                pass
        self.meta.setText("<b>%s</b>" % _esc(name))

    def set_entries(self, entries):
        """The headline: recovered / total, failures and unnamed counts."""
        self._entries = entries or []
        total = len(self._entries)
        ok = sum(1 for e in self._entries if not filetypes.is_failed(e))
        failed = total - ok
        unnamed = sum(1 for e in self._entries if not filetypes.is_named(e))
        pct = (100 * ok // total) if total else 0
        self.headline.setText("%d / %d blocks recovered" % (ok, total))
        parts = ["%d%%" % pct]
        if failed:
            parts.append("%d failed" % failed)
        if unnamed:
            parts.append("%d unnamed" % unnamed)
        self.detail.setText("\u00b7 ".join(parts))
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(ok)
        state = "ok" if not failed else ("warn" if ok else "bad")
        self.progress.setProperty("w3state", state)
        theme.repolish(self.progress)
        self.progress.setToolTip("%d of %d blocks decrypted" % (ok, total))

    def set_safety(self, result=None, running=False):
        if running:
            self.safety_btn.setText("Safety: scanning…")
            return
        if result is None:
            self.safety_btn.setText("Safety: not run")
            return
        findings = result.get("findings") or []
        warnings = sum(1 for f in findings
                       if f.get("severity") in ("warning", "high"))
        if warnings:
            self.safety_btn.setText("Safety: %d warning%s"
                                    % (warnings, "s" if warnings != 1 else ""))
            self.safety_btn.setToolTip("Open the safety scan for details")
        else:
            self.safety_btn.setText("Safety: clean")
            self.safety_btn.setToolTip("No suspicious patterns found")

    def set_report_available(self, available=True):
        self.report_btn.setEnabled(bool(available))

    def apply_theme(self):
        for w in (self, self.meta, self.headline, self.detail,
                  self.rebuild_btn, self.extract_btn, self.safety_btn,
                  self.report_btn, self.progress):
            theme.repolish(w)


def _esc(text):
    import html
    return html.escape(str(text))
