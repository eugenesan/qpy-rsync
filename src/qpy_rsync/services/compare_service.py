from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from qpy_rsync.backend.diagnostics import debug
from qpy_rsync.backend.process_runner import ProcessResult, QtProcessRunner
from qpy_rsync.backend.rsync_command import build_compare_spec
from qpy_rsync.backend.rsync_parser import ParseResult, parse_output
from qpy_rsync.backend.sync_progress import SyncProgress, parse_sync_progress
from qpy_rsync.core.models import SyncProfile


@dataclass(slots=True, frozen=True)
class CompareResult:
    parsed: ParseResult
    stderr: str
    exit_code: int


class CompareService:
    def __init__(self, parent: object | None = None) -> None:
        self._delete_enabled = False
        self._cancelled = False
        self._buffer = ""
        self._runner = QtProcessRunner(parent)  # type: ignore[arg-type]
        self.on_started: Callable[[], None] = lambda: None
        self.on_finished: Callable[[CompareResult], None] = lambda _result: None
        self.on_error: Callable[[str], None] = lambda _message: None
        self.on_cancelled: Callable[[], None] = lambda: None
        self.on_log: Callable[[str], None] = lambda _message: None
        self.on_progress: Callable[[SyncProgress], None] = lambda _progress: None
        # Indirection is intentional: GUI callbacks are assigned after this service is constructed.
        self._runner.on_stdout = self._stdout_chunk
        self._runner.on_stderr = lambda text: self.on_log(text)
        self._runner.on_finished = self._finish
        self._runner.on_error = lambda message: self.on_error(message)

    def compare(self, profile: SyncProfile) -> None:
        self._delete_enabled = profile.transfer.mirror_enabled
        self._cancelled = False
        self._buffer = ""
        self.on_started()
        self._runner.start(build_compare_spec(profile))

    def cancel(self) -> None:
        self._cancelled = True
        self._runner.cancel()

    def _stdout_chunk(self, text: str) -> None:
        """Stream rsync output while keeping partial lines buffered.

        Rsync separates itemized records with newlines and progress updates
        with carriage returns. Splitting on both gives complete lines even when
        QProcess delivers arbitrary chunk boundaries.
        """
        if not text:
            return
        self._buffer += text
        parts = re.split(r"[\r\n]", self._buffer)
        self._buffer = parts.pop()
        for line in parts:
            self._emit_line(line)

    def _emit_line(self, line: str) -> None:
        cleaned = line.strip()
        if not cleaned:
            return
        progress = parse_sync_progress(cleaned)
        if progress is not None:
            self.on_progress(progress)
            return
        self.on_log(cleaned)

    def _finish(self, process: ProcessResult) -> None:
        if self._buffer:
            self._emit_line(self._buffer)
            self._buffer = ""
        debug("compare.finish", exit_code=process.exit_code, stdout=repr(process.stdout[:2000]), stderr=repr(process.stderr[:2000]))
        if self._cancelled:
            self.on_cancelled()
            return
        if process.crashed:
            self.on_error("rsync terminated unexpectedly before comparison completed.")
            return
        if process.exit_code != 0:
            self.on_error(f"rsync exited with status {process.exit_code}: {process.stderr.strip()}")
            return
        try:
            parsed = parse_output(process.stdout, delete_enabled=self._delete_enabled)
        except ValueError as exc:
            self.on_error(f"Could not parse rsync output: {exc}")
            return
        debug("compare.parsed", changes=len(parsed.changes), diagnostics=len(parsed.diagnostics))
        self.on_finished(CompareResult(parsed, process.stderr, process.exit_code))
