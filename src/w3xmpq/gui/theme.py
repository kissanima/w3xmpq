# -*- coding: utf-8 -*-
"""Light/dark themes and the semantic colour tokens the UI paints with.

Qt on Windows defaults to the native style, which ignores most of the
palette — a dark palette applied on top of it produces unreadable
half-themed widgets.  The GUI therefore runs on Fusion, whose palette is
honoured everywhere.

Widgets never hard-code a hex colour.  They ask :func:`tokens` for a
*semantic* role (``accent``, ``success``, ``warn``, ``danger`` …) so chips,
severity badges, the recovery bar and the diff highlights stay readable in
both themes.  The QSS below styles only widgets that opt in with a
``w3role`` dynamic property; everything else keeps the Fusion palette.

Nothing here touches files: :func:`apply_theme` only re-polishes the
running application, so switching is instant and loses no state.
"""

from PySide6.QtGui import QColor, QPalette

__all__ = ["apply_theme", "is_dark", "colors", "tokens", "qss",
           "theme_from_settings", "DARK", "LIGHT", "TOKEN_NAMES"]

DARK = "dark"
LIGHT = "light"

#: Semantic roles shared by every painted widget.  Both themes must define
#: exactly this set; a missing key is a programming error, not a default.
TOKEN_NAMES = (
    "accent", "accent_text", "accent_soft",
    "success", "warn", "danger", "info", "muted",
    "panel", "surface", "border", "text", "text_dim",
    "chip_bg", "chip_text", "chip_active_bg", "chip_active_text",
    "diff_add_bg", "diff_add_fg", "diff_del_bg", "diff_del_fg",
    "diff_hunk_bg", "progress_bg", "progress_fg", "progress_bad",
)

_TOKENS = {
    LIGHT: dict(
        accent="#1f6feb", accent_text="#ffffff", accent_soft="#d8e8ff",
        success="#1a7f37", warn="#9a6700", danger="#c0392b",
        info="#1f6feb", muted="#8a8f98",
        panel="#f2f3f5", surface="#ffffff", border="#d7dbe0",
        text="#1b1f24", text_dim="#5c636c",
        chip_bg="#ffffff", chip_text="#39414a",
        chip_active_bg="#1f6feb", chip_active_text="#ffffff",
        diff_add_bg="#d9f2df", diff_add_fg="#115c2a",
        diff_del_bg="#fde2de", diff_del_fg="#8b1d12",
        diff_hunk_bg="#fff4cf", progress_bg="#e3e6ea",
        progress_fg="#1f6feb", progress_bad="#c0392b",
    ),
    DARK: dict(
        accent="#4c9bff", accent_text="#10151c", accent_soft="#203a5e",
        success="#6cc98a", warn="#e3b341", danger="#ff8080",
        info="#6ea8fe", muted="#8a8f98",
        panel="#26282d", surface="#1b1d21", border="#3a3f47",
        text="#e3e5e8", text_dim="#a9aeb6",
        chip_bg="#26282d", chip_text="#c9cdd4",
        chip_active_bg="#2f6fbf", chip_active_text="#ffffff",
        diff_add_bg="#1d3d29", diff_add_fg="#a6e9bb",
        diff_del_bg="#4a2624", diff_del_fg="#ffb3ae",
        diff_hunk_bg="#463b1d", progress_bg="#2c2f35",
        progress_fg="#4c9bff", progress_bad="#ff8080",
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

#: Stylesheet built from tokens.  Only widgets carrying a ``w3role``
#: property are styled, so the rest of Fusion keeps following the palette.
_QSS = """
QFrame[w3role="strip"], QFrame[w3role="drawer"] {
    background: %(panel)s; border: 1px solid %(border)s; border-radius: 6px;
}
QFrame[w3role="drop"] {
    background: %(surface)s; border: 2px dashed %(border)s;
    border-radius: 10px;
}
QFrame[w3role="drop"][w3hot="true"] {
    border-color: %(accent)s; background: %(accent_soft)s;
}
QPushButton[w3role="accent"] {
    background: %(accent)s; color: %(accent_text)s;
    border: 1px solid %(accent)s; border-radius: 4px;
    padding: 6px 14px; font-weight: 600;
}
QPushButton[w3role="accent"]:hover { background: %(accent_soft)s;
    color: %(text)s; border-color: %(accent)s; }
QPushButton[w3role="accent"]:disabled { background: %(progress_bg)s;
    color: %(muted)s; border-color: %(border)s; }
QPushButton[w3role="chip"], QToolButton[w3role="chip"] {
    background: %(chip_bg)s; color: %(chip_text)s;
    border: 1px solid %(border)s; border-radius: 11px;
    padding: 3px 10px;
}
QPushButton[w3role="chip"]:checked, QToolButton[w3role="chip"]:checked {
    background: %(chip_active_bg)s; color: %(chip_active_text)s;
    border-color: %(chip_active_bg)s; font-weight: 600;
}
QPushButton[w3role="ghost"], QToolButton[w3role="ghost"] {
    background: transparent; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 4px; padding: 5px 10px;
}
QPushButton[w3role="ghost"]:hover, QToolButton[w3role="ghost"]:hover {
    background: %(accent_soft)s;
}
QPushButton[w3role="badge"] {
    background: %(chip_bg)s; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 10px; padding: 2px 9px;
}
QPushButton[w3role="badge"]:hover { background: %(accent_soft)s; }
QLabel[w3role="badge"] {
    background: %(chip_bg)s; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 10px; padding: 2px 9px;
}
QLabel[w3role="headline"] { color: %(text)s; font-weight: 600; }
QLabel[w3role="dim"] { color: %(text_dim)s; }
QLabel[w3role="severity-high"] { color: %(danger)s; font-weight: 600; }
QLabel[w3role="severity-warning"] { color: %(warn)s; font-weight: 600; }
QLabel[w3role="severity-info"] { color: %(info)s; }
QProgressBar {
    background: %(progress_bg)s; border: none; border-radius: 4px;
    text-align: center; color: %(text)s; height: 10px;
}
QProgressBar::chunk { background: %(progress_fg)s; border-radius: 4px; }
QProgressBar[w3role="recovery"]::chunk { background: %(success)s; }
QProgressBar[w3role="recovery"][w3state="warn"]::chunk { background: %(warn)s; }
QProgressBar[w3role="recovery"][w3state="bad"]::chunk { background: %(danger)s; }
QTableView { gridline-color: %(border)s; }
QHeaderView::section {
    background: %(panel)s; color: %(text_dim)s; padding: 4px 6px;
    border: none; border-right: 1px solid %(border)s;
    border-bottom: 1px solid %(border)s;
}
QToolTip { color: %(text)s; background: %(surface)s;
    border: 1px solid %(border)s; padding: 3px; }
QMenuBar, QMenu, QToolBar { background: %(panel)s; color: %(text)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 8px; }
QStatusBar { background: %(panel)s; color: %(text_dim)s; }
QTabWidget::pane { border: 1px solid %(border)s; }
QTabBar::tab {
    background: %(panel)s; color: %(text_dim)s; padding: 5px 10px;
    border: 1px solid %(border)s; border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: %(surface)s; color: %(text)s; }
QTabBar::tab:hover:!selected { background: %(accent_soft)s; }
QPlainTextEdit, QTextEdit, QTextBrowser {
    background: %(surface)s; color: %(text)s;
    selection-background-color: %(accent)s;
    selection-color: %(accent_text)s;
}
QSplitter::handle { background: %(border)s; }
QTreeWidget { background: %(surface)s; }
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


def tokens(app=None):
    """Semantic colour tokens for the active theme (see :data:`TOKEN_NAMES`)."""
    return _TOKENS[DARK if is_dark(app) else LIGHT]


def colors(app=None):
    """Legacy colour roles kept for the diff view and older callers."""
    t = tokens(app)
    return dict(bad=t["danger"], good=t["success"],
                changed=t["warn"], muted=t["muted"], panel=t["panel"])


def qss(app=None):
    """The token-substituted stylesheet for the active theme."""
    return _QSS % tokens(app)


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
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            pal.setColor(QPalette.Disabled, role, QColor("#6b7078"))
        app.setPalette(pal)
    else:
        app.setPalette(app.style().standardPalette())
    app.setProperty("w3xmpq_dark", bool(dark))
    app.setStyleSheet(qss(app))


def set_role(widget, role):
    """Opt a widget into a token-styled QSS rule (and keep it polished)."""
    widget.setProperty("w3role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


def repolish(widget):
    """Re-evaluate the stylesheet after a theme switch or property change."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget
