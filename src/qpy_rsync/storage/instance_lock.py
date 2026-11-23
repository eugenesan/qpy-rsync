"""Small PID-based locks for files shared between qpy-rsync instances.

A lock is a plain file containing the owning PID. A stale lock whose PID is
no longer alive is replaced. This is enough to coordinate a few desktop
instances without a daemon or D-Bus service.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterator

from contextlib import contextmanager

__all__ = ["LockBusy", "FileLock", "pid_alive", "lock_pid"]


def lock_pid(path: Path) -> int | None:
    """Return the PID recorded in a profile's lock file, if any."""
    try:
        return int(Path(str(path) + ".lock").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


class LockBusy(RuntimeError):
    """Raised when a live instance already owns the lock."""


def pid_alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class FileLock:
    """Non-daemonic, PID-stamped advisory lock."""

    def __init__(self, path: Path, *, timeout: float = 0.0) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self.owned = False

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".lock")

    def _read_pid(self) -> int | None:
        try:
            return int(self.lock_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None

    def acquire(self, *, timeout: float | None = None) -> None:
        if self.owned:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            try:
                fd = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pid = self._read_pid()
                if pid is None or not pid_alive(pid):
                    try:
                        self.lock_path.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise LockBusy(f"{self.path.name} is locked by PID {pid}")
                time.sleep(0.05)
                continue
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(str(os.getpid()))
            self.owned = True
            return

    def release(self) -> None:
        if not self.owned:
            return
        try:
            if self._read_pid() == os.getpid():
                self.lock_path.unlink(missing_ok=True)
        finally:
            self.owned = False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.release()


@contextmanager
def try_lock(path: Path, *, timeout: float = 2.0) -> Iterator[bool]:
    """Best-effort lock; yields False if another live instance holds it."""
    lock = FileLock(path, timeout=timeout)
    try:
        lock.acquire()
    except LockBusy:
        yield False
        return
    try:
        yield True
    finally:
        lock.release()
