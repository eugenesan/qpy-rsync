from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from qpy_rsync.backend.decision_filters import temporary_decision_filter
from qpy_rsync.backend.process_runner import ProcessResult, QtProcessRunner
from qpy_rsync.backend.rsync_command import build_compare_spec
from qpy_rsync.backend.rsync_parser import parse_output
from qpy_rsync.core.changes import Change, ChangeAction
from qpy_rsync.core.execution_plan import ExecutionPlan
from qpy_rsync.core.models import SyncProfile


@dataclass(slots=True, frozen=True)
class PlanMismatch:
    missing: tuple[tuple[str, ChangeAction, str], ...]
    unexpected: tuple[tuple[str, ChangeAction, str], ...]

    @property
    def valid(self) -> bool:
        return not self.missing and not self.unexpected


@dataclass(slots=True, frozen=True)
class PlanValidationResult:
    valid: bool
    mismatch: PlanMismatch
    stderr: str
    exit_code: int


def compare_plan_to_changes(plan: ExecutionPlan, changes: list[Change]) -> PlanMismatch:
    expected = {
        (item.path, item.action, item.kind.value)
        for item in plan.included_items
    }
    actual = {
        (change.path.rstrip("/"), change.action, change.kind.value)
        for change in changes
        if change.action not in {ChangeAction.NO_CHANGE, ChangeAction.MESSAGE, ChangeAction.DESTINATION_ONLY}
    }
    return PlanMismatch(
        missing=tuple(sorted(expected - actual)),
        unexpected=tuple(sorted(actual - expected)),
    )


class PlanValidationService:
    def __init__(self, parent: object | None = None) -> None:
        self._runner = QtProcessRunner(parent)  # type: ignore[arg-type]
        self._filter_context = None
        self._filter_path: Path | None = None
        self._plan: ExecutionPlan | None = None
        self._delete_enabled = False
        self.on_started: Callable[[], None] = lambda: None
        self.on_finished: Callable[[PlanValidationResult], None] = lambda _result: None
        self.on_error: Callable[[str], None] = lambda _message: None
        self.on_log: Callable[[str], None] = lambda _message: None
        self.on_spec: Callable[[object], None] = lambda _spec: None
        self._runner.on_stdout = lambda _chunk: None
        self._runner.on_stderr = lambda text: self.on_log(text)
        self._runner.on_finished = self._finish
        self._runner.on_error = self._error

    def validate(self, profile: SyncProfile, plan: ExecutionPlan) -> None:
        if plan.profile_fingerprint != __import__(
            "qpy_rsync.core.execution_plan", fromlist=["profile_fingerprint"]
        ).profile_fingerprint(profile):
            self.on_error("Execution plan is stale because profile options changed.")
            return
        self._plan = plan
        selected_deletions = any(
            item.included and item.action is ChangeAction.DELETE
            for item in plan.items
        )
        effective_profile = deepcopy(profile)
        effective_profile.transfer.delete = selected_deletions
        self._delete_enabled = selected_deletions
        self._filter_context = temporary_decision_filter(plan)
        self._filter_path = self._filter_context.__enter__()
        self.on_started()
        try:
            spec = build_compare_spec(effective_profile, filter_file=self._filter_path)
            self.on_spec(spec)
            self._runner.start(spec)
        except BaseException:
            self._cleanup()
            raise

    def cancel(self) -> None:
        self._runner.cancel()

    def _cleanup(self) -> None:
        if self._filter_context is not None:
            self._filter_context.__exit__(None, None, None)
        self._filter_context = None
        self._filter_path = None

    def _error(self, message: str) -> None:
        self._cleanup()
        self.on_error(message)

    def _finish(self, process: ProcessResult) -> None:
        try:
            if process.exit_code != 0:
                self.on_error(
                    f"Validation dry-run exited with status {process.exit_code}: {process.stderr.strip()}"
                )
                return
            assert self._plan is not None
            parsed = parse_output(process.stdout, delete_enabled=self._delete_enabled)
            mismatch = compare_plan_to_changes(self._plan, parsed.changes)
            self.on_finished(
                PlanValidationResult(mismatch.valid, mismatch, process.stderr, process.exit_code)
            )
        except ValueError as exc:
            self.on_error(f"Could not parse validation dry-run output: {exc}")
        finally:
            self._cleanup()
