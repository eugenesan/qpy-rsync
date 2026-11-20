from __future__ import annotations

from dataclasses import dataclass
import re
from time import perf_counter
from typing import Callable

from qpy_rsync.backend.diagnostics import debug, debug_timing
from qpy_rsync.backend.native_records import NativeRecordStore, new_store
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
        self._parse_seconds = 0.0
        self._log_seconds = 0.0
        self._line_count = 0
        # With the optional native backend the records are accumulated in
        # flat arrays instead of one Change object per line.
        self._native_store: NativeRecordStore | None = new_store(
            delete_enabled=False
        )
        self._pending_lines: list[str] = []
        self._last_items_reported = 0
        self._runner = QtProcessRunner(parent)  # type: ignore[arg-type]
        self.on_started: Callable[[], None] = lambda: None
        self.on_finished: Callable[[CompareResult], None] = lambda _result: None
        self.on_error: Callable[[str], None] = lambda _message: None
        self.on_cancelled: Callable[[], None] = lambda: None
        self.on_log: Callable[[str], None] = lambda _message: None
        self.on_diagnostic: Callable[[str], None] = lambda _message: None
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
        self._parse_seconds = 0.0
        self._log_seconds = 0.0
        self._line_count = 0
        self._pending_lines = []
        self._last_items_reported = 0
        self._native_store = new_store(
            delete_enabled=profile.transfer.mirror_enabled
        )
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
        self._flush_native_lines()

    def _flush_native_lines(self) -> None:
        """Parse a batch of buffered lines into the native record store."""
        if not self._pending_lines or self._native_store is None:
            return
        lines = self._pending_lines
        self._pending_lines = []
        if self._parse_error is not None:
            return
        self._native_store.delete_enabled = self._delete_enabled
        started = perf_counter()
        try:
            self._native_store.append(lines)
        except RsyncParseError as exc:
            self._parse_error = str(exc)
        self._parse_seconds += perf_counter() - started
        count = len(self._native_store)
        self._line_count = count + len(self._native_store.diagnostics)
        if count // 1000 > self._last_items_reported // 1000:
            self._last_items_reported = count
            self.on_items(count)

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
        log_started = perf_counter()
        self.on_log(cleaned)
        self._log_seconds += perf_counter() - log_started
        if self._parse_error is not None:
            return
        if self._native_store is not None:
            self._pending_lines.append(cleaned)
            return
        parse_started = perf_counter()
        try:
            change = parse_record(cleaned, delete_enabled=self._delete_enabled)
        except RsyncParseError as exc:
            self._parse_seconds += perf_counter() - parse_started
            self._parse_error = str(exc)
            return
        self._parse_seconds += perf_counter() - parse_started
        self._line_count += 1
        if change is None:
            self._diagnostics.append(cleaned)
            return
        self._changes.append(change)
        # Updating the label for every record is visible work in the GUI;
        # a thousand-record cadence is still live but far cheaper.
        if len(self._changes) % 1000 == 0:
            self.on_items(len(self._changes))

    def _finish(self, process: ProcessResult) -> None:
        if self._buffer:
            self._emit_line(self._buffer)
            self._buffer = ""
        self._flush_native_lines()
        self.on_items(
            len(self._native_store)
            if self._native_store is not None
            else len(self._changes)
        )
        debug_timing(
            "compare.parse",
            lines=self._line_count,
            parse_ms=round(self._parse_seconds * 1000, 1),
            log_ms=round(self._log_seconds * 1000, 1),
        )
        self.on_diagnostic(
            f"Compare parse: {self._line_count:,} line(s), "
            f"parsing {self._parse_seconds:.2f} s, "
            f"journal writes {self._log_seconds:.2f} s."
        )
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
        if self._native_store is not None:
            # A caller that fed the whole output at the end instead of
            # streaming it bypasses the streaming path; parse it now.
            if not len(self._native_store) and process.stdout:
                started = perf_counter()
                try:
                    self._native_store.append(process.stdout.splitlines())
                except RsyncParseError as exc:
                    self.on_error(f"Could not parse rsync output: {exc}")
                    return
                self._parse_seconds += perf_counter() - started
                self._line_count = (
                    len(self._native_store) + len(self._native_store.diagnostics)
                )
            from qpy_rsync.core.change_store import build_native_store

            parsed = ParseResult(
                self._native_store.changes() if len(self._native_store) else [],
                self._native_store.diagnostics,
                build_native_store(self._native_store),
            )
        else:
            # A caller that fed the whole output at the end instead of
            # streaming it (a synchronous test or a runner) bypasses the
            # streaming path; parse it now so the result is complete.
            if not self._changes and process.stdout:
                from qpy_rsync.backend.rsync_parser import parse_output

                try:
                    parsed_from_output = parse_output(
                        process.stdout, delete_enabled=self._delete_enabled
                    )
                except ValueError as exc:
                    self.on_error(f"Could not parse rsync output: {exc}")
                    return
                self._changes = list(parsed_from_output.changes)
                self._diagnostics = list(parsed_from_output.diagnostics)
            parsed = ParseResult(list(self._changes), list(self._diagnostics))
        debug("compare.parsed", changes=len(parsed.changes), diagnostics=len(parsed.diagnostics))
        self.on_finished(CompareResult(parsed, process.stderr, process.exit_code))
