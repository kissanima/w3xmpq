# -*- coding: utf-8 -*-
"""Left pane: the archive's folder hierarchy, 7-zip style."""

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class FolderTree(QTreeWidget):
    """Each item carries its full folder path; the root clears the filter."""

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
        self.blockSignals(True)
        self.clear()
        root_item = QTreeWidgetItem(["(all files)"])
        root_item.setData(0, Qt.UserRole, None)
        self.addTopLevelItem(root_item)
        nodes = {None: root_item}
        folders = set()
        for e in entries or []:
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
