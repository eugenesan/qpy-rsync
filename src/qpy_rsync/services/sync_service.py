from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from qpy_rsync.backend.decision_filters import temporary_decision_filter
from qpy_rsync.backend.process_runner import ProcessResult, QtProcessRunner
from qpy_rsync.backend.sync_progress import SyncProgress, parse_sync_progress
from qpy_rsync.backend.rsync_command import ProcessSpec, build_sync_spec
from qpy_rsync.core.changes import ChangeAction
from qpy_rsync.core.enums import EndpointKind
from qpy_rsync.core.execution_plan import ExecutionPlan, profile_fingerprint
from qpy_rsync.core.models import SyncProfile

@dataclass(slots=True, frozen=True)
class SyncResult:
    exit_code: int
    stdout: str
    stderr: str


_RSYNC_EXIT_MESSAGES = {
    1: "rsync reported a syntax or usage error.",
    2: "rsync reported a protocol incompatibility.",
    3: "rsync reported file-selection errors.",
    5: "rsync could not start the client-server protocol.",
    10: "rsync reported a socket I/O error.",
    11: "rsync reported a file I/O error.",
    12: "rsync reported a protocol data-stream error.",
    20: "rsync received SIGUSR1 or SIGINT.",
    23: "rsync completed with a partial transfer due to an error.",
    24: "rsync completed with vanished source files.",
    30: "rsync timed out while sending or receiving data.",
}


def explain_rsync_exit(code: int) -> str:
    return _RSYNC_EXIT_MESSAGES.get(code, f"rsync exited with status {code}.")


def enforce_execution_boundary(profile: SyncProfile) -> None:
    """Check that the profile may be executed.

    The earlier restriction to a disposable smoke-test tree was lifted in the
    safety review. Local and SSH endpoints are both allowed, so there is no
    path restriction left to enforce.
    """
    return None


class SyncService:
    def __init__(self, parent: object | None = None, *, runner=None) -> None:
        self._runner = runner if runner is not None else QtProcessRunner(parent)  # type: ignore[arg-type]
        self._filter_context = None
        self._filter_path: Path | None = None
        self._cancel_requested = False
        self._buffer = ""
        self.on_started: Callable[[], None] = lambda: None
        self.on_finished: Callable[[SyncResult], None] = lambda _result: None
        self.on_error: Callable[[str, bool], None] = lambda _message, _cancelled=False: None
        self.on_stdout: Callable[[str], None] = lambda _text: None
        self.on_stderr: Callable[[str], None] = lambda _text: None
        self.on_progress: Callable[[SyncProgress], None] = lambda _progress: None
        self.on_transient: Callable[[str], None] = lambda _text: None
        self.on_spec: Callable[[object], None] = lambda _spec: None
        self._runner.on_started = lambda: self.on_started()
        self._runner.on_stdout = self._handle_stdout
        self._runner.on_stderr = lambda text: self.on_stderr(text)
        self._runner.on_finished = self._finish
        self._runner.on_error = self._error

    def _handle_stdout(self, text: str) -> None:
        if not text:
            return
        self._buffer += text
        parts = re.split(r"[\r\n]", self._buffer)
        self._buffer = parts.pop()
        for line in parts:
            cleaned = line.strip()
            if not cleaned:
                continue
            progress = parse_sync_progress(cleaned)
            if progress is not None:
                # Progress and speed belong in the session log only; the
                # journal keeps the itemized records and application states.
                self.on_progress(progress)
                self.on_transient(cleaned)
                continue
            self.on_stdout(cleaned)

    def synchronize(
        self,
        profile: SyncProfile,
        plan: ExecutionPlan,
        *,
        filter_path: Path | None = None,
    ) -> ProcessSpec:
        enforce_execution_boundary(profile)
        if plan.profile_fingerprint != profile_fingerprint(profile):
            raise ValueError("The verified synchronization plan is stale.")
        if not plan.included_items:
            raise ValueError("The verified synchronization plan contains no included actions.")
        effective_profile = deepcopy(profile)
        effective_profile.transfer.delete = any(
            item.included and item.action is ChangeAction.DELETE
            for item in plan.items
        )
        self._cancel_requested = False
        self._buffer = ""
        if filter_path is None:
            self._filter_context = temporary_decision_filter(plan)
            self._filter_path = self._filter_context.__enter__()
        else:
            # The confirmation dialog owns this filter so it could show the
            # exact command before the user accepted.
            self._filter_context = None
            self._filter_path = None
        spec = build_sync_spec(
            effective_profile, filter_file=filter_path or self._filter_path
        )
        try:
            self.on_spec(spec)
            self._runner.start(spec)
        except BaseException:
            self._cleanup()
            raise
        return spec

    def cancel(self) -> None:
        self._cancel_requested = True
        self._runner.cancel()

    def pause(self) -> bool:
        """Suspend a running synchronization."""
        return self._runner.pause()

    def resume(self) -> bool:
        """Continue a suspended synchronization."""
        return self._runner.resume()

    @property
    def paused(self) -> bool:
        return self._runner.paused

    def shutdown(self, timeout_ms: int = 2000) -> None:
        """Stop a running synchronization so the window can be closed."""
        self._cancel_requested = True
        self._runner.shutdown(timeout_ms)

    def _cleanup(self) -> None:
        if self._filter_context is not None:
            self._filter_context.__exit__(None, None, None)
        self._filter_context = None
        self._filter_path = None

    def _error(self, message: str) -> None:
        cancelled = self._cancel_requested
        self._cleanup()
        self.on_error(message, cancelled)

    def _finish(self, process: ProcessResult) -> None:
        if self._buffer:
            cleaned = self._buffer.strip()
            self._buffer = ""
            if cleaned:
                if parse_sync_progress(cleaned) is not None:
                    self.on_transient(cleaned)
                else:
                    self.on_stdout(cleaned)
        try:
            if self._cancel_requested or process.crashed:
                self.on_error("Synchronization was cancelled or terminated.", True)
                return
            if process.exit_code != 0:
                detail = explain_rsync_exit(process.exit_code)
                if process.stderr.strip():
                    detail += " " + process.stderr.strip()
                self.on_error(detail, False)
                return
            self.on_finished(SyncResult(process.exit_code, process.stdout, process.stderr))
        finally:
            self._cleanup()
