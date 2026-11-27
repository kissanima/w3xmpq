#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI tests (offscreen) for the redesigned w3xmpq interface.

Everything here addresses the *views* directly — the window is only a tab
host now, so the old ~30 compatibility properties are gone.  Skipped
entirely when PySide6 is missing so the non-GUI CI matrix still passes.
"""

import atexit
import itertools
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, 'fixtures'))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..', 'src')))

import gen_synth  # noqa: E402

try:
    from PySide6.QtCore import (QEventLoop, QItemSelectionModel, QSettings,
                                QTimer, Qt)
    from PySide6.QtWidgets import QApplication, QAbstractItemView
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from w3xmpq.gui.main_window import MainWindow as _RealMainWindow

    # QSettings("w3xmpq", "w3xmpq") lands in the user's registry/INI.  Every
    # window here gets its own throw-away INI, so remembered layouts, recent
    # maps and geometry can never leak between tests or into real preferences.
    _settings_home = tempfile.TemporaryDirectory(prefix="w3xmpq-gui-test-")
    atexit.register(_settings_home.cleanup)
    _window_ids = itertools.count()

    def MainWindow(*args, **kwargs):
        ini = os.path.join(_settings_home.name,
                           "settings-%d.ini" % next(_window_ids))
        kwargs.setdefault("settings", QSettings(ini, QSettings.IniFormat))
        return _RealMainWindow(*args, **kwargs)


def _make_blp1(width=4, height=4):
    """A classic BLP1 texture: uncompressed BGRA, bottom-up."""
    import struct
    header = bytearray(0x9C)
    header[0:4] = b'BLP1'
    struct.pack_into('<I', header, 0x04, 0)      # encoding: uncompressed
    struct.pack_into('<I', header, 0x08, 1)      # alpha present
    struct.pack_into('<I', header, 0x0C, width)
    struct.pack_into('<I', header, 0x10, height)
    pixels = b''.join(bytes([30, 60, 90, 255]) * width
                      for _ in range(height))
    struct.pack_into('<I', header, 0x1C, 0x9C)
    struct.pack_into('<I', header, 0x5C, len(pixels))
    return bytes(header) + pixels


def _make_map(tmp):
    """Write a synthetic .w3x built from the standard sample set."""
    path = os.path.join(tmp, 'gui_test.w3x')
    with open(path, 'wb') as f:
        f.write(gen_synth.build_w3x(gen_synth.build_archive(
            gen_synth.sample_file_set())))
    return path


def _make_image_map(tmp):
    """A .w3x holding a .blp texture and a JASS script."""
    path = os.path.join(tmp, 'images.w3x')
    files = [
        dict(name='war3mapMap.blp', data=_make_blp1(),
             flags=gen_synth.F_EXISTS),
        dict(name='war3map.j',
             data=b'function main takes nothing returns nothing\n'
                  b'    // a comment\n'
                  b'    local integer i = 42\n'
                  b'    set i = i + 1\n'
                  b'endfunction\n',
             flags=gen_synth.F_EXISTS),
    ]
    with open(path, 'wb') as f:
        f.write(gen_synth.build_w3x(gen_synth.build_archive(files)))
    return path


def _make_model_map(tmp):
    """A .w3x holding one synthetic static MDX model."""
    from test_mdx2fbx import build_mdx
    path = os.path.join(tmp, 'models.w3x')
    files = [dict(name='Units\\Test\\Test.mdx', data=build_mdx(),
                  flags=gen_synth.F_EXISTS)]
    with open(path, 'wb') as f:
        f.write(gen_synth.build_w3x(gen_synth.build_archive(files)))
    return path


def _real_blp_path():
    """A genuine Warcraft III .blp file, if the game is installed."""
    base = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', '..', '..'))
    ui = os.path.join(base, 'UI')
    if not os.path.isdir(ui):
        return None
    for dirpath, _dirs, files in os.walk(ui):
        for name in sorted(files):
            if name.lower().endswith('.blp'):
                return os.path.join(dirpath, name)
    return None


def _make_foldered_map(tmp):
    """A .w3x whose files live in folders (zip-tree test fixture)."""
    path = os.path.join(tmp, 'folders.w3x')
    names = ['war3map.j', 'textures\\tex.blp', 'textures\\ui\\plus.blp',
             'Scripts\\relocated.j']
    files = [
        dict(name=names[0],
             data=b'function main takes nothing returns nothing\n' * 30,
             flags=gen_synth.F_EXISTS),
        dict(name=names[1], data=os.urandom(2000),
             flags=gen_synth.F_EXISTS),
        dict(name=names[2], data=os.urandom(1000),
             flags=gen_synth.F_EXISTS),
        dict(name=names[3], data=b'x' * 500,
             flags=gen_synth.F_EXISTS),
        # Real tool-made MPQs embed this; the scanner should use it.
        dict(name='(listfile)',
             data=("\n".join(names) + "\n").encode(),
             flags=gen_synth.F_EXISTS),
    ]
    with open(path, 'wb') as f:
        f.write(gen_synth.build_w3x(gen_synth.build_archive(files)))
    return path


def _make_pair(tmp):
    """Two maps that differ in one file, add one file and drop one."""
    v1 = [
        dict(name='war3map.j',
             data=b'function main takes nothing returns nothing\n'
                  b'endfunction\n' * 4,
             flags=gen_synth.F_EXISTS),
        dict(name='shared.bin', data=b'SAME CONTENT', flags=gen_synth.F_EXISTS),
        dict(name='removed.bin', data=b'BYE', flags=gen_synth.F_EXISTS),
    ]
    v2 = [
        dict(name='war3map.j',
             data=b'function main takes nothing returns nothing\n'
                  b'    call DoNothing()\n'
                  b'endfunction\n' * 4,
             flags=gen_synth.F_EXISTS),
        dict(name='shared.bin', data=b'SAME CONTENT', flags=gen_synth.F_EXISTS),
        dict(name='added.bin', data=b'HELLO', flags=gen_synth.F_EXISTS),
    ]

    def write(files, name):
        files = list(files) + [dict(
            name='(listfile)',
            data=("\n".join(f['name'] for f in files) + "\n").encode(),
            flags=gen_synth.F_EXISTS)]
        path = os.path.join(tmp, name)
        with open(path, 'wb') as f:
            f.write(gen_synth.build_w3x(gen_synth.build_archive(files)))
        return path

    return write(v1, 'v1.w3x'), write(v2, 'v2.w3x')


def _wait_until(predicate, timeout_ms=30000):
    """Spin the event loop until predicate() is true (or time out)."""
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(50)
    poll.timeout.connect(lambda: predicate() and loop.quit())
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout_ms)
    loop.exec()
    poll.stop()
    deadline.stop()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestGuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls.map_path = _make_map(cls._tmp.name)
        cls.folders_path = _make_foldered_map(cls._tmp.name)
        cls.image_path = _make_image_map(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _open(self, path):
        win = MainWindow()
        view = win.open_archive(path)
        # The scan is followed by an automatic report/safety job on the
        # shared manager; wait for both so assertions see a settled view.
        _wait_until(lambda: view.worker is None
                    and not win.tasks.active_jobs())
        return win, view

    def _visible(self, view):
        return [view.table.entry_at(r)
                for r in range(view.table.row_count())]

    def test_open_scan_summary_and_preview(self):
        win, view = self._open(self.map_path)
        self.assertIsNone(view.worker)
        self.assertIsNotNone(view.current_entries)
        self.assertGreater(view.table.row_count(), 0)
        # The verdict is the headline, not a dot-separated footnote.
        self.assertIn("blocks recovered",
                      view.summary_strip.headline.text())
        self.assertIn("%" , view.summary_strip.detail.text())
        self.assertGreater(view.summary_strip.progress.value(), 0)
        # Chip counts come from the model, independent of the filter.
        counts = view.table.counts()
        self.assertEqual(counts["all"], view.table.source_count())
        view.table.select_first_ok()
        self.assertTrue(view.banner.text().strip())
        win.close()

    def test_extract_via_worker(self):
        from w3xmpq.gui.workers import ExtractWorker
        win = MainWindow()
        outdir = os.path.join(self._tmp.name, 'out')
        done = {}
        loop = QEventLoop()
        w = ExtractWorker(self.map_path, outdir)

        def on_done(manifest):
            done['manifest'] = manifest
            loop.quit()

        w.result_ready.connect(on_done)
        w.failed.connect(lambda e: (done.__setitem__('err', e), loop.quit()))
        w.start()
        QTimer.singleShot(30000, loop.quit)
        loop.exec()
        self.assertNotIn('err', done)
        got = sum(1 for r in done['manifest'] if r['status'] == 'ok')
        self.assertGreater(got, 0)
        self.assertTrue(os.path.isdir(outdir))
        win.close()

    def test_extract_selected_by_block_including_unnamed(self):
        """A protected map's unnamed files are exactly the ones to extract."""
        import re
        from w3xmpq.gui.workers import ExtractWorker
        win, view = self._open(self.map_path)
        view.table.select_first_ok()
        blocks = view._selected_blocks()
        self.assertEqual(len(blocks), 1)
        self.assertTrue(view.selected_entries())
        names = view._selected_names()
        self.assertEqual(len(names), 1)

        outdir = os.path.join(self._tmp.name, 'sel')
        done = {}
        loop = QEventLoop()
        w = ExtractWorker(
            self.map_path, outdir,
            pattern="|".join(re.escape(n) for n in names) if names else None,
            blocks=blocks)

        def on_done(manifest):
            done['manifest'] = manifest
            loop.quit()

        w.result_ready.connect(on_done)
        w.failed.connect(lambda e: (done.__setitem__('err', e), loop.quit()))
        w.start()
        QTimer.singleShot(30000, loop.quit)
        loop.exec()
        self.assertNotIn('err', done)
        extracted = [r['name'] for r in done['manifest']
                     if r.get('extracted')]
        self.assertEqual(extracted, [names[0]])
        win.close()

    def test_folder_tree_and_proxy_filter(self):
        win, view = self._open(self.folders_path)
        tree = view.folders
        root = tree.topLevelItem(0)
        self.assertEqual(root.text(0), "(all files)")
        top = {root.child(i).text(0) for i in range(root.childCount())}
        self.assertIn("Scripts/", top)
        self.assertIn("textures/", top)
        tex = [root.child(i) for i in range(root.childCount())
               if root.child(i).text(0) == "textures/"][0]
        self.assertEqual(tex.child(0).text(0), "ui/")

        total = view.table.row_count()
        view.apply_folder_filter("textures")
        rows = self._visible(view)
        self.assertGreaterEqual(len(rows), 2)
        for e in rows:
            self.assertTrue((e["name"] or "").replace("/", "\\")
                            .startswith("textures\\"), e["name"])
        view.apply_folder_filter("textures\\ui")
        self.assertEqual(len(self._visible(view)), 1)
        view.apply_folder_filter(None)
        self.assertEqual(len(self._visible(view)), total)
        win.close()

    def test_multi_select_and_live_filter(self):
        win, view = self._open(self.folders_path)
        self.assertEqual(view.table.selectionMode(),
                         QAbstractItemView.ExtendedSelection)
        view.table.clearSelection()
        model = view.table.selectionModel()
        for r in (0, 1):
            model.select(view.table.model().index(r, 0),
                         QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.assertGreaterEqual(len(view.table.selected_entries()), 2)

        view.filter_edit.setText("tex")
        rows = self._visible(view)
        self.assertTrue(rows)
        for e in rows:
            self.assertIn("tex", (e["name"] or "").lower())
        view.filter_edit.setText("")
        self.assertEqual(len(self._visible(view)),
                         view.table.source_count())
        win.close()

    def test_sorting_keeps_entries_in_sync(self):
        win, view = self._open(self.folders_path)
        view.table.sortByColumn(2, Qt.DescendingOrder)   # Size
        sizes = [e["size"] for e in self._visible(view)]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        view.table.sortByColumn(0, Qt.AscendingOrder)    # Name
        names = [(e["name"] or "").lower() for e in self._visible(view)]
        self.assertEqual(names, sorted(names))
        win.close()

    def test_filter_chips_use_model_counts(self):
        win, view = self._open(self.image_path)
        counts = view.table.counts()
        self.assertEqual(counts["all"], view.table.source_count())
        self.assertGreaterEqual(counts["texture"], 1)
        view.chips.set_current("texture")
        self.assertEqual(view.chips.current(), "texture")
        rows = self._visible(view)
        self.assertTrue(rows)
        for e in rows:
            from w3xmpq.core import filetypes
            self.assertEqual(filetypes.category(e), "texture")
        # Counts must NOT shrink when a filter is applied.
        self.assertEqual(view.table.counts()["all"],
                         view.table.source_count())
        view.chips.set_current("all")
        win.close()

    def test_find_in_preview_searches_forward(self):
        win, view = self._open(self.folders_path)
        row = next(r for r in range(view.table.row_count())
                   if (view.table.entry_at(r)["name"] or "")
                   .endswith("war3map.j"))
        view.table.selectRow(row)
        pane = view.preview
        self.assertIn("function", pane.preview.toPlainText())
        pane.set_find_visible(True)
        pane.find_edit.setText("function main")
        self.assertRegex(pane.find_count.text(), r"^1 / \d+$")
        self.assertLess(pane.preview.textCursor().blockNumber(), 5)
        pane.find_edit.setText("zzz-not-there")
        self.assertEqual(pane.find_count.text(), "no matches")
        pane.set_find_visible(False)
        self.assertFalse(pane._find_row_widget.isVisible())
        win.close()

    def test_preview_text_hex_switch(self):
        win, view = self._open(self.folders_path)
        view.table.select_first_ok()
        pane = view.preview
        pane.set_mode("hex")
        self.assertEqual(pane.mode, "hex")
        self.assertIn("00000000", pane.preview.toPlainText())
        pane.set_mode("text")
        self.assertEqual(pane.mode, "text")
        win.close()

    def test_export_table_and_save_entry(self):
        win, view = self._open(self.folders_path)
        out = os.path.join(self._tmp.name, "table.json")
        count = view._write_table(out)
        self.assertEqual(count, len(view.current_entries))
        with open(out, encoding="utf-8") as f:
            rows = json.load(f)
        self.assertEqual(len(rows), count)
        self.assertIn("name_source", rows[0])
        self.assertIn("detected_type", rows[0])

        csv_path = os.path.join(self._tmp.name, "table.csv")
        view._write_table(csv_path)
        with open(csv_path, encoding="utf-8") as f:
            head = f.readline()
        self.assertIn("sha256", head)

        e = next(x for x in view.current_entries if x["status"] == "ok")
        target = os.path.join(self._tmp.name, "one.bin")
        n = view._save_entry_to(e, target)
        self.assertEqual(n, len(e["data"]))
        with open(target, "rb") as f:
            self.assertEqual(f.read(), e["data"])
        win.close()

    def test_layout_state_roundtrip_with_hex_splitter(self):
        win, view = self._open(self.folders_path)
        view.chips.set_current("texture")
        view.table.set_advanced(True)
        view.drawer.open_safety()
        state = view.layout_state()
        # QSettings needs plain JSON-safe values, not a QByteArray.
        json.dumps(state)
        self.assertIsInstance(state["splitter"], str)
        self.assertEqual(state["chip"], "texture")
        self.assertTrue(state["advanced"])
        fresh = win.open_archive(self.image_path)
        _wait_until(lambda: fresh.worker is None)
        fresh.restore_layout_state(state)
        self.assertEqual(fresh.chips.current(), "texture")
        self.assertTrue(fresh.table.advanced)
        self.assertTrue(fresh.drawer.expanded)
        win._save_session()
        saved = json.loads(win.settings.value("layouts", "{}"))
        self.assertIn(os.path.abspath(self.folders_path), saved)
        win.close()

    def test_unnamed_entry_is_selectable_and_extractable(self):
        from w3xmpq.core import filetypes
        win, view = self._open(self.map_path)
        entry = dict(block=999, name=None, size=4, archived_size=4,
                     flags=0, status="ok", name_source="unknown",
                     key_method="plain", sha256=None, data=b"BLP1")
        self.assertFalse(filetypes.is_named(entry))
        self.assertIn("texture", filetypes.display_name(entry))
        self.assertTrue(filetypes.entry_name(entry).endswith(".blp"))
        view.table.load_entries([entry])
        view.table.selectRow(0)
        self.assertEqual(view._selected_blocks(), [999])
        self.assertEqual(view._selected_names(), [])
        win.close()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestFileTypes(unittest.TestCase):
    """Content-based detection survives a stripped listfile."""

    def test_magic_beats_extension(self):
        from w3xmpq.core import filetypes
        kind = filetypes.detect("notes.txt", _make_blp1()[:8])
        self.assertEqual(kind.key, "texture")
        self.assertEqual(filetypes.category(dict(name="notes.txt",
                                                 data=_make_blp1()[:8])),
                         "texture")

    def test_unnamed_names_are_safe(self):
        from w3xmpq.core import filetypes
        e = dict(block=7, name=None, data=b"MDLX" + b"\0" * 20,
                 name_source="unknown", flags=0, status="ok")
        self.assertEqual(filetypes.entry_name(e), "model_0007.mdx")
        self.assertIn("model", filetypes.display_name(e))
        self.assertFalse(filetypes.is_named(e))

    def test_flags_and_failure(self):
        from w3xmpq.core import filetypes
        self.assertTrue(filetypes.is_failed(dict(status="FAILED")))
        self.assertFalse(filetypes.is_failed(dict(status="ok")))
        self.assertTrue(filetypes.is_encrypted(
            dict(flags=filetypes.FLAG_ENCRYPTED)))


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestGuiPreview(unittest.TestCase):
    """Image preview, syntax highlighting and the Text/Hex switch."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls.image_map = _make_image_map(cls._tmp.name)
        cls.model_map = _make_model_map(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _open(self):
        win = MainWindow()
        view = win.open_archive(self.image_map)
        _wait_until(lambda: view.worker is None)
        return win, view

    def _row_for(self, view, suffix):
        for r in range(view.table.row_count()):
            e = view.table.entry_at(r)
            if e and (e.get("name") or "").endswith(suffix):
                return r
        return None

    def test_blp_shows_an_image(self):
        win, view = self._open()
        row = self._row_for(view, ".blp")
        self.assertIsNotNone(row, "no .blp entry in the table")
        view.table.selectRow(row)
        self.assertEqual(view.preview.preview_stack.currentIndex(), 1)
        pixmap = view.preview.image_label.pixmap()
        self.assertFalse(pixmap.isNull())
        self.assertGreater(pixmap.width(), 0)
        win.close()

    def test_text_file_switches_back_to_text(self):
        win, view = self._open()
        view.table.selectRow(self._row_for(view, ".blp"))
        self.assertEqual(view.preview.preview_stack.currentIndex(), 1)
        view.table.selectRow(self._row_for(view, ".j"))
        self.assertEqual(view.preview.preview_stack.currentIndex(), 0)
        win.close()

    def test_mdx_shows_model_on_single_click(self):
        win = MainWindow()
        view = win.open_archive(self.model_map)
        _wait_until(lambda: view.worker is None)
        row = self._row_for(view, ".mdx")
        self.assertIsNotNone(row, "no .mdx entry in the table")
        view.table.selectRow(row)
        self.assertEqual(view.preview.preview_stack.currentIndex(), 2)
        self.assertTrue(view.preview.model_btn.isChecked())
        self.assertEqual(view.preview.model_view.mesh['included_geosets'], 1)
        self.assertEqual(view.preview.model_view.mesh['triangle_count'], 2)
        view.preview.set_mode("text")
        self.assertEqual(view.preview.preview_stack.currentIndex(), 0)
        view.preview.set_mode("model")
        self.assertEqual(view.preview.preview_stack.currentIndex(), 2)
        win.close()

    def test_jass_is_highlighted(self):
        win, view = self._open()
        view.table.selectRow(self._row_for(view, ".j"))
        self.assertIsNotNone(view.preview._highlighter)
        win.close()

    def test_jass_classification(self):
        from w3xmpq.gui.jass_highlight import classify_jass
        line = "    set i = i + 1   // add one"
        spans = classify_jass(line)
        roles = {role for _s, _l, role in spans}
        self.assertIn("keyword", roles)
        self.assertIn("comment", roles)
        for start, length, role in spans:
            if role == "comment":
                self.assertEqual(line[start:start + length], "// add one")
        keywords = [line[s:s + l] for s, l, r in spans if r == "keyword"]
        self.assertIn("set", keywords)
        self.assertNotIn("i", keywords)

    def test_jass_string_and_number(self):
        from w3xmpq.gui.jass_highlight import classify_jass
        line = '    local string s = "hello"'
        spans = classify_jass(line)
        by_role = {}
        for start, length, role in spans:
            by_role.setdefault(role, []).append(line[start:start + length])
        self.assertIn('"hello"', by_role.get("string", []))
        self.assertIn("local", by_role.get("keyword", []))

    def test_real_blp_from_the_game(self):
        path = _real_blp_path()
        if not path:
            self.skipTest("no Warcraft III .blp files found")
        with open(path, "rb") as fh:
            data = fh.read()
        win, view = self._open()
        entry = dict(block=0, name="texture.blp", size=len(data),
                     archived_size=len(data), flags=0, status="ok",
                     sha256=None, data=data)
        view.preview.set_entry(entry)
        self.assertEqual(view.preview.preview_stack.currentIndex(), 1)
        self.assertFalse(view.preview.image_label.pixmap().isNull())
        win.close()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestTabs(unittest.TestCase):
    """Tabs, shared task manager, non-modal jobs, theme, keyboard."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls.map_path = _make_map(cls._tmp.name)
        cls.folders_path = _make_foldered_map(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _wait_all(self, win, timeout_ms=40000):
        # A tab may own several jobs (scan + analysis); `worker` only tracks
        # the scan.  The shared manager is the single source of truth.
        _wait_until(lambda: all(getattr(w, "worker", None) is None
                                for w in win._all_views())
                    and not win.tasks.active_jobs(), timeout_ms)

    def test_two_archives_get_two_tabs(self):
        win = MainWindow()
        win.open_archive(self.map_path)
        win.open_archive(self.folders_path)
        self.assertEqual(win.tabs.count(), 2)
        self.assertEqual(win.view().current_path,
                         os.path.abspath(self.folders_path))
        self._wait_all(win)
        self.assertIsNotNone(win.view())
        self.assertGreater(win.view().table.row_count(), 0)
        win.close()

    def test_tabs_keep_independent_state(self):
        from w3xmpq.gui.archive_view import ArchiveView
        win = MainWindow()
        first = win.open_archive(self.map_path)
        second = win.open_archive(self.folders_path)
        self._wait_all(win)
        self.assertIsInstance(first, ArchiveView)
        self.assertIsInstance(second, ArchiveView)
        self.assertIsNot(first.table, second.table)

        first.filter_edit.setText("tex")
        self.assertEqual(second.filter_edit.text(), "")
        self.assertTrue(first.current_entries)
        self.assertTrue(second.current_entries)

        win.tabs.setCurrentWidget(second)
        self.assertIs(win.view(), second)
        win.tabs.setCurrentWidget(first)
        self.assertIs(win.view(), first)
        win.close()

    def test_shared_task_manager_and_task_bar(self):
        win = MainWindow()
        view = win.open_archive(self.map_path)
        self.assertIs(view.tasks, win.tasks)
        self.assertIs(win.task_bar.manager, win.tasks)
        # Actions are not globally disabled while a job runs.
        self.assertTrue(win.open_act.isEnabled())
        self.assertTrue(win.extract_act.isEnabled())
        self._wait_all(win)
        self.assertFalse(win.tasks.active_jobs())
        win.close()

    def test_reopening_the_same_path_focuses_its_tab(self):
        win = MainWindow()
        first = win.open_archive(self.map_path)
        second = win.open_archive(self.map_path)
        self.assertIs(first, second)
        self.assertEqual(win.tabs.count(), 1)
        self._wait_all(win)
        win.close()

    def test_closing_tabs_returns_to_the_welcome_page(self):
        win = MainWindow()
        self.assertEqual(win.stack.currentIndex(), 0)
        win.open_archive(self.map_path)
        win.open_archive(self.folders_path)
        self.assertEqual(win.stack.currentIndex(), 1)
        self._wait_all(win)
        win._close_tab(0)
        self.assertEqual(win.tabs.count(), 1)
        win._close_tab(0)
        self.assertEqual(win.tabs.count(), 0)
        self.assertIsNone(win.view())
        self.assertEqual(win.stack.currentIndex(), 0)
        win.close()

    def test_closing_a_tab_mid_scan_is_safe(self):
        win = MainWindow()
        win.open_archive(self.map_path)
        win._close_tab(0)          # possibly still scanning
        self.assertEqual(win.tabs.count(), 0)
        win.close()

    def test_batch_tab_is_singleton(self):
        from w3xmpq.gui.batch_view import BatchView
        win = MainWindow()
        first = win.open_batch()
        self.assertIsInstance(first, BatchView)
        self.assertIs(first.tasks, win.tasks)
        second = win.open_batch()
        self.assertIs(first, second)
        self.assertEqual(win.tabs.count(), 1)
        win.close()

    def test_keyboard_map_is_wired(self):
        win = MainWindow()
        shortcuts = {a.shortcut().toString()
                     for a in win.findChildren(type(win.open_act))}
        for key in ("Ctrl+R", "Ctrl+D", "Ctrl+B", "Ctrl+O", "Ctrl+W",
                    "Ctrl+E", "Ctrl+Shift+E", "Ctrl+1", "Ctrl+9"):
            self.assertIn(key, shortcuts)
        win.close()

    def test_dark_theme_applies_and_persists(self):
        from w3xmpq.gui import theme
        win = MainWindow()
        win._set_dark(True)
        self.assertTrue(theme.is_dark())
        self.assertTrue(win.dark_act.isChecked())
        self.assertEqual(win.settings.value("theme"), "dark")
        win._save_session()
        self.assertEqual(win.settings.value("theme"), "dark")
        win._set_dark(False)
        self.assertFalse(theme.is_dark())
        self.assertEqual(win.settings.value("theme"), "light")
        win.close()

    def test_theme_survives_a_preview(self):
        win = MainWindow()
        view = win.open_archive(self.folders_path)
        self._wait_all(win)
        row = next(r for r in range(view.table.row_count())
                   if (view.table.entry_at(r)["name"] or "")
                   .endswith("war3map.j"))
        view.table.selectRow(row)
        before = view.preview.preview.toPlainText()
        win._set_dark(True)
        self.assertEqual(view.preview.preview.toPlainText(), before)
        self.assertIsNotNone(view.preview._highlighter)
        win._set_dark(False)
        win.close()

    def test_diff_tab_coexists_with_archive_tabs(self):
        path_a, path_b = _make_pair(self._tmp.name)
        win = MainWindow()
        diff = win.open_diff(path_a, path_b)
        archive = win.open_archive(path_a)
        self.assertEqual(win.tabs.count(), 2)
        self.assertIs(win.view(), archive)
        win.tabs.setCurrentWidget(diff)
        self.assertIsNone(win.view())
        win.tabs.setCurrentWidget(archive)
        self.assertIsNotNone(win.view())
        self._wait_all(win)
        win.close()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestDiffView(unittest.TestCase):
    """Inline-highlighted diff with hunk navigation."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls.path_a, cls.path_b = _make_pair(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _open(self):
        win = MainWindow()
        view = win.open_diff(self.path_a, self.path_b)
        _wait_until(lambda: view.worker is None, 40000)
        return win, view

    def _visible_rows(self, view):
        return [view._row_at(r) for r in range(view.table.rowCount())
                if not view.table.isRowHidden(r)]

    def test_changes_are_classified_by_name(self):
        win, view = self._open()
        kinds = {r["name"]: r["kind"] for r in view.rows}
        self.assertEqual(kinds["war3map.j"], "changed")
        self.assertEqual(kinds["added.bin"], "only_b")
        self.assertEqual(kinds["removed.bin"], "only_a")
        self.assertEqual(kinds["shared.bin"], "same")
        win.close()

    def test_summary_chips_are_colour_coded(self):
        win, view = self._open()
        label = view.summary_labels["changed"]
        self.assertRegex(label.text(), r"\d+ changed")
        self.assertIn("color", label.styleSheet())
        win.close()

    def test_default_filter_hides_identical_files(self):
        win, view = self._open()
        rows = self._visible_rows(view)
        self.assertTrue(rows)
        self.assertTrue(all(r["kind"] != "same" for r in rows))
        view.group_combo.setCurrentText("identical files")
        rows = self._visible_rows(view)
        self.assertTrue(rows)
        self.assertTrue(all(r["kind"] == "same" for r in rows))
        win.close()

    def test_name_filter_narrows_the_table(self):
        win, view = self._open()
        view.filter_edit.setText("added")
        rows = self._visible_rows(view)
        self.assertEqual([r["name"] for r in rows], ["added.bin"])
        win.close()

    def test_both_versions_are_shown_side_by_side(self):
        win, view = self._open()
        row = next(r for r in range(view.table.rowCount())
                   if view._row_at(r)["name"] == "war3map.j")
        view.table.selectRow(row)
        self.assertIn("endfunction", view.pane_a.toPlainText())
        self.assertNotIn("DoNothing", view.pane_a.toPlainText())
        self.assertIn("DoNothing", view.pane_b.toPlainText())
        self.assertIn("+", view.diff_label.text())
        win.close()

    def test_only_in_a_has_an_empty_right_pane(self):
        win, view = self._open()
        row = next(r for r in range(view.table.rowCount())
                   if view._row_at(r)["kind"] == "only_a")
        view.table.selectRow(row)
        self.assertEqual(view.pane_b.toPlainText(), "(not in B)")
        self.assertNotEqual(view.pane_a.toPlainText(), "")
        win.close()

    def test_first_difference_marks_the_edit(self):
        from w3xmpq.gui.diff_view import first_difference
        self.assertEqual(first_difference("a\nb\nc", "a\nB\nc"), (1, 1))
        self.assertEqual(first_difference("a\nb", "a\nb\nc"), (2, 2))
        self.assertIsNone(first_difference("same", "same"))
        self.assertIsNone(first_difference(None, "a"))

    def test_inline_diff_html_highlights_both_sides(self):
        from w3xmpq.gui import theme
        from w3xmpq.gui.diff_view import build_diff_html
        html_a, html_b, changes = build_diff_html(
            "alpha\nbeta\ngamma", "alpha\nBETA\ngamma", theme.tokens())
        self.assertEqual(len(changes), 1)
        self.assertIn(theme.tokens()["diff_del_bg"], html_a)
        self.assertIn(theme.tokens()["diff_add_bg"], html_b)
        self.assertIn('name="c0"', html_a)

    def test_next_and_previous_change_navigation(self):
        win, view = self._open()
        row = next(r for r in range(view.table.rowCount())
                   if view._row_at(r)["name"] == "war3map.j")
        view.table.selectRow(row)
        self.assertTrue(view._changes)
        self.assertRegex(view.change_label.text(), r"change \d+ / \d+")
        before = view._change_index
        view.next_change()
        self.assertEqual(view._change_index,
                         (before + 1) % len(view._changes))
        view.previous_change()
        self.assertEqual(view._change_index, before)
        self.assertGreater(view.pane_a.textCursor().blockNumber(), -1)
        win.close()


if __name__ == '__main__':
    unittest.main()
