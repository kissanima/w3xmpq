# -*- coding: utf-8 -*-
"""w3xmpq GUI — main window.

The window is a *host*: every open archive is a tab holding one
:class:`~w3xmpq.gui.archive_view.ArchiveView`, and a comparison is a tab
holding a :class:`~w3xmpq.gui.diff_view.DiffView`. All per-archive state
lives in those widgets, so tabs are fully independent — you can keep
three maps and a diff open at once and switch between them.

Layout::

    ┌ menu / toolbar ────────────────────────────────┐
    ├ tabs ──────────────────────────────────────────┤
    │  banner (map name / author / tileset / verdict) │
    │  filter row                                     │
    │  folder tree │ file table │ preview             │
    └ status bar ─────────────────────────────────────┘

Everything heavy runs on QThread workers (workers.py); this module only
wires results into widgets.
"""

import os
import sys

from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QLabel, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from . import theme
from .archive_view import ARCHIVE_FILTER, ArchiveView
from .dialogs import (BatchDialog, DiffPickDialog, TextDialog,
                      render_batch)
from .diff_view import DiffView
from .workers import BatchWorker

#: Tab labels longer than this are elided; the tooltip keeps the path.
MAX_TITLE = 34

ARCHIVE_EXT = (".w3x", ".w3m", ".mpq")


def _elide(text, limit=MAX_TITLE):
    text = text or ""
    return text if len(text) <= limit else text[:limit - 1] + "…"


class DropArea(QStackedWidget):
    """Central stack that accepts archives dropped anywhere on it."""

    files_dropped = Signal(list)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("w3xmpq", "w3xmpq")
        self._task = None               # window-level worker (batch)
        self._dark = theme.theme_from_settings(self.settings) == theme.DARK
        theme.apply_theme(QApplication.instance(), self._dark)
        self._show_filter = self.settings.value("show_filter", 0, type=int)
        self._splitter_state = self.settings.value("splitter")
        self._build_ui()
        self._restore_session()
        self._update_empty_state()
        self._update_actions()

    # ------------------------------------------------------------ session
    def _restore_session(self):
        geom = self.settings.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)

    def _save_session(self):
        self.settings.setValue("geometry", self.saveGeometry())
        view = self.view()
        if view is not None:
            self.settings.setValue("splitter", view.splitter.saveState())
            self.settings.setValue(
                "show_filter", view.show_combo.currentIndex())
        self.settings.setValue(
            "theme", theme.DARK if self._dark else theme.LIGHT)

    def closeEvent(self, event):
        self._save_session()
        for w in self._all_views():
            if hasattr(w, "shutdown"):
                w.shutdown()
        if self._task is not None and self._task.isRunning():
            self._task.wait(3000)
        super().closeEvent(event)

    # ------------------------------------------------------------ tabs
    def view(self):
        """The archive in the current tab, or None (diff tab / empty)."""
        w = self.tabs.currentWidget() if self.tabs.count() else None
        return w if isinstance(w, ArchiveView) else None

    def _all_views(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def _update_empty_state(self):
        self.stack.setCurrentIndex(1 if self.tabs.count() else 0)

    def _on_view_status(self, widget, message):
        """Status messages only apply to the tab you are looking at."""
        if widget is self.tabs.currentWidget():
            self.statusBar().showMessage(message)

    def _on_view_busy(self, widget, _busy):
        self._update_actions()

    def _on_open_failed(self, widget, err):
        self._refresh_tab(widget)
        QMessageBox.critical(self, "Could not open archive", err)

    def _refresh_tab(self, widget):
        index = self.tabs.indexOf(widget)
        if index < 0:
            return
        self.tabs.setTabText(index, _elide(widget.title))
        self.tabs.setTabToolTip(index, widget.summary())

    def _close_tab(self, index):
        widget = self.tabs.widget(index)
        if widget is None:
            return
        if hasattr(widget, "shutdown"):
            widget.shutdown()
        self.tabs.removeTab(index)
        widget.deleteLater()
        self._update_empty_state()
        self._update_actions()

    def _close_current_tab(self):
        if self.tabs.count():
            self._close_tab(self.tabs.currentIndex())

    def _cycle_tab(self, step):
        count = self.tabs.count()
        if count > 1:
            self.tabs.setCurrentIndex(
                (self.tabs.currentIndex() + step) % count)

    def eventFilter(self, obj, event):
        # Middle-click closes a tab, like a browser.
        if obj is self.tabs.tabBar() \
                and event.type() == QEvent.MouseButtonRelease \
                and event.button() == Qt.MiddleButton:
            index = self.tabs.tabBar().tabAt(event.position().toPoint())
            if index >= 0:
                self._close_tab(index)
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------ UI setup
    def _build_ui(self):
        self.setWindowTitle("w3xmpq " + __version__)
        self.resize(1180, 760)
        self.setAcceptDrops(True)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(lambda _i: self._update_actions())
        self.tabs.tabBar().installEventFilter(self)

        welcome = QWidget()
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.addStretch(1)
        title = QLabel("<h2>w3xmpq %s</h2>" % __version__)
        title.setAlignment(Qt.AlignCenter)
        hint = QLabel(
            "Open a .w3x / .w3m / .mpq file (Ctrl+O) or drop it here.<br>"
            "Each archive opens in its own tab — browse it like a zip: "
            "click a file to preview, double-click to focus the preview, "
            "right-click to extract.")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        open_btn = QPushButton("Open an archive…")
        open_btn.setMaximumWidth(200)
        open_btn.clicked.connect(self._open_dialog)
        welcome_layout.addWidget(title)
        welcome_layout.addWidget(hint)
        welcome_layout.addSpacing(12)
        welcome_layout.addWidget(open_btn, 0, Qt.AlignHCenter)
        welcome_layout.addStretch(2)

        self.stack = DropArea()
        self.stack.addWidget(welcome)      # 0 — empty state
        self.stack.addWidget(self.tabs)    # 1 — open archives
        self.stack.files_dropped.connect(self._open_many)
        self.setCentralWidget(self.stack)

        self.statusBar().showMessage("Ready")

        # ---- actions
        open_act = QAction("&Open…", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self._open_dialog)
        close_act = QAction("&Close tab", self)
        close_act.setShortcut("Ctrl+W")
        close_act.triggered.connect(self._close_current_tab)
        extract_act = QAction("&Extract…", self)
        extract_act.setShortcut("Ctrl+E")
        extract_act.triggered.connect(lambda: self._call("extract"))
        extract_sel_act = QAction("Extract &selected…", self)
        extract_sel_act.setShortcut("Ctrl+Shift+E")
        extract_sel_act.triggered.connect(
            lambda: self._call("extract_selected"))
        save_prev_act = QAction("Save pre&view as…", self)
        save_prev_act.setShortcut("Ctrl+S")
        save_prev_act.triggered.connect(lambda: self._call("save_preview"))
        export_act = QAction("&Export file table…", self)
        export_act.triggered.connect(lambda: self._call("export_table"))
        folder_act = QAction("Open containing &folder", self)
        folder_act.triggered.connect(
            lambda: self._call("open_containing_folder"))
        quit_act = QAction("E&xit", self)
        quit_act.triggered.connect(self.close)

        report_act = QAction("&Deprotection report", self)
        report_act.triggered.connect(lambda: self._call("report"))
        scan_act = QAction("&Safety scan", self)
        scan_act.triggered.connect(lambda: self._call("safety_scan"))
        rebuild_act = QAction("&Rebuild (WorldEdit-ready)…", self)
        rebuild_act.triggered.connect(lambda: self._call("rebuild"))
        compare_act = QAction("Compare current with…", self)
        compare_act.triggered.connect(self._compare_current)
        diff_act = QAction("&Compare two archives…", self)
        diff_act.triggered.connect(self._diff)
        batch_act = QAction("&Batch extract folder…", self)
        batch_act.triggered.connect(self._batch)

        next_tab_act = QAction("Next tab", self)
        next_tab_act.setShortcut("Ctrl+Tab")
        next_tab_act.triggered.connect(lambda: self._cycle_tab(1))
        prev_tab_act = QAction("Previous tab", self)
        prev_tab_act.setShortcut("Ctrl+Shift+Tab")
        prev_tab_act.triggered.connect(lambda: self._cycle_tab(-1))
        self.dark_act = QAction("&Dark theme", self)
        self.dark_act.setCheckable(True)
        self.dark_act.setChecked(self._dark)
        self.dark_act.setShortcut("Ctrl+Shift+D")
        self.dark_act.toggled.connect(self._set_dark)

        about_act = QAction("&About", self)
        about_act.triggered.connect(self._about)

        menu_file = self.menuBar().addMenu("&File")
        menu_file.addAction(open_act)
        self.recent_menu = menu_file.addMenu("Open &recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        menu_file.addAction(close_act)
        menu_file.addSeparator()
        menu_file.addAction(extract_act)
        menu_file.addAction(extract_sel_act)
        menu_file.addAction(save_prev_act)
        menu_file.addAction(export_act)
        menu_file.addAction(folder_act)
        menu_file.addSeparator()
        menu_file.addAction(quit_act)

        menu_tools = self.menuBar().addMenu("&Tools")
        for a in (report_act, scan_act, rebuild_act, None,
                  compare_act, diff_act, None, batch_act):
            if a is None:
                menu_tools.addSeparator()
            else:
                menu_tools.addAction(a)

        menu_view = self.menuBar().addMenu("&View")
        menu_view.addAction(self.dark_act)
        menu_view.addSeparator()
        menu_view.addAction(next_tab_act)
        menu_view.addAction(prev_tab_act)

        menu_help = self.menuBar().addMenu("&Help")
        menu_help.addAction(about_act)

        tb = self.addToolBar("main")
        tb.setMovable(False)
        self._actions = []
        for a in (open_act, extract_act, extract_sel_act, report_act,
                  scan_act, rebuild_act, compare_act):
            tb.addAction(a)
            self._actions.append(a)

        # Actions that need an archive, and the subset that needs a
        # finished scan. Keep the tab-management ones always available.
        self._need_view = [extract_act, extract_sel_act, report_act,
                           scan_act, rebuild_act, compare_act]
        self._need_entries = [save_prev_act, export_act, folder_act]
        self._need_tab = [close_act]

    def _call(self, method):
        """Run a method of the current archive pane."""
        view = self.view()
        if view is not None:
            getattr(view, method)()

    def _update_actions(self):
        view = self.view()
        busy = (view is not None and view.worker is not None) or \
            (self._task is not None)
        has_view = view is not None and not busy
        has_entries = has_view and bool(view.current_entries)
        for a in self._need_view:
            a.setEnabled(has_view)
        for a in self._need_entries:
            a.setEnabled(has_entries)
        for a in self._need_tab:
            a.setEnabled(self.tabs.count() > 0)

    # ------------------------------------------------------------ theme
    def _set_dark(self, on):
        self._dark = bool(on)
        if self.dark_act.isChecked() != self._dark:
            self.dark_act.blockSignals(True)
            self.dark_act.setChecked(self._dark)
            self.dark_act.blockSignals(False)
        theme.apply_theme(QApplication.instance(), self._dark)
        self.settings.setValue(
            "theme", theme.DARK if self._dark else theme.LIGHT)
        for w in self._all_views():
            if hasattr(w, "on_theme_changed"):
                w.on_theme_changed()

    # ------------------------------------------------------------ opening
    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open archive", "", ARCHIVE_FILTER)
        if path:
            self.open_archive(path)

    def _open_many(self, paths):
        for path in paths:
            if os.path.splitext(path)[1].lower() in ARCHIVE_EXT:
                self.open_archive(path)

    def open_archive(self, path):
        """Open `path` in a new tab (or focus the tab already showing it)."""
        path = os.path.abspath(path)
        for w in self._all_views():
            if isinstance(w, ArchiveView) and w.current_path and \
                    os.path.abspath(w.current_path) == path:
                self.tabs.setCurrentWidget(w)
                return w
        view = ArchiveView(path, settings=self.settings,
                           show_filter=self._show_filter)
        if self._splitter_state is not None:
            view.splitter.restoreState(self._splitter_state)
        view.status.connect(
            lambda msg, w=view: self._on_view_status(w, msg))
        view.busy.connect(lambda on, w=view: self._on_view_busy(w, on))
        view.title_changed.connect(lambda w=view: self._refresh_tab(w))
        view.loaded.connect(self._update_actions)
        view.open_failed.connect(
            lambda err, w=view: self._on_open_failed(w, err))
        index = self.tabs.addTab(view, _elide(view.title))
        self.tabs.setTabToolTip(index, view.summary())
        self.tabs.setCurrentIndex(index)
        self._remember_recent(path)
        self._update_empty_state()
        self._update_actions()
        view.start_scan()
        return view

    def open_diff(self, path_a, path_b):
        """Compare two archives in a new tab."""
        view = DiffView(path_a, path_b)
        view.status.connect(
            lambda msg, w=view: self._on_view_status(w, msg))
        view.busy.connect(lambda on, w=view: self._on_view_busy(w, on))
        view.title_changed.connect(lambda w=view: self._refresh_tab(w))
        index = self.tabs.addTab(view, _elide(view.title))
        self.tabs.setTabToolTip(index, "%s\n%s" % (path_a, path_b))
        self.tabs.setCurrentIndex(index)
        self._update_empty_state()
        self._update_actions()
        view.start()
        return view

    # ------------------------------------------------- recent files
    def _fill_recent_menu(self):
        self.recent_menu.clear()
        for path in self.settings.value("recent", []) or []:
            act = QAction(path, self)
            act.triggered.connect(lambda _=False, p=path:
                                  self.open_archive(p))
            self.recent_menu.addAction(act)
        if not self.recent_menu.actions():
            act = QAction("(no recent files)", self)
            act.setEnabled(False)
            self.recent_menu.addAction(act)

    def _remember_recent(self, path):
        recent = [p for p in (self.settings.value("recent", []) or [])
                  if p != path]
        recent.insert(0, path)
        self.settings.setValue("recent", recent[:10])

    # ------------------------------------------------------------ diff
    def _compare_current(self):
        view = self.view()
        if view is None or not view.current_path:
            QMessageBox.information(self, "No archive",
                                    "Open an archive first.")
            return
        dlg = DiffPickDialog(self, path_a=view.current_path)
        if dlg.exec() != QDialog.Accepted:
            return
        self.open_diff(dlg.path_a, dlg.path_b)

    def _diff(self):
        dlg = DiffPickDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        self.open_diff(dlg.path_a, dlg.path_b)

    # ------------------------------------------------------------ batch
    def _batch(self):
        if self._task is not None:
            QMessageBox.information(
                self, "Busy", "A task is running — wait for it to finish.")
            return
        dlg = BatchDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._run_window_task(
            "Batch extracting…",
            BatchWorker(dlg.search_dir, dlg.outdir),
            on_done=lambda res: TextDialog(
                self, "Batch extract",
                render_batch(dlg.search_dir, res)).exec())

    def _run_window_task(self, message, worker, on_done):
        self.statusBar().showMessage(message)
        self._task = worker
        self._update_actions()

        def done(result):
            self._task = None
            self._update_actions()
            self.statusBar().showMessage("Ready")
            on_done(result)

        def failed(err):
            self._task = None
            self._update_actions()
            self.statusBar().showMessage("Ready")
            QMessageBox.critical(self, "Task failed", err)

        worker.result_ready.connect(done)
        worker.failed.connect(failed)
        worker.start()

    # ------------------------------------------------------------ about
    def _about(self):
        QMessageBox.about(
            self, "About w3xmpq",
            "<b>w3xmpq %s</b><br><br>"
            "Open any Warcraft III map or MPQ archive — recovers "
            "encrypted files via a known-plaintext attack, no listfile "
            "needed.<br><br>"
            "Read-only: the tool never modifies your files.<br>"
            "<a href='https://github.com/kissanima/w3xmpq'>"
            "github.com/kissanima/w3xmpq</a>" % __version__)

    # ------------------------------------------------------------ drag&drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        self._open_many(paths)

    # ------------------------------------------------- compat accessors
    #: The tab host keeps the per-archive widgets inside ArchiveView, but
    #: older code (and the test suite) addresses them through the window.
    def _attr(self, name, default=None):
        view = self.view()
        return getattr(view, name) if view is not None else default

    @property
    def table(self):
        return self._attr("table")

    @property
    def folders(self):
        return self._attr("folders")

    @property
    def preview(self):
        return self._attr("preview")

    @property
    def preview_stack(self):
        return self._attr("preview_stack")

    @property
    def image_label(self):
        return self._attr("image_label")

    @property
    def banner(self):
        return self._attr("banner")

    @property
    def filter_edit(self):
        return self._attr("filter_edit")

    @property
    def show_combo(self):
        return self._attr("show_combo")

    @property
    def find_edit(self):
        return self._attr("find_edit")

    @property
    def find_count(self):
        return self._attr("find_count")

    @property
    def _find_row_widget(self):
        return self._attr("_find_row_widget")

    @property
    def _highlighter(self):
        return self._attr("_highlighter")

    @property
    def worker(self):
        view = self.view()
        return (view.worker if view is not None else None) or self._task

    @property
    def current_path(self):
        return self._attr("current_path")

    @current_path.setter
    def current_path(self, value):
        view = self.view()
        if view is not None:
            view.current_path = value

    @property
    def current_entries(self):
        return self._attr("current_entries")

    @current_entries.setter
    def current_entries(self, value):
        view = self.view()
        if view is not None:
            view.current_entries = value

    def apply_folder_filter(self, folder):
        view = self.view()
        if view is not None:
            view.apply_folder_filter(folder)

    def _selected_names(self):
        view = self.view()
        return view._selected_names() if view is not None else []

    def _write_table(self, path):
        return self.view()._write_table(path)

    def _save_entry_to(self, entry, path):
        return self.view()._save_entry_to(entry, path)

    def _toggle_find(self):
        self._call("_toggle_find")

    def _hide_find(self):
        self._call("_hide_find")

    def _find_next(self, backwards=False):
        view = self.view()
        if view is not None:
            view._find_next(backwards)


def main(argv=None):
    # Accept either real sys.argv or an explicit list (the CLI `gui`
    # subcommand passes just the archive path).
    args = list(sys.argv[1:]) if argv is None else list(argv)
    # Handle --version before any Qt machinery: release CI smoke-tests the
    # frozen binary with this flag, and it must work headless.
    if "--version" in args or "-V" in args:
        print("w3xmpq %s (GUI)" % __version__)
        return 0
    qt_args = [sys.argv[0]] + args
    app = QApplication(qt_args)
    app.setApplicationName("w3xmpq")
    app.setOrganizationName("w3xmpq")
    win = MainWindow()
    win.show()
    # Files passed on the command line open immediately, one tab each.
    for arg in args:
        if os.path.splitext(arg)[1].lower() in ARCHIVE_EXT \
                and os.path.isfile(arg):
            win.open_archive(arg)
    sys.exit(app.exec())
