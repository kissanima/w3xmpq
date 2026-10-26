# -*- coding: utf-8 -*-
"""Light and dark themes for the GUI.

Qt on Windows defaults to the native style, which ignores most of the
palette — a dark palette applied on top of it produces unreadable
half-themed widgets. The GUI therefore runs on the Fusion style, whose
palette is honoured everywhere, and dark mode is a palette + a small
stylesheet for the few widgets Fusion leaves light (headers, tabs,
tooltips).

Nothing here touches files: :func:`apply_theme` only re-polishes the
running application, so switching is instant and loses no state.
"""

from PySide6.QtGui import QColor, QPalette

__all__ = ["apply_theme", "is_dark", "colors", "theme_from_settings",
           "DARK", "LIGHT"]

DARK = "dark"
LIGHT = "light"

#: Colour roles used by widgets that paint text by hand (table rows,
#: diff panes). Filled per theme so nothing hard-codes `Qt.red`.
_PALETTES = {
    LIGHT: dict(
        bad="#c0392b",        # failed block / removed file
        muted="#8a8f98",      # unnamed file
        good="#1a7f37",       # added file
        changed="#8a5a00",    # modified file
        panel="#f2f3f5",
    ),
    DARK: dict(
        bad="#ff8080",
        muted="#8a8f98",
        good="#6cc98a",
        changed="#e3b341",
        panel="#26282d",
    ),
}

_DARK_PALETTE = {
    QPalette.Window: "#1f2126",
    QPalette.WindowText: "#e3e5e8",
    QPalette.Base: "#17181b",
    QPalette.AlternateBase: "#1c1e22",
    QPalette.ToolTipBase: "#2a2d33",
    QPalette.ToolTipText: "#e3e5e8",
    QPalette.Text: "#e3e5e8",
    QPalette.Button: "#2a2d33",
    QPalette.ButtonText: "#e3e5e8",
    QPalette.BrightText: "#ff8080",
    QPalette.Link: "#6ea8fe",
    QPalette.Highlight: "#2f6fbf",
    QPalette.HighlightedText: "#ffffff",
    QPalette.PlaceholderText: "#7c828c",
    QPalette.Light: "#3a3f47",
    QPalette.Midlight: "#33373e",
    QPalette.Mid: "#2c2f35",
    QPalette.Dark: "#141518",
    QPalette.Shadow: "#0e0f11",
}

_DARK_QSS = """
QToolTip {
    color: #e3e5e8; background: #2a2d33; border: 1px solid #3a3f47;
    padding: 3px;
}
QMenuBar, QMenu, QToolBar {
    background: #232529; color: #e3e5e8;
}
QMenu::separator { height: 1px; background: #33373e; margin: 4px 8px; }
QMenu::item:selected, QMenuBar::item:selected { background: #2f6fbf; }
QStatusBar { background: #1b1d21; color: #a9aeb6; }
QTabWidget::pane { border: 1px solid #33373e; }
QTabBar::tab {
    background: #26282d; color: #c9cdd4; padding: 5px 10px;
    border: 1px solid #33373e; border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #1f2126; color: #ffffff; }
QTabBar::tab:hover:!selected { background: #2f3238; }
QHeaderView::section {
    background: #26282d; color: #c9cdd4; padding: 3px;
    border: none; border-right: 1px solid #33373e;
    border-bottom: 1px solid #33373e;
}
QTableWidget { gridline-color: #2c2f35; }
QTreeWidget { background: #1b1d21; }
QPlainTextEdit {
    background: #17181b; color: #e3e5e8;
    selection-background-color: #2f6fbf; selection-color: #ffffff;
}
QSplitter::handle { background: #2c2f35; }
QProgressBar {
    background: #26282d; border: 1px solid #33373e;
    border-radius: 3px; text-align: center; color: #e3e5e8;
}
QProgressBar::chunk { background: #2f6fbf; border-radius: 2px; }
"""


def _app(app=None):
    if app is not None:
        return app
    from PySide6.QtWidgets import QApplication
    return QApplication.instance()


def is_dark(app=None):
    """True when the dark theme is active.

    Falls back to the palette's lightness when the theme was never
    applied (e.g. a widget built outside the GUI entry point).
    """
    app = _app(app)
    if app is None:
        return False
    flag = app.property("w3xmpq_dark")
    if flag is not None:
        return bool(flag)
    return app.palette().color(QPalette.Window).lightness() < 128


def colors(app=None):
    """Colour roles for the active theme."""
    return _PALETTES[DARK if is_dark(app) else LIGHT]


def theme_from_settings(settings, app=None):
    """The theme to start with: the saved choice, else the system's."""
    saved = settings.value("theme", "") if settings is not None else ""
    if saved in (DARK, LIGHT):
        return saved
    app = _app(app)
    if app is not None and \
            app.palette().color(QPalette.Window).lightness() < 128:
        return DARK
    return LIGHT


def apply_theme(app, dark):
    """Switch the whole application to the light or dark theme."""
    if app is None:
        return
    already = app.property("w3xmpq_dark")
    if already is not None and bool(already) == bool(dark) \
            and app.style().objectName().lower() == "fusion":
        return                       # no-op: avoids re-polishing everything
    # Fusion honours the palette on every platform; the native Windows
    # style would leave half the widgets light.
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")

    if dark:
        pal = QPalette()
        for role, value in _DARK_PALETTE.items():
            pal.setColor(role, QColor(value))
        # Disabled text must stay readable on the dark background.
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            pal.setColor(QPalette.Disabled, role, QColor("#6b7078"))
        app.setPalette(pal)
        app.setStyleSheet(_DARK_QSS)
    else:
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet("")
    app.setProperty("w3xmpq_dark", bool(dark))
