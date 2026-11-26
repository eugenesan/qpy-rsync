"""Opt-in interactive performance logging."""

from __future__ import annotations

from pathlib import Path

import pytest

from qpy_rsync.backend import diagnostics


def test_perf_log_is_disabled_by_default(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "disabled.log"
    monkeypatch.delenv(diagnostics.PERF_LOG_ENV, raising=False)
    with diagnostics.timed("test.disabled"):
        pass
    assert not target.exists()


def test_perf_log_writes_one_line_per_phase(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "perf.log"
    monkeypatch.setenv(diagnostics.PERF_LOG_ENV, str(target))
    monkeypatch.delenv("QPY_RSYNC_TIMING", raising=False)
    monkeypatch.delenv("QPY_RSYNC_PROFILE", raising=False)
    diagnostics.set_timing_enabled(False)
    with diagnostics.timed("view.toggle_excluded", paths=1):
        pass
    with diagnostics.timed("ui.sort", column=0):
        pass
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = lines[0].split()
    assert first[1] == "view.toggle_excluded"
    assert first[2].endswith("ms")
    assert "paths=1" in lines[0]
    assert lines[1].split()[1] == "ui.sort"
    assert "column=0" in lines[1]


def test_timing_setting_routes_phases_to_the_shared_sink(monkeypatch) -> None:
    received: list[str] = []
    monkeypatch.delenv(diagnostics.PERF_LOG_ENV, raising=False)
    monkeypatch.delenv("QPY_RSYNC_TIMING", raising=False)
    monkeypatch.delenv("QPY_RSYNC_PROFILE", raising=False)
    monkeypatch.delenv("QPY_RSYNC_DEBUG", raising=False)
    diagnostics.set_timing_sink(received.append)

    diagnostics.set_timing_enabled(False)
    with diagnostics.timed("test.disabled_phase"):
        pass
    diagnostics.native_timing("native.overview_update", 12.3)
    assert received == []

    # The existing settings flag is sufficient: no env var or extra file.
    diagnostics.set_timing_enabled(True)
    with diagnostics.timed("test.enabled_phase"):
        pass
    diagnostics.native_timing("native.overview_update", 12.3)
    assert any("test.enabled_phase" in line for line in received)
    assert any(
        "native.overview_update" in line and "ms=12.3" in line
        for line in received
    )
    diagnostics.set_timing_enabled(False)
    diagnostics.set_timing_sink(None)


def test_perf_log_ignores_unwritable_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(diagnostics.PERF_LOG_ENV, str(tmp_path / "missing" / "perf.log"))
    with diagnostics.timed("test.unwritable"):
        pass
