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


def _make_map(tmp):
    """Write a synthetic .w3x built from the standard sample set."""
    path = os.path.join(tmp, 'gui_test.w3x')
    with open(path, 'wb') as f:
        f.write(gen_synth.build_w3x(gen_synth.build_archive(
            gen_synth.sample_file_set())))
    return path


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


if __name__ == '__main__':
    unittest.main()
