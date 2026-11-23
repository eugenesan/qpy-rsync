from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import datetime
from time import perf_counter


def enabled() -> bool:
    return os.environ.get("QPY_RSYNC_DEBUG", "").lower() in {"1", "true", "yes", "on"}


_TIMING_OVERRIDE = False


def set_timing_enabled(value: bool) -> None:
    """Enable timing output from the Advanced setting, at runtime."""
    global _TIMING_OVERRIDE
    _TIMING_OVERRIDE = bool(value)


def timing_enabled() -> bool:
    return (
        _TIMING_OVERRIDE
        or enabled()
        or any(
            os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}
            for name in ("QPY_RSYNC_TIMING", "QPY_RSYNC_PROFILE")
        )
    )


_TIMING_SINK = None


def set_timing_sink(sink) -> None:
    """Also deliver timing lines to a callback (e.g. the session log)."""
    global _TIMING_SINK
    _TIMING_SINK = sink


def debug(event: str, **values: object) -> None:
    if not enabled():
        return
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    details = " ".join(f"{key}={value!r}" for key, value in values.items())
    print(f"[qpy-rsync debug] {timestamp} {event} {details}".rstrip(), file=sys.stderr, flush=True)


def debug_timing(event: str, **values: object) -> None:
    """Print a timing line when either debug or timing mode is enabled."""
    if not timing_enabled():
        return
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    details = " ".join(f"{key}={value!r}" for key, value in values.items())
    line = f"[qpy-rsync timing] {timestamp} {event} {details}".rstrip()
    print(line, file=sys.stderr, flush=True)
    if _TIMING_SINK is not None:
        try:
            _TIMING_SINK(line)
        except Exception:
            pass


@contextmanager
def timed(event: str, **values: object):
    """Time a block and report it through :func:`debug_timing`."""
    start = perf_counter()
    try:
        yield
    finally:
        debug_timing(event, ms=round((perf_counter() - start) * 1000, 1), **values)
