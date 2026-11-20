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


def test_lazy_plan_items_read_native_arrays_only_once() -> None:
    """Guard against the O(n^2) that froze the GUI on large comparisons."""
    from qpy_rsync.core.execution_plan import _LazyPlanItems

    class CountingArrays:
        def __init__(self, size: int) -> None:
            self.reads = 0
            self._paths = [f"p{i}" for i in range(size)]
            self._actions = [0] * size
            self._comparison_actions = [0] * size
            self._kinds = [0] * size
            self._included = [1] * size
            self._destructive = [0] * size
            self._sizes = [1] * size
            self._size_none = [0] * size

        def _read(self, name: str):
            self.reads += 1
            return getattr(self, f"_{name}")

        @property
        def paths(self):
            return self._read("paths")

        @property
        def actions(self):
            return self._read("actions")

        @property
        def comparison_actions(self):
            return self._read("comparison_actions")

        @property
        def kinds(self):
            return self._read("kinds")

        @property
        def included(self):
            return self._read("included")

        @property
        def destructive(self):
            return self._read("destructive")

        @property
        def sizes(self):
            return self._read("sizes")

        @property
        def size_none(self):
            return self._read("size_none")

    arrays = CountingArrays(1000)
    items = _LazyPlanItems(arrays)
    assert len(items) == 1000
    assert len(list(items)) == 1000
    assert arrays.reads == 8


def test_stale_native_snapshot_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    from qpy_rsync.gui.flat_change_model import _NativeSnapshot

    model = model_with(monkeypatch, "1")
    before = signature(model)
    empty: list[int] = []
    stale = _NativeSnapshot(
        0, empty, empty, empty, empty, empty, empty, empty, empty, empty,
        empty, empty, empty,
    )
    model._publish_native_snapshot(stale)
    assert signature(model) == before


def test_native_search_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    python = model_with(monkeypatch, "0")
    native = model_with(monkeypatch, "1")
    for text in ("txt", "docs/", "*.txt", "docs/a", "[ac]*.txt", "?"):
        assert python.search_matches(text) == native.search_matches(text)


def test_native_plan_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    from qpy_rsync.core.changes import ChangeDecisions, ChangeDecision
    from qpy_rsync.core.enums import EndpointKind
    from qpy_rsync.core.execution_plan import build_execution_plan
    from qpy_rsync.core.models import Endpoint, SyncProfile

    profile = SyncProfile(
        "plan",
        Endpoint(EndpointKind.LOCAL, "/src/"),
        Endpoint(EndpointKind.LOCAL, "/dst/"),
    )

    def run(flag: str) -> tuple[object, ...]:
        monkeypatch.setenv("QPY_RSYNC_NATIVE", flag)
        decisions = ChangeDecisions()
        decisions.set("docs/a.txt", ChangeDecision.EXCLUDE)
        plan = build_execution_plan(profile, changes(), decisions)
        return (
            tuple(
                (
                    item.path,
                    item.action,
                    item.comparison_action,
                    item.kind,
                    item.included,
                    item.destructive,
                    item.size,
                )
                for item in plan.items
            ),
            plan.summary,
            plan.items_fingerprint,
            plan.decision_signature,
            plan.profile_fingerprint,
        )

    assert run("0") == run("1")


def test_compare_service_parser_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    from qpy_rsync.backend.process_runner import ProcessResult
    from qpy_rsync.services.compare_service import CompareService

    lines = [
        ">f+++++++++|qpy-rsync|10|qpy-rsync|2026/01/01|qpy-rsync|new.txt",
        "*deleting  |qpy-rsync||qpy-rsync||qpy-rsync|old.txt",
        "cL+++++++++|qpy-rsync|5|qpy-rsync|2026/01/01|qpy-rsync|link -> target",
        ">f+++++++++|qpy-rsync|10|qpy-rsync|2026/01/01|qpy-rsync|.",
        "an informational line",
    ]

    def run(flag: str) -> tuple[list[tuple[object, ...]], list[str]]:
        monkeypatch.setenv("QPY_RSYNC_NATIVE", flag)
        service = CompareService()
        finished: list[object] = []
        service.on_finished = finished.append
        for line in lines:
            service._stdout_chunk(line + "\n")
        service._finish(ProcessResult(0, "", ""))
        parsed = finished[0].parsed
        return (
            [
                (
                    change.path,
                    change.action,
                    change.kind,
                    change.size,
                    change.modified_time,
                    change.link_target,
                    change.reason,
                )
                for change in parsed.changes
            ],
            parsed.diagnostics,
        )

    assert run("0") == run("1")
