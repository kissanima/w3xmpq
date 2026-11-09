# -*- coding: utf-8 -*-
"""The file table's model, sort/filter proxy and view.

Phase 1 of the UI rebuild replaced the old ``QTableWidget`` (which looped
every row calling ``setRowHidden`` on each keystroke) with one source of
truth:

    FileTableModel   rows = scanned entry dicts, never rebuilt for a filter
    FileFilterProxy  folder + text + chip filtering, and all sorting
    FileTable        QTableView with multi-select, hidden "Advanced" columns
                     and a right-click header menu

Because filtered rows simply do not exist in the proxy, the chip counts
come from the *model*, not from a walk over hidden rows — that is what
makes filtering a large map O(rows) once instead of O(rows) per keystroke
plus N hide/show calls.
"""

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, Qt, Signal,
                            QSortFilterProxyModel)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHeaderView, QMenu, QTableView,
                               QAbstractItemView)

from ..core import filetypes
from . import theme

SORT_ROLE = Qt.UserRole + 1
ENTRY_ROLE = Qt.UserRole + 2

#: (header, key).  The first four are the everyday view; the rest are the
#: expert columns, hidden by default and reachable from the header menu.
COLUMNS = (("Name", "name"), ("Type", "type"), ("Size", "size"),
           ("Status", "status"), ("Block", "block"), ("Packed", "packed"),
           ("Flags", "flags"), ("Src", "src"))
BASIC = (0, 1, 2, 3)
ADVANCED = (4, 5, 6, 7)
COL_NAME, COL_TYPE, COL_SIZE, COL_STATUS = BASIC

FLAGS_SHORT = ((0x80000000, "E", "exists"),
               (0x00000200, "Z", "compressed"),
               (0x00010000, "K", "encrypted / name-derived key"),
               (0x01000000, "S", "single sector"),
               (0x04000000, "C", "deleted / CRC"),
               (0x00040000, "P", "patch file"))

#: The chips in display order; ``all`` is always first.
CHIPS = (("all", "All"), ("script", "Scripts"), ("texture", "Textures"),
         ("model", "Models"), ("sound", "Sounds"), ("unnamed", "Unnamed"),
         ("failed", "Failed"), ("encrypted", "Encrypted"))


def invalidate_rows(proxy):
    """Re-run filterAcceptsRow on every source row.

    PySide6 6.12 marks ``invalidateFilter()`` *and* its advertised
    replacements ``invalidateRowsFilter()`` / ``invalidateColumnsFilter()``
    as deprecated.  ``invalidate()`` is the remaining non-deprecated call
    and has existed since Qt 4.
    """
    proxy.invalidate()


def flags_str(flags):
    return "".join(c for bit, c, _desc in FLAGS_SHORT if flags & bit) or "-"


def flags_tooltip(flags):
    return "\n".join("%s  %s" % (c, desc) for bit, c, desc in FLAGS_SHORT
                     if flags & bit) or "no known flags set"


def _cell(entry, key):
    if key == "name":
        return filetypes.display_name(entry)
    if key == "type":
        return filetypes.detect(entry.get("name"),
                                entry.get("data") or b"").label
    if key == "size":
        return "{:,}".format(entry.get("size", 0))
    if key == "status":
        return "\u25cf %s" % ("ok" if not filetypes.is_failed(entry)
                              else entry.get("status", "FAILED"))
    if key == "block":
        return str(entry.get("block", ""))
    if key == "packed":
        return "{:,}".format(entry.get("archived_size", 0))
    if key == "flags":
        return flags_str(entry.get("flags", 0))
    if key == "src":
        return "%s/%s" % (entry.get("name_source") or "unknown",
                          entry.get("key_method") or "plain")
    return ""


def _sort_key(entry, key):
    if key == "name":
        return filetypes.display_name(entry).lower()
    if key == "type":
        return _cell(entry, "type").lower()
    if key == "size":
        return entry.get("size", 0)
    if key == "packed":
        return entry.get("archived_size", 0)
    if key == "block":
        return entry.get("block", 0)
    if key == "status":
        return 0 if filetypes.is_failed(entry) else 1
    return _cell(entry, key).lower()


class FileTableModel(QAbstractTableModel):
    """One row per scanned MPQ block."""

    def __init__(self, entries=None, parent=None):
        super().__init__(parent)
        self.entries = list(entries or [])

    def set_entries(self, entries):
        self.beginResetModel()
        self.entries = list(entries or [])
        self.endResetModel()

    def entry(self, row):
        if 0 <= row < len(self.entries):
            return self.entries[row]
        return None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal or role != Qt.DisplayRole:
            return None
        if 0 <= section < len(COLUMNS):
            return COLUMNS[section][0]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        e = self.entry(index.row())
        if e is None:
            return None
        key = COLUMNS[index.column()][1]
        if role == ENTRY_ROLE:
            return e
        if role == SORT_ROLE:
            return _sort_key(e, key)
        if role == Qt.DisplayRole:
            return _cell(e, key)
        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) \
                if key in ("size", "packed", "block", "flags") \
                else Qt.AlignVCenter
        if role == Qt.ToolTipRole:
            if key == "flags":
                return flags_tooltip(e.get("flags", 0))
            if key == "name":
                return e.get("name") or \
                    "name not recovered — will be extracted as %s" % \
                    filetypes.entry_name(e)
            if key == "type":
                k = filetypes.detect(e.get("name"), e.get("data") or b"")
                return "detected from magic bytes (%s)" % k.ext
            if key == "status":
                return "recovered" if not filetypes.is_failed(e) else \
                    "block could not be decrypted"
            return None
        if role == Qt.ForegroundRole:
            t = theme.tokens()
            if filetypes.is_failed(e):
                return QColor(t["danger"])
            if key == "name" and not filetypes.is_named(e):
                return QColor(t["muted"])
            if key == "status":
                return QColor(t["success"])
            return QColor(t["text"])
        return None

    def refresh_colors(self):
        if self.entries:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(self.rowCount() - 1,
                                             self.columnCount() - 1))


_UNSET = object()


class FileFilterProxy(QSortFilterProxyModel):
    """Folder, live text and chip filtering over `FileTableModel`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.folder = None
        self.category = "all"
        self.setSortRole(SORT_ROLE)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setDynamicSortFilter(True)

    def configure(self, text=_UNSET, folder=_UNSET, category=_UNSET):
        if text is not _UNSET:
            self.text = (text or "").strip().lower()
        if folder is not _UNSET:
            self.folder = folder
        if category is not _UNSET:
            self.category = category
        invalidate_rows(self)

    def set_folder(self, folder):
        self.folder = folder
        invalidate_rows(self)

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        e = model.entry(source_row) if model is not None else None
        if e is None:
            return False
        name = e.get("name") or ""
        if self.folder is not None:
            if not name.replace("/", "\\").startswith(self.folder + "\\"):
                return False
        if self.text:
            if self.text not in name.lower() and \
                    self.text not in filetypes.display_name(e).lower():
                return False
        cat = self.category
        if cat == "unnamed":
            return not filetypes.is_named(e)
        if cat == "failed":
            return filetypes.is_failed(e)
        if cat == "encrypted":
            return filetypes.is_encrypted(e)
        if cat != "all" and filetypes.category(e) != cat:
            return False
        return True

    def lessThan(self, left, right):
        a = self.sourceModel().data(left, SORT_ROLE)
        b = self.sourceModel().data(right, SORT_ROLE)
        if isinstance(a, str) and isinstance(b, str):
            return a.lower() < b.lower()
        try:
            return (a if a is not None else 0) < (b if b is not None else 0)
        except TypeError:
            return str(a) < str(b)


class FileTable(QTableView):
    """The archive's file list."""

    advanced_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = FileTableModel(parent=self)
        self.proxy = FileFilterProxy(self)
        self.proxy.setSourceModel(self.model_)
        self.setModel(self.proxy)
        self._advanced = False
        self._setup()

    def _setup(self):
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setWordWrap(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col in ADVANCED + (COL_TYPE, COL_SIZE, COL_STATUS):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)
        self._apply_column_visibility()
        self.sortByColumn(COL_SIZE, Qt.DescendingOrder)

    def _apply_column_visibility(self):
        for col in ADVANCED:
            self.setColumnHidden(col, not self._advanced)

    def set_advanced(self, on):
        self._advanced = bool(on)
        self._apply_column_visibility()
        self.advanced_toggled.emit(self._advanced)

    @property
    def advanced(self):
        return self._advanced

    def _header_menu(self, pos):
        menu = QMenu(self)
        act = menu.addAction("Advanced columns")
        act.setCheckable(True)
        act.setChecked(self._advanced)
        act.triggered.connect(self.set_advanced)
        menu.addSeparator()
        for col, (label, _key) in enumerate(COLUMNS):
            if col == COL_NAME:
                continue
            a = menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(not self.isColumnHidden(col))
            a.triggered.connect(
                lambda _=False, c=col: self.setColumnHidden(
                    c, not self.isColumnHidden(c)))
        menu.exec(self.horizontalHeader().viewport().mapToGlobal(pos))

    # ---------------------------------------------------------- rows
    def load_entries(self, entries):
        self.model_.set_entries(entries)
        invalidate_rows(self.proxy)

    def row_count(self):
        return self.proxy.rowCount()

    def rowCount(self):                     # convenience for callers/tests
        return self.proxy.rowCount()

    def source_count(self):
        return self.model_.rowCount()

    def entry_at(self, visual_row):
        index = self.proxy.index(visual_row, 0)
        if not index.isValid():
            return None
        src = self.proxy.mapToSource(index)
        return self.model_.entry(src.row())

    def entries_shown(self):
        return [self.entry_at(r) for r in range(self.row_count())]

    def selected_entries(self):
        out = []
        for index in self.selectionModel().selectedRows(0):
            src = self.proxy.mapToSource(index)
            e = self.model_.entry(src.row())
            if e is not None:
                out.append(e)
        return out

    def current_entry(self):
        return self.entry_at(self.currentIndex().row())

    def select_entry(self, entry):
        """Select the visual row holding `entry` (by identity)."""
        for r in range(self.row_count()):
            if self.entry_at(r) is entry:
                self.selectRow(r)
                return True
        return False

    def select_first_ok(self):
        for r in range(self.row_count()):
            e = self.entry_at(r)
            if e is not None and not filetypes.is_failed(e):
                self.selectRow(r)
                return True
        return False

    def is_row_visible(self, row):
        return 0 <= row < self.row_count()

    # ------------------------------------------------------- filtering
    def set_folder(self, folder):
        self.proxy.set_folder(folder)

    def set_filter(self, text=_UNSET, folder=_UNSET, category=_UNSET):
        self.proxy.configure(text=text, folder=folder, category=category)

    def counts(self):
        """Chip counts from the model — independent of the active filter."""
        result = {"all": self.model_.rowCount()}
        for key, _label in CHIPS[1:]:
            result[key] = 0
        for e in self.model_.entries:
            if not filetypes.is_named(e):
                result["unnamed"] += 1
            if filetypes.is_failed(e):
                result["failed"] += 1
            if filetypes.is_encrypted(e):
                result["encrypted"] += 1
            cat = filetypes.category(e)
            if cat in result:
                result[cat] += 1
        return result

    # ------------------------------------------------------------ theme
    def apply_theme(self):
        self.model_.refresh_colors()

    def reload_keeping_selection(self):
        """Re-read colours without dropping the selected entry."""
        entry = self.current_entry()
        self.model_.refresh_colors()
        if entry is not None:
            self.select_entry(entry)
