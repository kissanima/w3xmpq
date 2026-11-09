# -*- coding: utf-8 -*-
"""Background workers for the w3xmpq GUI.

All heavy lifting (scan / extract / diff / batch / rebuild / analysis) runs
on QThreads so the UI stays responsive.  Every worker exposes the same
small contract used by :class:`~w3xmpq.gui.tasks.TaskManager`:

    ``result_ready``  signal(object) — the result
    ``failed``        signal(str)    — an error message
    ``progress``      signal(int, int) — (done, total); total 0 = unknown
    ``cancel()``                    — best-effort cooperative stop

Several jobs may run at once (scan one map while rebuilding another); the
task manager owns the worker references until each thread has really
finished, which is what keeps Qt from tearing down a live QThread.
"""

from PySide6.QtCore import QThread, Signal

from ..core.extract import extract_archive, scan_archive
from ..core.diff import diff_archives
from ..core.batch import batch_extract
from ..core.mpq_write import rebuild_map


class _Worker(QThread):
    """Shared signals + cooperative cancellation for every job."""

    result_ready = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @property
    def cancelled(self):
        return self._cancel

    def _stopping(self):
        return self._cancel

    def _emit(self, value):
        self.result_ready.emit(value)


class ScanWorker(_Worker):
    """scan_archive on a background thread, with progress + cancel."""

    def __init__(self, path, listfile=None, parent=None):
        super().__init__(parent)
        self.path = path
        self.listfile = listfile

    def run(self):
        try:
            self._emit(scan_archive(
                self.path, self.listfile,
                progress=self.progress.emit,
                should_stop=self._stopping))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class ExtractWorker(_Worker):
    """Extract an archive (optionally limited to selected block numbers)."""

    def __init__(self, path, outdir, pattern=None, listfile=None,
                 blocks=None, parent=None):
        super().__init__(parent)
        self.path = path
        self.outdir = outdir
        self.pattern = pattern
        self.listfile = listfile
        self.blocks = blocks

    def run(self):
        try:
            self._emit(extract_archive(
                self.path, self.outdir, pattern=self.pattern,
                listfile=self.listfile, blocks=self.blocks,
                verbose=False, progress=self.progress.emit,
                should_stop=self._stopping))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class DiffWorker(_Worker):
    def __init__(self, path_a, path_b, with_data=False, parent=None):
        super().__init__(parent)
        self.path_a = path_a
        self.path_b = path_b
        # The GUI viewer needs the bytes to show both sides of a change;
        # the CLI only needs the lists.
        self.with_data = with_data

    def run(self):
        try:
            self.progress.emit(0, 2)
            self._emit(diff_archives(
                self.path_a, self.path_b, with_data=self.with_data))
            self.progress.emit(2, 2)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class BatchWorker(_Worker):
    def __init__(self, search_dir, outdir, pattern=None, parent=None):
        super().__init__(parent)
        self.search_dir = search_dir
        self.outdir = outdir
        self.pattern = pattern

    def run(self):
        try:
            self._emit(batch_extract(self.search_dir, self.outdir,
                                     pattern=self.pattern,
                                     progress=self.progress.emit))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class RebuildWorker(_Worker):
    def __init__(self, path, out_path, parent=None):
        super().__init__(parent)
        self.path = path
        self.out_path = out_path

    def run(self):
        try:
            self.progress.emit(0, 0)
            names = rebuild_map(self.path, self.out_path)
            self.progress.emit(1, 1)
            self._emit(dict(out_path=self.out_path, files=names,
                            count=len(names)))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class FnWorker(_Worker):
    """Run an arbitrary core function that takes (path) and returns a dict."""

    def __init__(self, fn, path, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.path = path

    def run(self):
        try:
            self.progress.emit(0, 0)
            self._emit(self._fn(self.path))
            self.progress.emit(1, 1)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))
