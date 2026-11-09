# -*- coding: utf-8 -*-
"""Non-modal background jobs.

The old UI kept a single ``self.worker``: starting anything while a task
ran popped "A task is running", and *every* action was disabled.  Here a
:class:`TaskManager` owns any number of QThread workers.  Each gets a row
in the :class:`TaskBar` (progress + cancel), the window stays usable, and
finished jobs stay listed in the analysis drawer's Tasks tab.

Worker lifetime matters: a QThread destroyed while ``run()`` is still on
the stack crashes Qt.  The manager holds each worker until its ``finished``
signal arrives, and only then drops the reference.
"""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QSizePolicy, QVBoxLayout)

from . import theme

RUNNING, DONE, FAILED, CANCELLED = "running", "done", "failed", "cancelled"


class Job:
    """A small value object; signals carry it to the task bar / drawer."""

    _next = 0

    def __init__(self, label, worker, on_done=None, on_failed=None,
                 owner=None):
        Job._next += 1
        self.id = Job._next
        self.label = label
        self.worker = worker
        self.owner = owner
        self.on_done = on_done
        self.on_failed = on_failed
        self.state = RUNNING
        self.message = ""
        self.done = 0
        self.total = 0

    @property
    def active(self):
        return self.state == RUNNING


class TaskManager(QObject):
    """Owns worker threads and broadcasts job state."""

    job_added = Signal(object)
    job_changed = Signal(object)
    result_ready = Signal(object, object)      # (job, result)
    job_failed = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs = []

    def submit(self, label, worker, on_done=None, on_failed=None,
               owner=None):
        """Start a job; optional per-job callbacks run on the UI thread."""
        job = Job(label, worker, on_done=on_done, on_failed=on_failed,
                  owner=owner)
        self.jobs.append(job)
        worker.result_ready.connect(
            lambda result, j=job: self._done(j, result))
        worker.failed.connect(
            lambda err, j=job: self._failed(j, err))
        worker.progress.connect(
            lambda done, total, j=job: self._progress(j, done, total))
        worker.finished.connect(
            lambda w=worker, j=job: self._release(j, w))
        self.job_added.emit(job)
        self.job_changed.emit(job)
        worker.start()
        return job

    def _done(self, job, result):
        if job.state != RUNNING:
            return
        job.state = CANCELLED if job.worker.cancelled else DONE
        job.message = "finished"
        self.result_ready.emit(job, result)
        self.job_changed.emit(job)
        if job.on_done is not None:
            job.on_done(result)

    def _failed(self, job, err):
        if job.state != RUNNING:
            return
        job.state = FAILED
        job.message = err
        self.job_failed.emit(job, err)
        self.job_changed.emit(job)
        if job.on_failed is not None:
            job.on_failed(err)

    def _progress(self, job, done, total):
        job.done, job.total = done, total
        self.job_changed.emit(job)

    def _release(self, job, worker):
        """QThread.finished == run() returned; safe to drop the reference."""
        if job.worker is worker:
            job.worker = None
        self.job_changed.emit(job)

    def cancel(self, job):
        if job.active and job.worker is not None:
            job.worker.cancel()
            job.message = "cancelling\u2026"
            self.job_changed.emit(job)

    def cancel_all(self):
        for job in self.jobs:
            self.cancel(job)

    def cancel_owner(self, owner):
        for job in self.jobs:
            if job.owner == owner:
                self.cancel(job)

    def jobs_for(self, owner):
        return [j for j in self.jobs if j.owner == owner]

    def active_jobs(self):
        return [j for j in self.jobs if j.active]

    def shutdown(self):
        self.cancel_all()
        for job in list(self.jobs):
            w = job.worker
            if w is not None and w.isRunning():
                w.wait(3000)


class TaskBar(QFrame):
    """Compact per-job progress rows for the status bar."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._rows = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(8)
        self.label = QLabel("")
        theme.set_role(self.label, "dim")
        layout.addWidget(self.label)
        self.rows_layout = QHBoxLayout()
        self.rows_layout.setSpacing(8)
        layout.addLayout(self.rows_layout, 1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.hide()
        manager.job_added.connect(self._add_row)
        manager.job_changed.connect(self._update_row)

    def _add_row(self, job):
        row = QFrame()
        theme.set_role(row, "strip")
        box = QHBoxLayout(row)
        box.setContentsMargins(7, 2, 7, 2)
        box.setSpacing(6)
        name = QLabel(job.label)
        name.setMaximumWidth(150)
        name.setToolTip(job.label)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedWidth(90)
        bar.setFixedHeight(9)
        cancel = QPushButton("\u00d7")
        cancel.setFixedWidth(22)
        cancel.setToolTip("Cancel this task")
        cancel.clicked.connect(lambda: self.manager.cancel(job))
        box.addWidget(name)
        box.addWidget(bar)
        box.addWidget(cancel)
        self.rows_layout.addWidget(row)
        self._rows[job.id] = (row, name, bar, cancel)
        self._update_row(job)

    def _update_row(self, job):
        item = self._rows.get(job.id)
        if item is None:
            return
        row, name, bar, cancel = item
        if job.total and job.total > 0:
            bar.setRange(0, job.total)
            bar.setValue(min(job.done, job.total))
        else:
            bar.setRange(0, 0)
        cancel.setEnabled(job.active)
        if not job.active:
            self.rows_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
            del self._rows[job.id]
        active = self.manager.active_jobs()
        self.label.setText("%d running" % len(active) if active else "")
        self.setVisible(bool(active) or bool(self._rows))

    def apply_theme(self):
        for row, name, bar, cancel in self._rows.values():
            theme.repolish(row)
