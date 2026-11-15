from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from qpy_rsync.backend.diagnostics import debug
from qpy_rsync.backend.process_runner import (
    ProcessResult,
    ProcessState,
    QtProcessRunner,
)
from qpy_rsync.backend.rsync_command import build_compare_spec
from qpy_rsync.backend.rsync_parser import (
    ParseResult,
    RsyncParseError,
    parse_record,
)
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
        # The records are parsed while rsync writes them, so the number of
        # items found can be reported while the comparison runs.
        self._changes: list[object] = []
        self._diagnostics: list[str] = []
        self._parse_error: str | None = None
        self._runner = QtProcessRunner(parent)  # type: ignore[arg-type]
        self.on_started: Callable[[], None] = lambda: None
        self.on_finished: Callable[[CompareResult], None] = lambda _result: None
        self.on_error: Callable[[str], None] = lambda _message: None
        self.on_cancelled: Callable[[], None] = lambda: None
        self.on_log: Callable[[str], None] = lambda _message: None
        self.on_progress: Callable[[SyncProgress], None] = lambda _progress: None
        self.on_transient: Callable[[str], None] = lambda _text: None
        # The number of items the comparison has found so far.
        self.on_items: Callable[[int], None] = lambda _count: None
        # Indirection is intentional: GUI callbacks are assigned after this service is constructed.
        self._runner.on_stdout = self._stdout_chunk
        self._runner.on_stderr = lambda text: self.on_log(text)
        self._runner.on_finished = self._finish
        self._runner.on_error = lambda message: self.on_error(message)

    def compare(self, profile: SyncProfile) -> None:
        self._delete_enabled = profile.transfer.mirror_enabled
        self._cancelled = False
        self._buffer = ""
        self._changes = []
        self._diagnostics = []
        self._parse_error = None
        self.on_started()
        self._runner.start(build_compare_spec(profile))

    def cancel(self) -> None:
        self._cancelled = True
        self._runner.cancel()

    @property
    def state(self) -> ProcessState:
        """Return the state of the rsync process."""
        return self._runner.state

    def pause(self) -> bool:
        """Suspend a running comparison."""
        return self._runner.pause()

    def resume(self) -> bool:
        """Continue a suspended comparison."""
        return self._runner.resume()

    @property
    def paused(self) -> bool:
        return self._runner.paused

    def shutdown(self, timeout_ms: int = 2000) -> None:
        """Stop a running comparison so the window can be closed."""
        self._cancelled = True
        self._runner.shutdown(timeout_ms)

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
            # Progress and speed belong in the session log only; the journal
            # keeps the itemized records and application states.
            self.on_progress(progress)
            self.on_transient(cleaned)
            return
        self.on_log(cleaned)
        if self._parse_error is not None:
            return
        try:
            change = parse_record(cleaned, delete_enabled=self._delete_enabled)
        except RsyncParseError as exc:
            self._parse_error = str(exc)
            return
        if change is None:
            self._diagnostics.append(cleaned)
            return
        self._changes.append(change)
        # The comparison reports what it found, so the window can show the
        # progress of the dry run.
        self.on_items(len(self._changes))

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
        if self._parse_error is not None:
            self.on_error(f"Could not parse rsync output: {self._parse_error}")
            return
        # A caller that fed the whole output at the end instead of
        # streaming it (a synchronous test or a runner) bypasses the
        # streaming path; parse it now so the result is complete.
        if not self._changes and process.stdout:
            from qpy_rsync.backend.rsync_parser import parse_output

            try:
                parsed = parse_output(
                    process.stdout, delete_enabled=self._delete_enabled
                )
            except ValueError as exc:
                self.on_error(f"Could not parse rsync output: {exc}")
                return
            self._changes = list(parsed.changes)
            self._diagnostics = list(parsed.diagnostics)
        parsed = ParseResult(list(self._changes), list(self._diagnostics))
        debug("compare.parsed", changes=len(parsed.changes), diagnostics=len(parsed.diagnostics))
        self.on_finished(CompareResult(parsed, process.stderr, process.exit_code))
