from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import datetime
from time import perf_counter

_TRUE = {"1", "true", "yes", "on"}


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


def set_timing_sink(sink) -> None:
    """Also deliver diagnostics to a callback (e.g. the session log)."""
    global _SINK
    _SINK = sink


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
    """Time a block and report it through :func:`debug_timing`."""
    start = perf_counter()
    try:
        yield
    finally:
        debug_timing(event, ms=round((perf_counter() - start) * 1000, 1), **values)
