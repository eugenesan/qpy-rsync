"""Sizes of objects that only exist on the destination side.

Rsync's deletion records carry placeholder sizes, so the real size of a
destination-only object comes from the destination listing gathered after a
comparison. A deleted directory is reported with its own entry size only; the
size a user cares about is the sum of everything below it.
"""

from __future__ import annotations

from qpy_rsync.core.changes import Change, ObjectKind

Metadata = dict[str, tuple[int | None, str | None]]


def destination_subtree_size(
    path: str, kind: ObjectKind, metadata: Metadata
) -> int:
    """The size to show on the destination side of a change."""
    clean = path.rstrip("/")
    own = metadata.get(clean, (None, None))[0]
    if kind is ObjectKind.DIRECTORY:
        prefix = clean + "/" if clean else ""
        total = sum(
            int(size or 0)
            for key, (size, _time) in metadata.items()
            if prefix and key.startswith(prefix)
        )
        if total:
            return total
    return int(own or 0)


def destination_size(change: Change, metadata: Metadata) -> int:
    """The destination size of one change, preferring an explicit value."""
    if change.destination_size is not None:
        return int(change.destination_size)
    return destination_subtree_size(change.path, change.kind, metadata)
