from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from qpy_rsync.backend.inventory import unchanged_changes
from qpy_rsync.core.changes import Change
from qpy_rsync.core.models import SyncProfile


class _WorkerSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)


class _InventoryTask(QRunnable):
    def __init__(
        self,
        token: int,
        profile: SyncProfile,
        changed: list[Change],
        signals: _WorkerSignals,
        gather: Callable[[SyncProfile, list[Change]], list[Change]],
    ) -> None:
        super().__init__()
        self._token = token
        self._profile = profile
        self._changed = changed
        self._signals = signals
        self._gather = gather

    def run(self) -> None:
        try:
            result = self._gather(self._profile, self._changed)
        except Exception as exc:  # noqa: BLE001 - worker boundary
            self._signals.failed.emit(self._token, str(exc))
            return
        self._signals.finished.emit(self._token, result)


class InventoryService(QObject):
    """Gather unchanged objects off the GUI thread.

    Inventory can inspect tens of thousands of remote or local paths. Running
    it in ``QThreadPool`` keeps the window responsive while rsync lists both
    trees. Each request carries a token so an outdated result can be ignored.
    """

    finished = Signal(int, object)
    failed = Signal(int, str)

    def __init__(
        self,
        parent: object | None = None,
        *,
        gather: Callable[[SyncProfile, list[Change]], list[Change]] | None = None,
        pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._gather = gather or unchanged_changes
        self._pool = pool or QThreadPool.globalInstance()
        self._token = 0
        self._signals = _WorkerSignals(self)
        self._signals.finished.connect(self._deliver_finished)
        self._signals.failed.connect(self._deliver_failed)
        # Keep running tasks alive even if the caller drops its reference.
        self._tasks: dict[int, _InventoryTask] = {}

    def gather(self, profile: SyncProfile, changed: list[Change]) -> int:
        self._token += 1
        token = self._token
        task = _InventoryTask(token, profile, list(changed), self._signals, self._gather)
        self._tasks[token] = task
        self._pool.start(task)
        return token

    def _deliver_finished(self, token: int, result: object) -> None:
        self._tasks.pop(token, None)
        self.finished.emit(token, result)

    def _deliver_failed(self, token: int, message: str) -> None:
        self._tasks.pop(token, None)
        self.failed.emit(token, message)

    def cancel(self) -> None:
        """Invalidate pending results without killing an active rsync process."""
        self._token += 1
