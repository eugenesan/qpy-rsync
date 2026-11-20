"""Environment-gated timing checks for the native backend.

Not part of `./qpy-rsync-test.sh -q`. Run with PYTHONPATH=src after build.sh.
The gates use ratios to the Python implementation on the same machine rather
than absolute times, so they are stable across CI hardware. Override the item
count with QPY_GATE_COUNT (default 100,000) and a gate with QPY_GATE_*=0 to skip
it.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from qpy_rsync import _qpy_native  # noqa: E402
from qpy_rsync.backend.native_records import NativeRecordStore  # noqa: E402
from qpy_rsync.backend.rsync_parser import parse_record  # noqa: E402
from qpy_rsync.core.changes import ChangeDecisions  # noqa: E402
from qpy_rsync.core.enums import EndpointKind  # noqa: E402
from qpy_rsync.core.execution_plan import build_execution_plan  # noqa: E402
from qpy_rsync.core.models import Endpoint, SyncProfile  # noqa: E402
from qpy_rsync.gui.flat_change_model import FlatChangeModel  # noqa: E402

from bench_filter import build_model_large  # noqa: E402
from bench_metadata import build_metadata, old_style  # noqa: E402

COUNT = int(os.environ.get("QPY_GATE_COUNT", "100000"))


def timed(function):
    started = time.perf_counter()
    function()
    return time.perf_counter() - started


def gate(name: str, python: float, native: float, maximum: float) -> None:
    if os.environ.get(f"QPY_GATE_{name.upper()}", "1") == "0":
        print(f"{name}: skipped")
        return
    ratio = native / python if python else float("inf")
    status = "PASS" if ratio <= maximum else "FAIL"
    print(
        f"{name}: python {python * 1000:.0f} ms, native {native * 1000:.0f} ms, "
        f"ratio {ratio:.2f} <= {maximum:.2f} [{status}]"
    )
    if status == "FAIL":
        raise SystemExit(1)


def main() -> None:
    profile = SyncProfile(
        "gate",
        Endpoint(EndpointKind.LOCAL, "/src/"),
        Endpoint(EndpointKind.LOCAL, "/dst/"),
    )
    changes = build_model_large(COUNT)
    print(f"timing gates on {COUNT:,} changes")

    models: dict[str, FlatChangeModel] = {}
    for flag in ("0", "1"):
        os.environ["QPY_RSYNC_NATIVE"] = flag
        model = FlatChangeModel()
        model.set_changes(changes)
        models[flag] = model

    def filter_python() -> None:
        models["0"]._visible_actions = None
        for _ in range(3):
            models["0"]._apply_filters()

    def filter_native() -> None:
        models["1"]._visible_actions = None
        for _ in range(3):
            models["1"]._apply_filters()

    gate("filter", timed(filter_python), timed(filter_native), 0.7)

    def plan_python() -> None:
        os.environ["QPY_RSYNC_NATIVE"] = "0"
        build_execution_plan(profile, changes, ChangeDecisions())

    def plan_native() -> None:
        os.environ["QPY_RSYNC_NATIVE"] = "1"
        build_execution_plan(profile, changes, ChangeDecisions())

    gate("plan", timed(plan_python), timed(plan_native), 0.7)

    sep = "|qpy-rsync|"
    lines = [
        f"{change.itemized_code}{sep}{change.size}{sep}2026/01/01{sep}{change.path}"
        for change in changes
    ]

    def parse_python() -> None:
        for line in lines:
            parse_record(line, delete_enabled=False)

    def parse_native() -> None:
        store = NativeRecordStore(_qpy_native, delete_enabled=False)
        store.append(lines)

    gate("parse", timed(parse_python), timed(parse_native), 0.8)

    os.environ["QPY_RSYNC_NATIVE"] = "1"
    metadata_model = FlatChangeModel()
    metadata_model.set_changes(changes)
    metadata = build_metadata(changes)

    def metadata_old() -> None:
        old_style(metadata_model, metadata)

    def metadata_new() -> None:
        metadata_model.merge_destination_metadata(metadata)

    gate("metadata", timed(metadata_old), timed(metadata_new), 0.7)


if __name__ == "__main__":
    main()
