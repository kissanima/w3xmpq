# -*- coding: utf-8 -*-
"""w3xmpq GUI — main window.

The window is a *host*: every open archive is a tab holding one
:class:`~w3xmpq.gui.archive_view.ArchiveView`, a comparison is a tab holding
a :class:`~w3xmpq.gui.diff_view.DiffView`, and batch extraction is a tab
holding a :class:`~w3xmpq.gui.batch_view.BatchView`.  Per-archive state
lives in those widgets, so tabs are independent.

The window owns the one piece of shared state: a
:class:`~w3xmpq.gui.tasks.TaskManager`.  Scans, analysis, extraction,
rebuilds, diffs and batch runs all go through it, appear as cancellable
rows in the status-bar :class:`~w3xmpq.gui.tasks.TaskBar`, and never block
the rest of the UI.  Nothing modal is used for a long-running job.

Layout::

    ┌ toolbar: Open · Recent ▾ ·················· Theme · ⋯ ┐
    ├ tabs ──────────────────────────────────────────────────┤
    │  SummaryStrip      verdict + primary actions           │
    │  filter… │ chips with counts                           │
    │  folders │ FileTable (model/proxy) │ PreviewPane       │
    │  AnalysisDrawer    Report · Safety · Tasks             │
    └ status bar ─────────────────────────── TaskBar ───────┘
"""

import json
import os
import sys

from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtGui import QAction, QCursor, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QMainWindow,
                               QMenu, QMessageBox, QSizePolicy,
                               QStackedWidget, QTabWidget, QToolButton,
                               QWidget)

from .. import __version__
from . import theme
from .archive_view import ARCHIVE_FILTER, ArchiveView
from .batch_view import BatchView
from .diff_view import DiffView
from .empty_state import WelcomePage
from .tasks import TaskBar, TaskManager

#: Tab labels longer than this are elided; the tooltip keeps the path.
MAX_TITLE = 34

ARCHIVE_EXT = (".w3x", ".w3m", ".mpq")


def _elide(text, limit=MAX_TITLE):
    text = text or ""
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


class DropArea(QStackedWidget):
    """Central stack that accepts archives dropped anywhere on it."""

    files_dropped = Signal(list)
    drag_active = Signal(bool)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drag_active.emit(True)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.drag_active.emit(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        self.drag_active.emit(False)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)


class MainWindow(QMainWindow):
    def __init__(self, settings=None):
        """`settings` is injectable so tests never touch the user's prefs."""
        super().__init__()
        self.settings = settings if settings is not None else \
            QSettings("w3xmpq", "w3xmpq")
        self.tasks = TaskManager(self)
        self._dark = theme.theme_from_settings(self.settings) == theme.DARK
        theme.apply_theme(QApplication.instance(), self._dark)
        self._build_ui()
        self._restore_session()
        self._update_empty_state()
        self._update_actions()

    # ------------------------------------------------------------ session
    def _layouts(self):
        """Remembered per-archive view state, kept as a JSON string.

        QSettings cannot reliably round-trip a nested dict on every Qt
        build; JSON is boring and survives every backend.
        """
        raw = self.settings.value("layouts", "")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", "replace")
        try:
            value = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _save_layout(self, view):
        if not isinstance(view, ArchiveView) or not view.current_path:
            return
        layouts = self._layouts()
        try:
            layouts[os.path.abspath(view.current_path)] = view.layout_state()
        except Exception:                                    # noqa: BLE001
            return                  # never let persistence break a close
        self.settings.setValue("layouts", json.dumps(layouts))

    def _restore_session(self):
        geom = self.settings.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)

    def _save_session(self):
        self.settings.setValue("geometry", self.saveGeometry())
        for widget in self._all_views():
            self._save_layout(widget)
        self.settings.setValue(
            "theme", theme.DARK if self._dark else theme.LIGHT)

    def closeEvent(self, event):
        self._save_session()
        for widget in self._all_views():
            if hasattr(widget, "shutdown"):
                widget.shutdown()
        self.tasks.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------ tabs
    def view(self):
        """The archive in the current tab, or None (diff/batch/empty)."""
        w = self.tabs.currentWidget() if self.tabs.count() else None
        return w if isinstance(w, ArchiveView) else None

    def _all_views(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def _update_empty_state(self):
        self.stack.setCurrentIndex(1 if self.tabs.count() else 0)
        self.welcome.set_recent(self.settings.value("recent", []) or [])

    def _on_view_status(self, widget, message):
        """Status messages only apply to the tab you are looking at."""
        if widget is self.tabs.currentWidget():
            self.statusBar().showMessage(message)

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
        self._save_layout(widget)
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

        self.welcome = WelcomePage()
        self.welcome.open_requested.connect(self._open_dialog)
        self.welcome.recent_selected.connect(self.open_archive)

        self.stack = DropArea()
        self.stack.addWidget(self.welcome)     # 0 — empty state
        self.stack.addWidget(self.tabs)        # 1 — open tabs
        self.stack.files_dropped.connect(self._on_dropped)
        self.stack.drag_active.connect(self.welcome.set_hot)
        self.setCentralWidget(self.stack)

        self.task_bar = TaskBar(self.tasks)
        self.statusBar().addPermanentWidget(self.task_bar, 1)
        self.statusBar().showMessage("Ready")

        self._build_actions()
        self._build_menus()
        self._build_toolbar()

    def _build_actions(self):
        a = self._new_action

        self.open_act = a("&Open\u2026", QKeySequence.Open,
                          self._open_dialog)
        self.close_act = a("&Close tab", "Ctrl+W",
                           self._close_current_tab)
        self.extract_act = a("&Extract all\u2026", "Ctrl+E",
                             lambda: self._call("extract"))
        self.extract_sel_act = a("Extract &selected\u2026", "Ctrl+Shift+E",
                                 lambda: self._call("extract_selected"))
        self.save_prev_act = a("Save pre&view as\u2026", "Ctrl+S",
                               lambda: self._call("save_preview"))
        self.export_act = a("&Export file table\u2026", None,
                            lambda: self._call("export_table"))
        self.folder_act = a("Open containing &folder", None,
                            lambda: self._call("open_containing_folder"))
        self.quit_act = a("E&xit", None, self.close)

        self.report_act = a("&Deprotection report", None,
                            lambda: self._call("report"))
        self.scan_act = a("&Safety scan", None,
                          lambda: self._call("safety_scan"))
        self.rebuild_act = a("&Rebuild (WorldEdit-ready)\u2026", "Ctrl+R",
                             lambda: self._call("rebuild"))
        self.compare_act = a("Compare &with\u2026", "Ctrl+D",
                             self._compare_current)
        self.diff_act = a("&Compare two archives\u2026", None, self._diff)
        self.batch_act = a("&Batch extract folder", "Ctrl+B", self._batch)

        self.next_tab_act = a("Next tab", "Ctrl+Tab",
                              lambda: self._cycle_tab(1))
        self.prev_tab_act = a("Previous tab", "Ctrl+Shift+Tab",
                              lambda: self._cycle_tab(-1))
        self.dark_act = a("&Dark theme", "Ctrl+Shift+D", None)
        self.dark_act.setCheckable(True)
        self.dark_act.setChecked(self._dark)
        self.dark_act.toggled.connect(self._set_dark)
        self.about_act = a("&About", None, self._about)

        # Ctrl+1…9 jump straight to a tab, as advertised on the welcome
        # page.  QAction.triggered passes a bool, hence the default arg.
        for number in range(1, 10):
            act = a("Tab %d" % number, "Ctrl+%d" % number, None)
            act.triggered.connect(
                lambda _checked=False, n=number - 1: self._goto_tab(n))

        # Per-archive actions need an archive tab; tab management does not.
        self._need_view = [self.extract_act, self.extract_sel_act,
                           self.save_prev_act, self.export_act,
                           self.folder_act, self.report_act, self.scan_act,
                           self.rebuild_act, self.compare_act]
        self._need_tab = [self.close_act]

    def _new_action(self, title, shortcut, handler):
        act = QAction(title, self)
        if shortcut:
            act.setShortcut(shortcut)
        if handler is not None:
            act.triggered.connect(handler)
        return act

    def _goto_tab(self, index):
        if index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    def _build_menus(self):
        menu_file = self.menuBar().addMenu("&File")
        menu_file.addAction(self.open_act)
        self.recent_menu = menu_file.addMenu("Open &recent")
        self.recent_menu.aboutToShow.connect(
            lambda: self._fill_recent(self.recent_menu))
        menu_file.addAction(self.close_act)
        menu_file.addSeparator()
        for act in (self.extract_act, self.extract_sel_act,
                    self.save_prev_act, self.export_act, self.folder_act):
            menu_file.addAction(act)
        menu_file.addSeparator()
        menu_file.addAction(self.quit_act)

        self.menu_tools = self.menuBar().addMenu("&Tools")
        for act in (self.report_act, self.scan_act, self.rebuild_act, None,
                    self.compare_act, self.diff_act, None, self.batch_act):
            if act is None:
                self.menu_tools.addSeparator()
            else:
                self.menu_tools.addAction(act)

        menu_view = self.menuBar().addMenu("&View")
        menu_view.addAction(self.dark_act)
        menu_view.addSeparator()
        menu_view.addAction(self.next_tab_act)
        menu_view.addAction(self.prev_tab_act)

        menu_help = self.menuBar().addMenu("&Help")
        menu_help.addAction(self.about_act)

    def _build_toolbar(self):
        """Three things only: Open, Recent, Theme (+ an overflow menu)."""
        tb = self.addToolBar("main")
        tb.setMovable(False)
        tb.addAction(self.open_act)

        recent_btn = QToolButton()
        recent_btn.setText("Recent")
        recent_btn.setPopupMode(QToolButton.InstantPopup)
        self.recent_toolbar_menu = QMenu(self)
        self.recent_toolbar_menu.aboutToShow.connect(
            lambda: self._fill_recent(self.recent_toolbar_menu))
        recent_btn.setMenu(self.recent_toolbar_menu)
        tb.addWidget(recent_btn)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        tb.addAction(self.dark_act)
        more = QToolButton()
        more.setText("\u22ef")
        more.setToolTip("More tools")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setMenu(self.menu_tools)
        tb.addWidget(more)

    def _call(self, method):
        """Run a method of the current archive pane."""
        view = self.view()
        if view is not None:
            getattr(view, method)()

    def _update_actions(self):
        # Tasks are non-modal now: a running rebuild must never disable
        # browsing, extracting or opening another map.
        has_view = self.view() is not None
        for act in self._need_view:
            act.setEnabled(has_view)
        for act in self._need_tab:
            act.setEnabled(self.tabs.count() > 0)

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
        self.task_bar.apply_theme()
        for widget in self._all_views():
            if hasattr(widget, "on_theme_changed"):
                widget.on_theme_changed()
        self.welcome.apply_theme()

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
        for widget in self._all_views():
            if isinstance(widget, ArchiveView) and widget.current_path and \
                    os.path.abspath(widget.current_path) == path:
                self.tabs.setCurrentWidget(widget)
                return widget
        view = ArchiveView(path, settings=self.settings, tasks=self.tasks,
                           layout=self._layouts().get(path))
        self._wire(view)
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
        view = DiffView(path_a, path_b, tasks=self.tasks)
        self._wire(view)
        index = self.tabs.addTab(view, _elide(view.title))
        self.tabs.setTabToolTip(index, "%s\n%s" % (path_a, path_b))
        self.tabs.setCurrentIndex(index)
        self._update_empty_state()
        self._update_actions()
        view.start()
        return view

    def open_batch(self):
        """Focus the batch tab, creating it on first use."""
        for widget in self._all_views():
            if isinstance(widget, BatchView):
                self.tabs.setCurrentWidget(widget)
                return widget
        view = BatchView(self.tasks, settings=self.settings)
        view.set_default_folders(self.settings.value("batch_dir", ""),
                                 self.settings.value("batch_out", ""))
        self._wire(view)
        index = self.tabs.addTab(view, view.title)
        self.tabs.setTabToolTip(index, view.summary())
        self.tabs.setCurrentIndex(index)
        self._update_empty_state()
        self._update_actions()
        return view

    def _wire(self, view):
        """The signal contract shared by archive, diff and batch tabs."""
        view.status.connect(
            lambda msg, w=view: self._on_view_status(w, msg))
        if hasattr(view, "title_changed"):
            view.title_changed.connect(lambda w=view: self._refresh_tab(w))
        if hasattr(view, "loaded"):
            view.loaded.connect(self._update_actions)
        if hasattr(view, "open_failed"):
            view.open_failed.connect(
                lambda err, w=view: self._on_open_failed(w, err))

    def _on_open_failed(self, widget, err):
        self._refresh_tab(widget)
        QMessageBox.critical(self, "Could not open archive", err)

    # ------------------------------------------------- recent files
    def _fill_recent(self, menu):
        menu.clear()
        for path in self.settings.value("recent", []) or []:
            act = QAction(path, self)
            act.triggered.connect(lambda _=False, p=path:
                                  self.open_archive(p))
            menu.addAction(act)
        if not menu.actions():
            act = QAction("(no recent files)", self)
            act.setEnabled(False)
            menu.addAction(act)

    def _remember_recent(self, path):
        recent = [p for p in (self.settings.value("recent", []) or [])
                  if p != path]
        recent.insert(0, path)
        self.settings.setValue("recent", recent[:10])
        self.welcome.set_recent(recent[:10])

    # ------------------------------------------------------------ compare
    def _pick_archive(self, title):
        path, _ = QFileDialog.getOpenFileName(self, title, "",
                                              ARCHIVE_FILTER)
        return path or None

    def _compare_current(self):
        """Compare the current archive with one picked map — no picker form."""
        view = self.view()
        if view is None or not view.current_path:
            QMessageBox.information(self, "No archive",
                                    "Open an archive first.")
            return
        other = self._pick_archive("Compare with\u2026")
        if other:
            self.open_diff(view.current_path, other)

    def _diff(self):
        a = self._pick_archive("Compare: first archive")
        if not a:
            return
        b = self._pick_archive("Compare: second archive")
        if b:
            self.open_diff(a, b)

    def _batch(self):
        self.open_batch()

    # ------------------------------------------------------------ about
    def _about(self):
        QMessageBox.about(
            self, "About w3xmpq",
            "<b>w3xmpq %s</b><br><br>"
            "Open any Warcraft III map or MPQ archive \u2014 recovers "
            "encrypted files via a known-plaintext attack, no listfile "
            "needed.<br><br>"
            "Read-only: the tool never modifies your files.<br>"
            "<a href='https://github.com/kissanima/w3xmpq'>"
            "github.com/kissanima/w3xmpq</a>" % __version__)

    # -------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.welcome.set_hot(True)
            self.statusBar().showMessage(
                "Drop to open \u2014 or drop onto a tab to compare")

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.welcome.set_hot(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        self.welcome.set_hot(False)
        if paths:
            event.acceptProposedAction()
            self._on_dropped(paths)

    def _on_dropped(self, paths):
        paths = [p for p in paths
                 if os.path.splitext(p)[1].lower() in ARCHIVE_EXT]
        if not paths:
            return
        # Dropping a second map *onto a tab* means "compare these two".
        # QCursor gives the global position even for events delivered to
        # the central stack rather than to the window.
        bar = self.tabs.tabBar()
        index = bar.tabAt(bar.mapFromGlobal(QCursor.pos())) \
            if self.tabs.count() else -1
        if index >= 0:
            target = self.tabs.widget(index)
            if isinstance(target, ArchiveView) and target.current_path:
                self.open_diff(target.current_path, paths[0])
                self._open_many(paths[1:])
                return
        self._open_many(paths)


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
    return app.exec()
