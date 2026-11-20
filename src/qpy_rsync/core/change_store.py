"""The flat storage behind FlatChangeModel.

Both backends expose the same arrays. The Python store keeps real Change
objects and derives the arrays in one pass at set_changes time. The native
store takes the arrays straight from the parsed records and exposes a lazy
Change sequence, so the half-million Change objects are only created for rows
the GUI actually asks for.

The model and the GUI consume only this interface; the flag chooses the store.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, overload

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind

from qpy_rsync.backend.native_backend import NATIVE_ACTIONS, NATIVE_KINDS

_NATIVE_ACTIONS = tuple(ChangeAction(value) for value in NATIVE_ACTIONS)
_NATIVE_KINDS = tuple(ObjectKind(value) for value in NATIVE_KINDS)


@dataclass(slots=True)
class ChangeStore:
    """Parallel arrays for one comparison, plus a Change view."""

    changes: Sequence[Change]
    paths: list[str]
    parents: list[str]
    names: list[str]
    folded: list[str]
    kinds: list[ObjectKind]
    actions: list[ChangeAction]
    sizes: list[int]
    size_none: list[bool]
    backend: str

    def __len__(self) -> int:
        return len(self.changes)

    def __bool__(self) -> bool:
        return len(self) != 0


def build_python_store(changes: Sequence[Change]) -> ChangeStore:
    """Derive the arrays from Change objects (the shipped default)."""
    items = list(changes)
    paths: list[str] = []
    parents: list[str] = []
    names: list[str] = []
    folded: list[str] = []
    for change in items:
        path = str(change.path).rstrip("/")
        if path in {".", "./"}:
            path = ""
        parent, _, name = path.rpartition("/")
        paths.append(path)
        parents.append(parent)
        names.append(name)
        folded.append(name.casefold())
    return ChangeStore(
        changes=items,
        paths=paths,
        parents=parents,
        names=names,
        folded=folded,
        kinds=[change.kind for change in items],
        actions=[change.action for change in items],
        sizes=[int(change.size or 0) for change in items],
        size_none=[change.size is None for change in items],
        backend="python",
    )


class LazyChangeSequence(Sequence[Change]):
    """A cached Change view over native record arrays."""

    def __init__(self, records: Any) -> None:
        self._records = records
        self._cache: dict[int, Change] = {}

    def __len__(self) -> int:
        return len(self._records.paths)

    @overload
    def __getitem__(self, index: int) -> Change: ...

    @overload
    def __getitem__(self, index: slice) -> list[Change]: ...

    def __getitem__(self, index: int | slice) -> Change | list[Change]:
        if isinstance(index, slice):
            return [self._item_at(i) for i in range(*index.indices(len(self)))]
        length = len(self)
        position = index + length if index < 0 else index
        if not 0 <= position < length:
            raise IndexError("change index out of range")
        return self._item_at(position)

    def __iter__(self) -> Iterator[Change]:
        for index in range(len(self)):
            yield self._item_at(index)

    def _item_at(self, index: int) -> Change:
        item = self._cache.get(index)
        if item is None:
            records = self._records
            item = Change(
                path=records.paths[index],
                action=_NATIVE_ACTIONS[records.actions[index]],
                kind=_NATIVE_KINDS[records.kinds[index]],
                itemized_code=records.codes[index],
                size=None if records.size_none[index] else records.sizes[index],
                modified_time=records.times[index] or None,
                link_target=records.link_targets[index] or None,
                reason=records.reasons[index],
            )
            self._cache[index] = item
        return item

    def __repr__(self) -> str:
        return f"<LazyChangeSequence {len(self)} records>"


def build_native_store(records: Any) -> ChangeStore:
    """Use the parsed native arrays directly; no Change objects yet."""
    paths: list[str] = []
    parents: list[str] = []
    names: list[str] = []
    folded: list[str] = []
    for raw in records.paths:
        path = str(raw).rstrip("/")
        if path in {".", "./"}:
            path = ""
        parent, _, name = path.rpartition("/")
        paths.append(path)
        parents.append(parent)
        names.append(name)
        folded.append(name.casefold())
    return ChangeStore(
        changes=LazyChangeSequence(records),
        paths=paths,
        parents=parents,
        names=names,
        folded=folded,
        kinds=[_NATIVE_KINDS[code] for code in records.kinds],
        actions=[_NATIVE_ACTIONS[code] for code in records.actions],
        sizes=list(records.sizes),
        size_none=[bool(value) for value in records.size_none],
        backend="native",
    )
