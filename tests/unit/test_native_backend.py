"""Parity tests for the optional native comparison backend.

The module is only present on the native experiment branch, so these tests
skip cleanly in a plain Python build. The Python path remains the default.
"""

from __future__ import annotations

import pytest

pytest.importorskip("qpy_rsync._qpy_native")

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind  # noqa: E402
from qpy_rsync.gui.flat_change_model import FlatChangeModel  # noqa: E402


def changes() -> list[Change]:
    return [
        Change("root.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", 10),
        Change("docs", ChangeAction.CREATE, ObjectKind.DIRECTORY, ">d", 0),
        Change("docs/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f", 20),
        Change("docs/sub", ChangeAction.CREATE, ObjectKind.DIRECTORY, ">d", 0),
        Change("docs/sub/c.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", 30),
        Change("gone.txt", ChangeAction.DELETE, ObjectKind.FILE, "*deleting", 0),
    ]


def model_with(monkeypatch: pytest.MonkeyPatch, flag: str | None) -> FlatChangeModel:
    if flag is None:
        monkeypatch.delenv("QPY_RSYNC_NATIVE", raising=False)
    else:
        monkeypatch.setenv("QPY_RSYNC_NATIVE", flag)
    model = FlatChangeModel()
    model.set_changes(changes())
    return model


def signature(model: FlatChangeModel) -> tuple[object, ...]:
    return (
        tuple(model.visible_rows()),
        tuple(sorted(model._visible_change_indices)),
        tuple(tuple(values) for values in model._aggregate_counts),
        dict(model.overview_aggregates()),
        model._directories[""].subtree_items,
    )


def test_python_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    model = model_with(monkeypatch, None)
    assert model._native is None
    assert model._native_comparison is None


def test_native_and_python_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    python = model_with(monkeypatch, "0")
    native = model_with(monkeypatch, "1")
    assert native._native_comparison is not None
    assert signature(python) == signature(native)

    for model in (python, native):
        model.set_visible_actions({ChangeAction.CREATE})
    assert signature(python) == signature(native)


def test_native_folding_keeps_totals(monkeypatch: pytest.MonkeyPatch) -> None:
    python = model_with(monkeypatch, "0")
    native = model_with(monkeypatch, "1")
    for model in (python, native):
        model.set_collapsed("docs", True)
        model.refresh_collapsed({"docs"})
    assert signature(python) == signature(native)
