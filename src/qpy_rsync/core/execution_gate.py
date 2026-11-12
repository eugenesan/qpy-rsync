from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExecutionGateState(StrEnum):
    NO_COMPARISON = "no_comparison"
    COMPARISON_OUTDATED = "comparison_outdated"
    SELECTION_READY = "selection_ready"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    CONFIRMING = "confirming"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True, frozen=True)
class ExecutionGateView:
    state: ExecutionGateState
    can_compare: bool
    can_verify: bool
    can_confirm: bool
    can_execute: bool
    can_swap: bool
    message: str


class InvalidGateTransition(ValueError):
    pass


class ExecutionGate:
    """Pure state machine guarding verification, confirmation, and execution."""

    def __init__(self) -> None:
        self._state = ExecutionGateState.NO_COMPARISON

    @property
    def state(self) -> ExecutionGateState:
        return self._state

    def comparison_ready(self, *, included: int) -> None:
        self._state = (
            ExecutionGateState.SELECTION_READY
            if included > 0
            else ExecutionGateState.NO_COMPARISON
        )

    def invalidate(self) -> None:
        self._state = ExecutionGateState.COMPARISON_OUTDATED

    def selection_changed(self, *, included: int) -> None:
        self.comparison_ready(included=included)

    def verification_started(self) -> None:
        # Verifying again after a successful verification is allowed.
        self._require_any(
            ExecutionGateState.SELECTION_READY,
            ExecutionGateState.VERIFIED,
        )
        self._state = ExecutionGateState.VERIFYING

    def verification_succeeded(self) -> None:
        self._require(ExecutionGateState.VERIFYING)
        self._state = ExecutionGateState.VERIFIED

    def verification_failed(self) -> None:
        self._require(ExecutionGateState.VERIFYING)
        self._state = ExecutionGateState.SELECTION_READY

    def confirmation_opened(self) -> None:
        self._require(ExecutionGateState.VERIFIED)
        self._state = ExecutionGateState.CONFIRMING

    def confirmation_cancelled(self) -> None:
        self._require(ExecutionGateState.CONFIRMING)
        self._state = ExecutionGateState.VERIFIED

    def execution_started(self) -> None:
        self._require(ExecutionGateState.CONFIRMING)
        self._state = ExecutionGateState.EXECUTING

    def execution_completed(self) -> None:
        self._require(ExecutionGateState.EXECUTING)
        self._state = ExecutionGateState.COMPLETED

    def execution_failed(self) -> None:
        self._require(ExecutionGateState.EXECUTING)
        self._state = ExecutionGateState.FAILED

    def execution_cancelled(self) -> None:
        self._require(ExecutionGateState.EXECUTING)
        self._state = ExecutionGateState.CANCELLED

    def view(self) -> ExecutionGateView:
        state = self._state
        messages = {
            ExecutionGateState.NO_COMPARISON: "Compare Source and Destination before synchronization.",
            ExecutionGateState.COMPARISON_OUTDATED: "Comparison is out of date. Compare again.",
            ExecutionGateState.SELECTION_READY: "Verify selected actions before synchronization.",
            ExecutionGateState.VERIFYING: "Verifying selected actions with a second dry run.",
            ExecutionGateState.VERIFIED: "Selected actions are verified and ready for confirmation.",
            ExecutionGateState.CONFIRMING: "Review the confirmation summary before synchronization.",
            ExecutionGateState.EXECUTING: "Synchronization is running.",
            ExecutionGateState.COMPLETED: "Synchronization completed; compare again to refresh.",
            ExecutionGateState.FAILED: "Synchronization failed; review diagnostics before retrying.",
            ExecutionGateState.CANCELLED: "Synchronization was cancelled; compare again before retrying.",
        }
        return ExecutionGateView(
            state=state,
            can_compare=state not in {ExecutionGateState.VERIFYING, ExecutionGateState.EXECUTING},
            can_verify=state
            in {ExecutionGateState.SELECTION_READY, ExecutionGateState.VERIFIED},
            can_confirm=state is ExecutionGateState.VERIFIED,
            can_execute=state is ExecutionGateState.CONFIRMING,
            can_swap=state not in {ExecutionGateState.VERIFYING, ExecutionGateState.EXECUTING},
            message=messages[state],
        )

    def _require(self, expected: ExecutionGateState) -> None:
        self._require_any(expected)

    def _require_any(self, *expected: ExecutionGateState) -> None:
        if self._state not in expected:
            wanted = " or ".join(state.value for state in expected)
            raise InvalidGateTransition(
                f"Cannot transition from {self._state.value}; expected {wanted}."
            )
