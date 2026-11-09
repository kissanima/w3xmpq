# -*- coding: utf-8 -*-
"""The empty state: a big drop zone, recent maps and the keyboard map."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .. import __version__
from . import theme

KEYBOARD = [
    ("Ctrl+O", "open a map"), ("Ctrl+W", "close tab"),
    ("Ctrl+F", "filter files"), ("Ctrl+Shift+F", "find in file"),
    ("Ctrl+E", "extract all"), ("Ctrl+Shift+E", "extract selected"),
    ("Ctrl+R", "rebuild"), ("Ctrl+D", "compare"),
    ("Ctrl+B", "batch"), ("Ctrl+1\u20269", "switch tab"),
]


class WelcomePage(QWidget):
    """What you see before any archive is open."""

    open_requested = Signal()
    recent_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        zone = QFrame()
        theme.set_role(zone, "drop")
        zone.setMinimumWidth(420)
        zbox = QVBoxLayout(zone)
        zbox.setAlignment(Qt.AlignCenter)
        zbox.setSpacing(10)
        title = QLabel("<h1>w3xmpq %s</h1>" % __version__)
        title.setAlignment(Qt.AlignCenter)
        big = QLabel("<h2>Drop a map here</h2>")
        big.setAlignment(Qt.AlignCenter)
        sub = QLabel("Read-only inspector for protected Warcraft III maps."
                     "<br>.w3x \u00b7 .w3m \u00b7 .mpq")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        theme.set_role(sub, "dim")
        self.open_btn = QPushButton("Open an archive\u2026")
        theme.set_role(self.open_btn, "accent")
        self.open_btn.setMaximumWidth(220)
        self.open_btn.clicked.connect(self.open_requested.emit)
        zbox.addStretch(1)
        zbox.addWidget(title)
        zbox.addWidget(big)
        zbox.addWidget(sub)
        zbox.addSpacing(8)
        zbox.addWidget(self.open_btn, 0, Qt.AlignHCenter)
        zbox.addStretch(1)
        root.addWidget(zone, 3)
        self.drop_zone = zone

        side = QFrame()
        theme.set_role(side, "strip")
        sbox = QVBoxLayout(side)
        sbox.setContentsMargins(14, 12, 14, 12)
        sbox.setSpacing(8)
        sbox.addWidget(QLabel("<b>Recent maps</b>"))
        self.recent = QListWidget()
        self.recent.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.recent.itemActivated.connect(
            lambda item: self.recent_selected.emit(item.data(Qt.UserRole)))
        self.recent.itemClicked.connect(
            lambda item: self.recent_selected.emit(item.data(Qt.UserRole)))
        sbox.addWidget(self.recent, 2)
        sbox.addWidget(QLabel("<b>Keyboard</b>"))
        for keys, what in KEYBOARD:
            row = QLabel("%s \u2014 %s" % (keys, what))
            theme.set_role(row, "dim")
            sbox.addWidget(row)
        sbox.addStretch(1)
        root.addWidget(side, 1)

    def set_recent(self, paths):
        self.recent.clear()
        # QListWidget.addItem() returns None in PySide6; always take the
        # item back from the widget by index.
        for path in paths or []:
            self.recent.addItem(os.path.basename(path))
            item = self.recent.item(self.recent.count() - 1)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
        if not self.recent.count():
            self.recent.addItem("(no recent maps)")
            item = self.recent.item(self.recent.count() - 1)
            item.setFlags(Qt.NoItemFlags)

    def set_hot(self, on):
        self.drop_zone.setProperty("w3hot", "true" if on else "false")
        theme.repolish(self.drop_zone)

    def apply_theme(self):
        for w in (self.drop_zone, self.open_btn):
            theme.repolish(w)
