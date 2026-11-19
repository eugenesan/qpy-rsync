"""Native accumulation of parsed rsync records with a lazy Change sequence.

The Python parser creates a Change object for every line as it streams. With
the optional backend enabled the records are accumulated as flat native
arrays instead, and Change objects are built on demand when the GUI consumes
them. The full field-by-field equivalence is checked by native/check_parse.py.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, overload

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

from .native_backend import NATIVE_ACTIONS, NATIVE_KINDS, native_module
from .rsync_parser import RsyncParseError

_ACTIONS = tuple(
    ChangeAction(value) for value in NATIVE_ACTIONS
)
_KINDS = tuple(ObjectKind(value) for value in NATIVE_KINDS)


class LazyChangeSequence(Sequence[Change]):
    """A read-only Change sequence backed by flat native arrays."""

    def __init__(self, store: NativeRecordStore) -> None:
        self._store = store

    def __len__(self) -> int:
        return len(self._store.paths)

    @overload
    def __getitem__(self, index: int) -> Change: ...

    @overload
    def __getitem__(self, index: slice) -> list[Change]: ...

    def __getitem__(self, index: int | slice) -> Change | list[Change]:
        if isinstance(index, slice):
            return [self._change_at(i) for i in range(*index.indices(len(self)))]
        length = len(self)
        position = index + length if index < 0 else index
        if not 0 <= position < length:
            raise IndexError("change index out of range")
        return self._change_at(position)

    def __iter__(self) -> Iterator[Change]:
        for index in range(len(self)):
            yield self._change_at(index)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, tuple)):
            return list(self) == list(other)
        return NotImplemented

    def __repr__(self) -> str:
        return f"<LazyChangeSequence {len(self)} records>"

    def _change_at(self, index: int) -> Change:
        store = self._store
        return Change(
            path=store.paths[index],
            action=_ACTIONS[store.actions[index]],
            kind=_KINDS[store.kinds[index]],
            itemized_code=store.codes[index],
            size=None if store.size_none[index] else store.sizes[index],
            modified_time=store.times[index] or None,
            link_target=store.link_targets[index] or None,
            reason=store.reasons[index],
        )


class NativeRecordStore:
    """Accumulate parsed records in native arrays, in stream order."""

    def __init__(self, module: Any, *, delete_enabled: bool) -> None:
        self._module = module
        self.delete_enabled = delete_enabled
        self.paths: list[str] = []
        self.actions: list[int] = []
        self.kinds: list[int] = []
        self.sizes: list[int] = []
        self.size_none: list[int] = []
        self.codes: list[str] = []
        self.times: list[str] = []
        self.link_targets: list[str] = []
        self.reasons: list[str] = []
        self.diagnostics: list[str] = []

    def __len__(self) -> int:
        return len(self.paths)

    def append(self, lines: list[str]) -> None:
        if not lines:
            return
        parsed = self._module.parse_records(
            "\n".join(lines) + "\n", self.delete_enabled
        )
        if parsed.error:
            raise RsyncParseError(parsed.error)
        self.paths.extend(parsed.paths)
        self.actions.extend(parsed.actions)
        self.kinds.extend(parsed.kinds)
        self.sizes.extend(parsed.sizes)
        self.size_none.extend(parsed.size_none)
        self.codes.extend(parsed.codes)
        self.times.extend(parsed.times)
        self.link_targets.extend(parsed.link_targets)
        self.reasons.extend(parsed.reasons)
        self.diagnostics.extend(parsed.skipped)

    def changes(self) -> LazyChangeSequence:
        return LazyChangeSequence(self)


def new_store(*, delete_enabled: bool) -> NativeRecordStore | None:
    """Create a store when the native backend is enabled."""
    module = native_module()
    if module is None:
        return None
    return NativeRecordStore(module, delete_enabled=delete_enabled)
