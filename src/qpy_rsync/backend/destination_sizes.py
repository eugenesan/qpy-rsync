"""Sizes of objects that only exist on the destination side.

Rsync's deletion records carry placeholder sizes, so the real size of a
destination-only object comes from the destination listing gathered after a
comparison. A deleted directory is reported with its own entry size only; the
size a user cares about is the sum of everything below it.

For large inventories the prefix sums are built once per listing; scanning the
whole metadata dict for every directory would be quadratic.
"""

from __future__ import annotations

from bisect import bisect_left

from qpy_rsync.core.changes import Change, ObjectKind

Metadata = dict[str, tuple[int | None, str | None]]
_MAX_CHAR = chr(0x10FFFF)


class DestinationSizeIndex:
    """Prefix sums over destination paths, for O(log n) subtree sizes."""

    def __init__(self, metadata: Metadata) -> None:
        self._metadata = metadata
        self._keys = sorted(metadata)
        sums = [0]
        for key in self._keys:
            sums.append(sums[-1] + int(metadata[key][0] or 0))
        self._sums = sums

    def own(self, path: str) -> int:
        return int(self._metadata.get(path.rstrip("/"), (None, None))[0] or 0)

    def subtree(self, path: str) -> int:
        clean = path.rstrip("/")
        if not clean:
            return self._sums[-1]
        prefix = clean + "/"
        start = bisect_left(self._keys, prefix)
        end = bisect_left(self._keys, prefix + _MAX_CHAR)
        return self._sums[end] - self._sums[start]


def build_destination_size_index(metadata: Metadata) -> DestinationSizeIndex:
    return DestinationSizeIndex(metadata)


def _index(
    metadata: Metadata | DestinationSizeIndex,
) -> DestinationSizeIndex:
    if isinstance(metadata, DestinationSizeIndex):
        return metadata
    return DestinationSizeIndex(metadata)


def destination_subtree_size(
    path: str, kind: ObjectKind, metadata: Metadata | DestinationSizeIndex
) -> int:
    """The size to show on the destination side of a change."""
    index = _index(metadata)
    own = index.own(path)
    if kind is ObjectKind.DIRECTORY:
        total = index.subtree(path)
        if total:
            return total
    return own


def destination_size(
    change: Change, metadata: Metadata | DestinationSizeIndex
) -> int:
    """The destination size of one change, preferring an explicit value."""
    if change.destination_size is not None:
        return int(change.destination_size)
    return destination_subtree_size(change.path, change.kind, metadata)
