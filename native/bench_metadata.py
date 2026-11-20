"""Evaluation for checkpoint 1-A: old vs in-place metadata merge on a real model.

Run with PYTHONPATH=src after build.sh. Reproduces the scale and the full
model/native/signal work behind the "metadata.merge" timing in a real session.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_filter import build_model_large  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from qpy_rsync.backend.destination_sizes import build_destination_size_index  # noqa: E402
from qpy_rsync.gui.flat_change_model import FlatChangeModel  # noqa: E402

COUNT = int(os.environ.get("QPY_GATE_COUNT", "520000"))
META = int(os.environ.get("QPY_METADATA_COUNT", "100000"))


def build_metadata(changes: list[object]) -> dict[str, tuple[int, str]]:
    return {
        str(change.path).rstrip("/"): (int(change.size or 0), "2026/01/01")
        for change in changes[::5][:META]
    }


def old_style(model: FlatChangeModel, new: dict) -> None:
    """The previous merge: two copies, full recompute, full native rebuild."""
    merged = dict(model._destination_metadata or {})
    merged.update(new)
    model._destination_metadata = dict(merged)
    model._destination_index = build_destination_size_index(
        model._destination_metadata
    )
    model._refresh_destination_sizes()
    model._rebuild_native_comparison()
    model.layoutAboutToBeChanged.emit()
    model._apply_filters()
    model.layoutChanged.emit()


def timed(function) -> float:
    started = time.perf_counter()
    function()
    return time.perf_counter() - started


def main() -> None:
    QApplication.instance() or QApplication([])
    os.environ["QPY_RSYNC_NATIVE"] = "1"
    changes = build_model_large(COUNT)
    model = FlatChangeModel()
    model.set_changes(changes)
    new = build_metadata(changes)
    print(f"{COUNT:,} changes, {len(new):,} new metadata entries")

    old = timed(lambda: old_style(model, new))
    fresh = timed(lambda: model.merge_destination_metadata(new))
    print(f"old-style merge {old * 1000:.0f} ms")
    print(f"new merge       {fresh * 1000:.0f} ms")
    print(f"speedup {old / fresh:.2f}x")


if __name__ == "__main__":
    main()
