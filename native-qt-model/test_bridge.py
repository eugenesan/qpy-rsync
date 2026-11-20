"""Phase 2b: can a native Qt widget live inside a PySide6 QApplication?"""

from __future__ import annotations

import os
import sys
import time

if not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
import shiboken6  # noqa: E402

BUILD = os.environ.get("QPY_QT_BUILD_DIR", "/tmp/opencode/qpy-qt-model-build")
DATA = os.environ.get("QPY_QT_DATA", "/tmp/opencode/qpy-model-1m.bin")
sys.path.insert(0, BUILD)

import native_qt_bridge as bridge  # noqa: E402


def main() -> None:
    application = QApplication.instance() or QApplication([])
    started = time.perf_counter()
    ok = bridge.load_binary(DATA)
    print(f"bridge.load_binary ok={ok} in {(time.perf_counter() - started) * 1000:.0f} ms")
    print(f"bridge.row_count={bridge.row_count()}")

    started = time.perf_counter()
    pointer = bridge.create_widget()
    print(f"create_widget in {(time.perf_counter() - started) * 1000:.0f} ms")
    widget = shiboken6.wrapInstance(pointer, QWidget)
    print(f"wrapped widget: {widget!r}")
    assert widget is not None

    started = time.perf_counter()
    widget.show()
    application.processEvents()
    application.processEvents()
    print(f"first paint in {(time.perf_counter() - started) * 1000:.0f} ms")

    for i in range(1000):
        bridge.toggle_decision(i)
    started = time.perf_counter()
    bridge.reset_views()
    application.processEvents()
    print(f"reset after 1000 decisions in {(time.perf_counter() - started) * 1000:.0f} ms")
    started = time.perf_counter()
    diff = bridge.decision_diff()
    print(
        f"decision diff: {len(diff)} entries in "
        f"{(time.perf_counter() - started) * 1000:.1f} ms"
    )
    print("EMBEDDING_OK")


if __name__ == "__main__":
    main()
