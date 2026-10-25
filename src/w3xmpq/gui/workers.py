# -*- coding: utf-8 -*-
"""Background workers for the w3xmpq GUI.

All heavy lifting (scan/extract/diff/batch/rebuild) runs on QThreads so the
UI stays responsive. Workers emit *finished* (result dict) or *failed* (str).
"""

from PySide6.QtCore import QThread, Signal

from ..core.extract import extract_archive, scan_archive
from ..core.diff import diff_archives
from ..core.batch import batch_extract
from ..core.mpq_write import rebuild_map


class ScanWorker(QThread):
    """scan_archive on a background thread, with progress + cancel."""
    result_ready = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, path, listfile=None, parent=None):
        super().__init__(parent)
        self.path = path
        self.listfile = listfile
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self.result_ready.emit(scan_archive(
                self.path, self.listfile,
                progress=self.progress.emit,
                should_stop=lambda: self._cancel))
        except Exception as e:  # noqa: BLE001 - surface to UI
            self.failed.emit(str(e))


class ExtractWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, path, outdir, pattern=None, listfile=None, parent=None):
        super().__init__(parent)
        self.path = path
        self.outdir = outdir
        self.pattern = pattern
        self.listfile = listfile

    def run(self):
        try:
            self.result_ready.emit(extract_archive(
                self.path, self.outdir, pattern=self.pattern,
                listfile=self.listfile, verbose=False))
        except Exception as e:
            self.failed.emit(str(e))


class DiffWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, path_a, path_b, parent=None):
        super().__init__(parent)
        self.path_a = path_a
        self.path_b = path_b

    def run(self):
        try:
            self.result_ready.emit(diff_archives(self.path_a, self.path_b))
        except Exception as e:
            self.failed.emit(str(e))


class BatchWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, search_dir, outdir, pattern=None, parent=None):
        super().__init__(parent)
        self.search_dir = search_dir
        self.outdir = outdir
        self.pattern = pattern

    def run(self):
        try:
            self.result_ready.emit(batch_extract(self.search_dir, self.outdir,
                                             pattern=self.pattern))
        except Exception as e:
            self.failed.emit(str(e))


class RebuildWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, path, out_path, parent=None):
        super().__init__(parent)
        self.path = path
        self.out_path = out_path

    def run(self):
        try:
            self.result_ready.emit(rebuild_map(self.path, self.out_path))
        except Exception as e:
            self.failed.emit(str(e))
