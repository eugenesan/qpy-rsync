from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import datetime
from time import perf_counter


def enabled() -> bool:
    return os.environ.get("QPY_RSYNC_DEBUG", "").lower() in {"1", "true", "yes", "on"}


def timing_enabled() -> bool:
    return enabled() or os.environ.get("QPY_RSYNC_TIMING", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
    print(
        f"[qpy-rsync timing] {timestamp} {event} {details}".rstrip(),
        file=sys.stderr,
        flush=True,
    )


@contextmanager
def timed(event: str, **values: object):
    """Time a block and report it through :func:`debug_timing`."""
    start = perf_counter()
    yield
    debug_timing(event, ms=round((perf_counter() - start) * 1000, 1), **values)
