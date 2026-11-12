from __future__ import annotations

import re
from dataclasses import dataclass

# Rsync reports the counter as "to-chk" or, while it walks the trees
# incrementally, as "ir-chk". A dry run may not transfer anything, so the
# "xfr#" part is optional.
_PROGRESS_RE = re.compile(
    r"(?:xfr#(?P<completed>\d+),\s*)?(?:ir-chk|to-chk)=(?P<remaining>\d+)/(?P<total>\d+)"
)
_PERCENT_RE = re.compile(r"(?P<percent>\d{1,3})%")


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
    completed = int(match.group("completed") or 0)
    remaining = int(match.group("remaining"))
    total = int(match.group("total"))
    # The counter covers the scan as well as the transfer, so a dry run
    # shows progress too. Rsync's own percentage counts transferred bytes and
    # stays at zero while it only lists the trees.
    if total > 0:
        percent = round(100 * (total - remaining) / total)
    else:
        denominator = completed + remaining
        percent = round(100 * completed / denominator) if denominator > 0 else 0
    percent = max(0, min(100, percent))
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
