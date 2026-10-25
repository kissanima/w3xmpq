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
    from PySide6.QtCore import QEventLoop, QTimer
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


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestGuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls.map_path = _make_map(cls._tmp.name)

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
                   if win.table.item(r, 5).text() == "ok"]
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


if __name__ == '__main__':
    unittest.main()
