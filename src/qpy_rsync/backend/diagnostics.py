from __future__ import annotations

import os
import sys
from datetime import datetime


def enabled() -> bool:
    return os.environ.get("QPY_RSYNC_DEBUG", "").lower() in {"1", "true", "yes", "on"}


def debug(event: str, **values: object) -> None:
    if not enabled():
        return
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    details = " ".join(f"{key}={value!r}" for key, value in values.items())
    print(f"[qpy-rsync debug] {timestamp} {event} {details}".rstrip(), file=sys.stderr, flush=True)
