"""Smoke test for the production hybrid wrapper."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind  # noqa: E402
from qpy_rsync.gui.native_hybrid_view import NativeHybridView  # noqa: E402

COUNT = int(os.environ.get("QPY_HYBRID_COUNT", "1000000"))


def main() -> None:
    application = QApplication.instance() or QApplication([])
    changes = [
        Change(
            f"d{i % 30000}/f{i}.txt",
            ChangeAction.CREATE if i % 17 else ChangeAction.DELETE,
            ObjectKind.FILE,
            ">f",
            size=i % 1000,
        )
        for i in range(COUNT)
    ]
    view = NativeHybridView()
    started = time.perf_counter()
    view.set_changes(changes)
    print(f"set_changes {time.perf_counter() - started:.3f} s")
    print(f"row_count {view.row_count()}")
    view.widget.show()
    application.processEvents()
    application.processEvents()
    for i in range(1000):
        view.toggle_decision(i)
    started = time.perf_counter()
    diff = view.decision_diff()
    print(f"decision_diff {len(diff)} entries in {(time.perf_counter() - started) * 1000:.1f} ms")
    print("HYBRID_OK")


if __name__ == "__main__":
    main()
