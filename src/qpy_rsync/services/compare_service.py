from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from qpy_rsync.backend.process_runner import ProcessResult, QtProcessRunner
from qpy_rsync.backend.rsync_command import build_compare_spec
from qpy_rsync.backend.rsync_parser import ParseResult, parse_output
from qpy_rsync.core.models import SyncProfile


@dataclass(slots=True, frozen=True)
class CompareResult:
    parsed: ParseResult
    stderr: str
    exit_code: int


class CompareService:
    def __init__(self, parent: object | None = None) -> None:
        self._runner = QtProcessRunner(parent)  # type: ignore[arg-type]
        self.on_started: Callable[[], None] = lambda: None
        self.on_finished: Callable[[CompareResult], None] = lambda _result: None
        self.on_error: Callable[[str], None] = lambda _message: None
        self.on_log: Callable[[str], None] = lambda _message: None
        self._runner.on_stdout = lambda _chunk: None
        self._runner.on_stderr = self.on_log
        self._runner.on_finished = self._finish
        self._runner.on_error = self.on_error

    def compare(self, profile: SyncProfile) -> None:
        self.on_started()
        self._runner.start(build_compare_spec(profile))

    def cancel(self) -> None:
        self._runner.cancel()

    def _finish(self, process: ProcessResult) -> None:
        if process.exit_code != 0:
            self.on_error(f"rsync exited with status {process.exit_code}: {process.stderr.strip()}")
            return
        try:
            parsed = parse_output(process.stdout)
        except ValueError as exc:
            self.on_error(f"Could not parse rsync output: {exc}")
            return
        self.on_finished(CompareResult(parsed, process.stderr, process.exit_code))
