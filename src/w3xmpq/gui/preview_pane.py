# -*- coding: utf-8 -*-
"""The preview pane: one file, with a header that says what it is.

The old preview was a bare ``QPlainTextEdit`` with find-in-file hidden
behind Ctrl+Shift+F (and that search jumped *backwards* while typing).
This one has a persistent header — file name, detected type, a manual
Text/Hex switch, Copy, Save as, and a visible Find button that reveals an
inline search row.  Textures still render as images; the Text/Hex switch
lets you inspect their raw bytes without leaving the pane.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (QFont, QImage, QKeySequence, QPixmap, QShortcut,
                           QTextCursor, QTextDocument)
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..core import filetypes
from ..core.blp import open_blp
from . import theme
from .jass_highlight import JassHighlighter, is_jass

TEXT_EXT = (".j", ".txt", ".ai", ".md", ".csv", ".json", ".xml", ".ini",
            ".wct", ".wtg", ".slk", ".wts")
HEX_PREVIEW_LIMIT = 8 * 1024
TEXT_PREVIEW_LIMIT = 200 * 1024


class FindEdit(QLineEdit):
    """Line edit that reports the Escape key (closes the find bar)."""
    escape_pressed = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.escape_pressed.emit()
            return
        super().keyPressEvent(event)


def _hexdump(data, limit=HEX_PREVIEW_LIMIT, width=16):
    rows = []
    for off in range(0, min(len(data), limit), width):
        chunk = data[off:off + width]
        hx = " ".join("%02x" % b for b in chunk)
        hx = hx.ljust(width * 3 - 1)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append("%08x  %s  %s" % (off, hx, asc))
    if len(data) > limit:
        rows.append("... (%d more bytes)" % (len(data) - limit))
    return "\n".join(rows)


def _is_text(name, data):
    if name and name.lower().endswith(TEXT_EXT):
        return True
    if not data:
        return False
    sample = data[:512]
    printable = sum(1 for b in sample
                    if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(sample) > 0.85


def preview_text(name, data):
    """Text shown for a file in a preview pane (text or hex dump)."""
    if _is_text(name, data):
        text = data[:TEXT_PREVIEW_LIMIT].decode("utf-8", "replace")
        if len(data) > TEXT_PREVIEW_LIMIT:
            text += "\n\u2026 (truncated)"
        return text
    return ("%d bytes \u2014 hex dump of first %d:\n\n%s"
            % (len(data), min(len(data), HEX_PREVIEW_LIMIT), _hexdump(data)))


def hex_text(data):
    return ("%d bytes \u2014 hex dump of first %d:\n\n%s"
            % (len(data), min(len(data), HEX_PREVIEW_LIMIT), _hexdump(data)))


class PreviewPane(QWidget):
    """Preview for the currently selected entry."""

    save_requested = Signal(object)
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entry = None
        self._text = ""
        self._hex = ""
        self._mode = "text"
        self._highlighter = None
        self._match_total = 0
        self._match_index = 0
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QFrame()
        theme.set_role(header, "strip")
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(8, 5, 8, 5)
        hbox.setSpacing(6)
        self.name_label = QLabel("No file selected")
        theme.set_role(self.name_label, "headline")
        self.name_label.setMinimumWidth(80)
        self.type_label = QLabel("")
        theme.set_role(self.type_label, "dim")
        hbox.addWidget(self.name_label, 1)
        hbox.addWidget(self.type_label)

        self.find_btn = QPushButton("Find")
        theme.set_role(self.find_btn, "ghost")
        self.find_btn.setCheckable(True)
        self.find_btn.setToolTip("Find in this file (Ctrl+Shift+F)")
        self.find_btn.clicked.connect(self.set_find_visible)
        hbox.addWidget(self.find_btn)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.text_btn = QPushButton("Text")
        self.hex_btn = QPushButton("Hex")
        for btn in (self.text_btn, self.hex_btn):
            btn.setCheckable(True)
            theme.set_role(btn, "ghost")
            btn.setMaximumWidth(52)
            self.mode_group.addButton(btn)
            hbox.addWidget(btn)
        self.text_btn.setChecked(True)
        self.text_btn.clicked.connect(lambda: self.set_mode("text"))
        self.hex_btn.clicked.connect(lambda: self.set_mode("hex"))
        self.mode_group.buttonClicked.connect(self._mode_button)

        self.copy_btn = QPushButton("Copy")
        theme.set_role(self.copy_btn, "ghost")
        self.copy_btn.setToolTip("Copy the visible text to the clipboard")
        self.copy_btn.clicked.connect(self.copy)
        hbox.addWidget(self.copy_btn)

        self.save_btn = QPushButton("Save as\u2026")
        theme.set_role(self.save_btn, "ghost")
        self.save_btn.setToolTip("Write this file's bytes to disk")
        self.save_btn.clicked.connect(
            lambda: self.save_requested.emit(self.entry))
        hbox.addWidget(self.save_btn)
        header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(header)

        # Inline find row, visible when the Find button is on.
        self._find_row_widget = QFrame()
        fbox = QHBoxLayout(self._find_row_widget)
        fbox.setContentsMargins(6, 2, 6, 2)
        fbox.setSpacing(4)
        self.find_prev = QPushButton("\u25c0")
        self.find_prev.setMaximumWidth(30)
        self.find_next = QPushButton("\u25b6")
        self.find_next.setMaximumWidth(30)
        self.find_edit = FindEdit()
        self.find_edit.setPlaceholderText("find in file\u2026")
        self.find_count = QLabel("")
        theme.set_role(self.find_count, "dim")
        fbox.addWidget(self.find_prev)
        fbox.addWidget(self.find_edit, 1)
        fbox.addWidget(self.find_next)
        fbox.addWidget(self.find_count)
        self._find_row_widget.setVisible(False)
        self._find_row_widget.setSizePolicy(QSizePolicy.Preferred,
                                            QSizePolicy.Fixed)
        layout.addWidget(self._find_row_widget)
        self.find_prev.clicked.connect(lambda: self._find_next(True))
        self.find_next.clicked.connect(lambda: self._find_next(False))
        self.find_edit.returnPressed.connect(lambda: self._find_next(False))
        self.find_edit.escape_pressed.connect(self._hide_find)
        self.find_edit.textChanged.connect(self._find_changed)
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        self._find_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._find_shortcut.activated.connect(self._toggle_find)

        self.preview_stack = QStackedWidget()
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        self.preview.setFont(font)
        self.preview.setPlaceholderText(
            "Select a file to preview it here. Textures render as images; "
            "use Text / Hex to inspect their bytes.")
        self.preview_stack.addWidget(self.preview)

        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setAlignment(Qt.AlignCenter)
        self.image_label = QLabel("No image")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_scroll.setWidget(self.image_label)
        self.preview_stack.addWidget(self.image_scroll)
        layout.addWidget(self.preview_stack, 1)

    # ------------------------------------------------------------ entry
    def clear(self):
        self.entry = None
        self._text = self._hex = ""
        self.name_label.setText("No file selected")
        self.type_label.setText("")
        self.preview.setPlainText("")
        self.image_label.clear()
        self._show_text_page()
        self._detach_highlighter()

    def set_entry(self, entry):
        """Preview one scanned entry (or clear on None / FAILED)."""
        if entry is None or filetypes.is_failed(entry) or \
                entry.get("data") is None:
            self.clear()
            return
        self.entry = entry
        name = entry.get("name")
        data = entry["data"] or b""
        kind = filetypes.detect(name, data)
        self.name_label.setText(filetypes.display_name(entry))
        self.name_label.setToolTip(name or filetypes.entry_name(entry))
        self.type_label.setText("%s %s" % (kind.label, kind.ext))
        self._text = preview_text(name, data)
        self._hex = hex_text(data)
        # Start on the image for a texture, on text otherwise.
        if kind.key == "texture" and self._show_image(name, data):
            self._detach_highlighter()
        else:
            self._show_text_page()
            self._render_mode()

    def set_mode(self, mode):
        """Manual Text/Hex switch — also leaves the image page."""
        self._mode = "hex" if mode == "hex" else "text"
        (self.hex_btn if self._mode == "hex" else self.text_btn) \
            .setChecked(True)
        self._show_text_page()
        self._render_mode()

    def _mode_button(self, button):
        self.set_mode("hex" if button is self.hex_btn else "text")

    @property
    def mode(self):
        return self._mode

    def _render_mode(self):
        text = self._hex if self._mode == "hex" else self._text
        self.preview.setPlainText(text)
        self._apply_highlighter(self._mode == "text" and
                                is_jass((self.entry or {}).get("name") or ""))
        if self._find_row_widget.isVisible():
            self._find_changed(self.find_edit.text())

    # --------------------------------------------------------- image
    def _show_text_page(self):
        self.preview_stack.setCurrentIndex(0)

    def _show_image(self, name, data):
        mip = None
        blp = None
        try:
            if data[:4] in (b"BLP1", b"BLP2"):
                blp = open_blp(data)
                if blp.is_jpeg:
                    image = QImage()
                    if not image.loadFromData(blp.jpeg_bytes(0)):
                        raise ValueError("Qt could not decode the JPEG stream")
                else:
                    image = QImage.fromData(blp.png_bytes(0))
                    if image.isNull():
                        raise ValueError("unsupported BLP encoding")
            else:
                # PNG/JPG/GIF/BMP textures are plain image files.
                image = QImage.fromData(data)
                if image.isNull():
                    raise ValueError("unsupported image encoding")
        except Exception as exc:                          # noqa: BLE001
            self._show_text_page()
            self.preview.setPlainText("Could not render %s:\n%s"
                                      % (name or "texture", exc))
            return False
        image = image.convertToFormat(QImage.Format_ARGB32)
        pixmap = QPixmap.fromImage(image)
        self.image_label.setPixmap(pixmap)
        self.preview_stack.setCurrentIndex(1)
        if blp is not None:
            mip = blp.mipmaps[0] if blp.mipmaps else None
        if mip:
            self.status.emit("%s \u2014 %dx%d %s, %d mipmap level(s)"
                             % (filetypes.display_name(self.entry),
                                mip.width, mip.height, blp.kind.upper(),
                                len(blp.mipmaps)))
        else:
            self.status.emit("%s \u2014 %dx%d image"
                             % (filetypes.display_name(self.entry),
                                image.width(), image.height()))
        return True

    # ---------------------------------------------------- highlighting
    def _detach_highlighter(self):
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
            self._highlighter = None

    def _apply_highlighter(self, enabled):
        self._detach_highlighter()
        if enabled:
            self._highlighter = JassHighlighter(self.preview.document())

    # ------------------------------------------------------------ find
    def set_find_visible(self, on):
        self.find_btn.setChecked(bool(on))
        self._find_row_widget.setVisible(bool(on))
        if on:
            self.find_edit.setFocus()
            self.find_edit.selectAll()
            self._find_changed(self.find_edit.text())
        else:
            self.find_count.setText("")

    def _toggle_find(self):
        self.set_find_visible(not self._find_row_widget.isVisible())

    def _hide_find(self):
        self.set_find_visible(False)

    def _find_changed(self, text):
        """Restart at the top and search *forward* while typing."""
        needle = text or ""
        if not needle:
            self.find_count.setText("")
            self._match_total = self._match_index = 0
            return
        self._match_total = self.preview.toPlainText().lower().count(
            needle.lower())
        if not self._match_total:
            self.find_count.setText("no matches")
            return
        self._match_index = 1
        cursor = self.preview.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.preview.setTextCursor(cursor)
        self.preview.find(needle)
        self.find_count.setText("%d / %d" % (self._match_index,
                                             self._match_total))

    def _find_next(self, backwards=False):
        needle = self.find_edit.text()
        if not needle or not self._match_total:
            return
        flags = QTextDocument.FindBackward if backwards else None
        found = (self.preview.find(needle, flags) if flags is not None
                 else self.preview.find(needle))
        if not found:                      # wrap around
            cursor = self.preview.textCursor()
            cursor.movePosition(QTextCursor.End if backwards
                                else QTextCursor.Start)
            self.preview.setTextCursor(cursor)
            found = (self.preview.find(needle, flags) if flags is not None
                     else self.preview.find(needle))
        if found:
            self._match_index = self._match_index + (-1 if backwards else 1)
            self._match_index = (self._match_index - 1) % self._match_total + 1
            self.find_count.setText("%d / %d" % (self._match_index,
                                                 self._match_total))
        else:
            self.find_count.setText("no matches")

    # ----------------------------------------------------------- actions
    def copy(self):
        from PySide6.QtGui import QGuiApplication
        text = self.preview.toPlainText()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.status.emit("Copied %d characters" % len(text))

    def apply_theme(self):
        for w in (self.name_label, self.type_label, self.find_btn,
                  self.text_btn, self.hex_btn, self.copy_btn, self.save_btn,
                  self.find_count):
            theme.repolish(w)
        if self.entry is not None:
            self._apply_highlighter(self._mode == "text" and
                                    is_jass((self.entry or {}).get("name")
                                            or ""))
