# -*- coding: utf-8 -*-
"""Filter chips with live counts.

Replaces the old "show" combo box.  A chip is an exclusive, checkable
button whose label carries the count for that family; counts come from
:meth:`~w3xmpq.gui.file_model.FileTable.counts`, i.e. the model, so they do
not change when a filter is applied (you can still see that a map has 97
unnamed blocks while looking only at its textures).
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton

from . import theme
from .file_model import CHIPS


class FilterChips(QFrame):
    """A row of exclusive chips.  Emits the selected key."""

    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(5)
        for key, label in CHIPS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("w3role", "chip")
            theme.set_role(btn, "chip")
            self.group.addButton(btn)
            self.buttons[key] = btn
            layout.addWidget(btn)
        layout.addStretch(1)
        self.buttons["all"].setChecked(True)
        self.group.idClicked.connect(self._on_clicked)

    def _on_clicked(self, _id):
        self.changed.emit(self.current())

    def current(self):
        for key, btn in self.buttons.items():
            if btn.isChecked():
                return key
        return "all"

    def set_current(self, key):
        btn = self.buttons.get(key) or self.buttons["all"]
        btn.setChecked(True)
        self.changed.emit(self.current())

    def set_counts(self, counts):
        for key, label in CHIPS:
            self.buttons[key].setText("%s %d" % (label, counts.get(key, 0)))

    def apply_theme(self):
        for btn in self.buttons.values():
            theme.repolish(btn)
