from __future__ import annotations

import re
from dataclasses import dataclass

_PROGRESS_RE = re.compile(r"\(xfr#(?P<completed>\d+),\s*to-chk=(?P<remaining>\d+)/(?P<total>\d+)\)")


@dataclass(slots=True, frozen=True)
class SyncProgress:
    files_completed: int
    files_remaining: int
    files_total: int
    percent: int


def parse_sync_progress(text: str) -> SyncProgress | None:
    match = _PROGRESS_RE.search(text)
    if match is None:
        return None
    completed = int(match.group("completed"))
    remaining = int(match.group("remaining"))
    total = int(match.group("total"))
    denominator = completed + remaining
    if denominator <= 0:
        percent = 0
    else:
        percent = round(100 * completed / denominator)
    if total > 0 and percent > 100:
        percent = 100
    return SyncProgress(
        files_completed=completed,
        files_remaining=remaining,
        files_total=total,
        percent=percent,
    )


# Compatibility aliases for alternative test/import names.
parse_rsync_progress = parse_sync_progress
parse_progress = parse_sync_progress
RsyncProgress = SyncProgress
ProgressInfo = SyncProgress