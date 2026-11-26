from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import datetime
from time import perf_counter

_TRUE = {"1", "true", "yes", "on"}

# Qt components started by a remote shell or an SSH command can emit these on
# stderr even though the application under test has nothing to do with Qt.
# They are harmless and obscure real rsync/SSH failures in the journal.
BENIGN_QT_MESSAGES = (
    "Cannot create platform OpenGL context",
    "fallback to QtQuick software backend",
    "Socket not connected",
    "QLocalSocket::PeerClosedError",
    "Connection::send() called with connection not inited",
)


def clean_qt_noise(text: str) -> str:
    """Drop known-benign Qt lines from captured process output."""
    return "\n".join(
        line
        for line in str(text).splitlines()
        if not any(pattern in line for pattern in BENIGN_QT_MESSAGES)
    )


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in _TRUE


_DEBUG_OVERRIDE = False


def set_debug_enabled(value: bool) -> None:
    """Enable debug diagnostics from the Advanced setting, at runtime."""
    global _DEBUG_OVERRIDE
    _DEBUG_OVERRIDE = bool(value)


def enabled() -> bool:
    return _DEBUG_OVERRIDE or _env_flag("QPY_RSYNC_DEBUG")


_TIMING_OVERRIDE = False


def set_timing_enabled(value: bool) -> None:
    """Enable timing output from the Advanced setting, at runtime."""
    global _TIMING_OVERRIDE
    _TIMING_OVERRIDE = bool(value)


def timing_enabled() -> bool:
    return (
        _TIMING_OVERRIDE
        or enabled()
        or any(_env_flag(name) for name in ("QPY_RSYNC_TIMING", "QPY_RSYNC_PROFILE"))
    )


_SINK = None

# Opt-in, low-overhead phase log for interactive performance reports. When
# unset, perf_log() returns before doing any work and the normal UI path is
# unchanged. Set QPY_RSYNC_PERF_LOG=/path/to/file before starting the app to
# get one line per timed phase: ISO timestamp, phase name, elapsed ms.
PERF_LOG_ENV = "QPY_RSYNC_PERF_LOG"


def set_timing_sink(sink) -> None:
    """Also deliver diagnostics to a callback (e.g. the session log)."""
    global _SINK
    _SINK = sink


def perf_log(event: str, elapsed_ms: float, **values: object) -> None:
    """Append one phase line to QPY_RSYNC_PERF_LOG when that variable is set."""
    path = os.environ.get(PERF_LOG_ENV, "")
    if not path:
        return
    try:
        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        details = " ".join(f"{key}={value}" for key, value in values.items())
        line = f"{timestamp} {event} {elapsed_ms:.1f}ms"
        if details:
            line += " " + details
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        # A broken or unwritable log must never affect the application.
        pass


def _emit(line: str) -> None:
    print(line, file=sys.stderr, flush=True)
    if _SINK is not None:
        try:
            _SINK(line)
        except Exception:
            pass


def debug(event: str, **values: object) -> None:
    if not enabled():
        return
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    details = " ".join(f"{key}={value!r}" for key, value in values.items())
    _emit(f"[qpy-rsync debug] {timestamp} {event} {details}".rstrip())


def debug_timing(event: str, **values: object) -> None:
    """Print a timing line when either debug or timing mode is enabled."""
    if not timing_enabled():
        return
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    details = " ".join(f"{key}={value!r}" for key, value in values.items())
    _emit(f"[qpy-rsync timing] {timestamp} {event} {details}".rstrip())


@contextmanager
def timed(event: str, **values: object):
    """Time a block and report it through :func:`debug_timing`.

    Independently of the verbose timing switches, an opt-in perf log records
    the same phases when ``QPY_RSYNC_PERF_LOG`` points at a file.
    """
    start = perf_counter()
    try:
        yield
    finally:
        elapsed_ms = round((perf_counter() - start) * 1000, 1)
        debug_timing(event, ms=elapsed_ms, **values)
        perf_log(event, elapsed_ms, **values)
