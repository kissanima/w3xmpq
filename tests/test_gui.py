#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI smoke tests (offscreen). Skipped entirely when PySide6 is missing
so non-GUI environments (and the CI matrix without Qt) still pass."""

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
    from PySide6.QtCore import QEventLoop, QTimer, Qt
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from w3xmpq.gui.main_window import MainWindow


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

    def _wait(self, win, attr="worker", timeout_ms=30000):
        """Spin the event loop until win.<attr> is None (task finished)."""
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(50)
        poll.timeout.connect(
            lambda: getattr(win, attr) is None and loop.quit())
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(timeout_ms)
        loop.exec()
        poll.stop()
        deadline.stop()

    def test_open_scan_preview(self):
        win = MainWindow()
        win.open_archive(self.map_path)
        self._wait(win)
        self.assertIsNone(win.worker)
        self.assertIsNotNone(win.current_entries)
        self.assertGreater(win.table.rowCount(), 0)
        ok_rows = [r for r in range(win.table.rowCount())
                   if win.table.item(r, 6).text() == "ok"]
        self.assertGreater(len(ok_rows), 0)
        # selecting a row must not crash the preview
        win.table.selectRow(ok_rows[0])
        self.assertTrue(win.banner.text().strip())
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

    def test_extract_selected_pattern(self):
        """Zip-style single-file extraction: selecting a row and running the
        ExtractWorker with that row's escaped name must extract exactly it."""
        import re
        from w3xmpq.gui.workers import ExtractWorker
        win = MainWindow()
        win.open_archive(self.map_path)
        self._wait(win)
        ok_rows = [r for r in range(win.table.rowCount())
                   if win.table.item(r, 6).text() == "ok"]
        win.table.selectRow(ok_rows[0])
        names = win._selected_names()
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0])

        outdir = os.path.join(self._tmp.name, 'sel')
        done = {}
        loop = QEventLoop()
        w = ExtractWorker(self.map_path, outdir,
                          pattern="|".join(re.escape(n) for n in names))

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
        self.assertTrue(os.path.isfile(
            os.path.join(outdir, names[0].replace('\\', os.sep))))
        win.close()

    def test_folder_tree_and_filter(self):
        """7-zip layout: folder tree builds from paths and filters the table."""
        win = MainWindow()
        win.open_archive(self.folders_path)
        self._wait(win)
        tree = win.folders
        root = tree.topLevelItem(0)
        self.assertEqual(root.text(0), "(all files)")
        top = {root.child(i).text(0) for i in range(root.childCount())}
        self.assertIn("Scripts/", top)
        self.assertIn("textures/", top)
        tex = [root.child(i) for i in range(root.childCount())
               if root.child(i).text(0) == "textures/"][0]
        self.assertEqual(tex.child(0).text(0), "ui/")

        total = win.table.rowCount()

        def visible():
            return [r for r in range(win.table.rowCount())
                    if not win.table.isRowHidden(r)]

        win.apply_folder_filter("textures")
        vis = visible()
        self.assertGreaterEqual(len(vis), 2)
        for r in vis:
            e = win.table.entry_at(r)
            self.assertTrue((e["name"] or "").replace("/", "\\")
                            .startswith("textures\\"), e["name"])
        win.apply_folder_filter("textures\\ui")
        self.assertEqual(len(visible()), 1)
        win.apply_folder_filter(None)
        self.assertEqual(len(visible()), total)
        win.close()

    def test_multi_select_and_live_filter(self):
        win = MainWindow()
        win.open_archive(self.folders_path)
        self._wait(win)

        # Extended selection: several rows can be picked at once.
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        from PySide6.QtWidgets import QTableWidget
        self.assertEqual(win.table.selectionMode(),
                         QTableWidget.ExtendedSelection)
        win.table.clearSelection()
        model = win.table.selectionModel()
        for r in (0, 1):
            model.select(
                win.table.model().index(r, 0),
                QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.assertGreaterEqual(len(win.table.selected_entries()), 2)
        self.assertGreaterEqual(len(win._selected_names()), 2)

        # Live text filter narrows the table down.
        win.filter_edit.setText("tex")
        visible = [r for r in range(win.table.rowCount())
                   if not win.table.isRowHidden(r)]
        self.assertTrue(visible)
        for r in visible:
            name = (win.table.entry_at(r)["name"] or "").lower()
            self.assertIn("tex", name)
        win.filter_edit.setText("")
        self.assertFalse(any(win.table.isRowHidden(r)
                             for r in range(win.table.rowCount())))
        win.close()

    def test_sorting_keeps_entries_in_sync(self):
        """Sorting by size must not desynchronise rows from their data."""
        win = MainWindow()
        win.open_archive(self.folders_path)
        self._wait(win)
        win.table.sortItems(2, Qt.DescendingOrder)   # Size column
        sizes = [win.table.entry_at(r)["size"]
                 for r in range(win.table.rowCount())]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        win.table.sortItems(1, Qt.AscendingOrder)    # Name column
        names = [(win.table.entry_at(r)["name"] or "").lower()
                 for r in range(win.table.rowCount())]
        self.assertEqual(names, sorted(names))
        win.close()

    def test_show_filter_combo(self):
        win = MainWindow()
        win.open_archive(self.folders_path)
        self._wait(win)

        def visible_names():
            out = []
            for r in range(win.table.rowCount()):
                if not win.table.isRowHidden(r):
                    e = win.table.entry_at(r)
                    out.append(e["name"] or "")
            return out

        win.show_combo.setCurrentText("named only")
        names = visible_names()
        self.assertTrue(names)
        self.assertTrue(all(n for n in names))
        win.show_combo.setCurrentText("all files")
        self.assertEqual(len(visible_names()), win.table.rowCount())
        win.close()

    def test_find_in_preview(self):
        win = MainWindow()
        win.open_archive(self.folders_path)
        self._wait(win)
        # pick a text file (war3map.j) and search inside it
        row = None
        for r in range(win.table.rowCount()):
            e = win.table.entry_at(r)
            if e and (e["name"] or "").endswith("war3map.j"):
                row = r
                break
        self.assertIsNotNone(row)
        win.table.selectRow(row)
        self.assertIn("function", win.preview.toPlainText())
        win._toggle_find()
        win.find_edit.setText("function main")
        win._find_next()
        self.assertIn("found", win.find_count.text())
        win.find_edit.setText("zzz-not-there")
        self.assertIn("not found", win.find_count.text())
        win._hide_find()
        self.assertFalse(win._find_row_widget.isVisible())
        win.close()

    def test_export_table_and_save_entry(self):
        import json
        win = MainWindow()
        win.open_archive(self.folders_path)
        self._wait(win)
        out = os.path.join(self._tmp.name, "table.json")
        count = win._write_table(out)
        self.assertEqual(count, len(win.current_entries))
        with open(out, encoding="utf-8") as f:
            rows = json.load(f)
        self.assertEqual(len(rows), count)
        self.assertIn("name_source", rows[0])

        csv_path = os.path.join(self._tmp.name, "table.csv")
        win._write_table(csv_path)
        with open(csv_path, encoding="utf-8") as f:
            head = f.readline()
        self.assertIn("sha256", head)

        # save one entry straight from the preview
        e = next(x for x in win.current_entries if x["status"] == "ok")
        target = os.path.join(self._tmp.name, "one.bin")
        n = win._save_entry_to(e, target)
        self.assertEqual(n, len(e["data"]))
        with open(target, "rb") as f:
            self.assertEqual(f.read(), e["data"])
        win.close()

    def test_session_settings_roundtrip(self):
        win = MainWindow()
        win.settings.setValue("last_dir", self._tmp.name)
        win.show_combo.setCurrentText("named only")
        win._save_session()
        self.assertEqual(win.settings.value("show_filter", 0, type=int), 1)
        win.close()

    def test_source_column_reports_recovery_method(self):
        win = MainWindow()
        win.open_archive(self.folders_path)
        self._wait(win)
        srcs = {win.table.item(r, 5).text() for r in range(win.table.rowCount())}
        self.assertTrue(srcs)
        for s in srcs:
            name_src, _, key_src = s.partition("/")
            self.assertIn(name_src, ("known", "listfile", "external",
                                     "guess", "unknown"))
            self.assertIn(key_src, ("plain", "crack", "named"))
        win.close()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestGuiPreview(unittest.TestCase):
    """Image preview and syntax highlighting."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls.image_map = _make_image_map(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _wait(self, win, timeout_ms=30000):
        loop = QEventLoop()
        poll = QTimer()
        poll.timeout.connect(lambda: win.worker is None and loop.quit())
        poll.start(50)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()

    def _row_for(self, win, suffix):
        for r in range(win.table.rowCount()):
            e = win.table.entry_at(r)
            if e and (e.get("name") or "").endswith(suffix):
                return r
        return None

    def test_blp_shows_an_image(self):
        win = MainWindow()
        win.open_archive(self.image_map)
        self._wait(win)
        row = self._row_for(win, ".blp")
        self.assertIsNotNone(row, "no .blp entry in the table")
        win.table.selectRow(row)
        self.assertEqual(win.preview_stack.currentIndex(), 1,
                         "the preview should switch to the image page")
        pixmap = win.image_label.pixmap()
        self.assertFalse(pixmap.isNull())
        self.assertGreater(pixmap.width(), 0)
        win.close()

    def test_text_file_switches_back_to_text(self):
        win = MainWindow()
        win.open_archive(self.image_map)
        self._wait(win)
        win.table.selectRow(self._row_for(win, ".blp"))
        self.assertEqual(win.preview_stack.currentIndex(), 1)
        win.table.selectRow(self._row_for(win, ".j"))
        self.assertEqual(win.preview_stack.currentIndex(), 0)
        win.close()

    def test_jass_is_highlighted(self):
        win = MainWindow()
        win.open_archive(self.image_map)
        self._wait(win)
        win.table.selectRow(self._row_for(win, ".j"))
        self.assertIsNotNone(win._highlighter,
                             "JASS files should get a syntax highlighter")
        win.close()

    def test_jass_classification(self):
        from w3xmpq.gui.jass_highlight import classify_jass
        line = "    set i = i + 1   // add one"
        spans = classify_jass(line)
        roles = {role for _s, _l, role in spans}
        self.assertIn("keyword", roles)
        self.assertIn("comment", roles)
        # The comment must win over the words inside it.
        for start, length, role in spans:
            if role == "comment":
                self.assertEqual(line[start:start + length],
                                 "// add one")
        # "set" is a keyword, "i" is not.
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
        win = MainWindow()
        win.open_archive(self.image_map)
        self._wait(win)
        entry = dict(block=0, name="texture.blp", size=len(data),
                     archived_size=len(data), flags=0, status="ok",
                     sha256=None, data=data)
        win.current_entries = [entry]
        win.table.load_entries([entry])
        win.table.selectRow(0)
        self.assertEqual(win.preview_stack.currentIndex(), 1)
        self.assertFalse(win.image_label.pixmap().isNull())
        win.close()


if __name__ == '__main__':
    unittest.main()
