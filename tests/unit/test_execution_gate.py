import pytest

from qpy_rsync.core.execution_gate import (
    ExecutionGate,
    ExecutionGateState,
    InvalidGateTransition,
)


def test_verified_confirmation_flow() -> None:
    gate = ExecutionGate()
    gate.comparison_ready(included=3)
    assert gate.state is ExecutionGateState.SELECTION_READY
    assert gate.view().can_verify
    gate.verification_started()
    gate.verification_succeeded()
    assert gate.view().can_confirm
    gate.confirmation_opened()
    assert gate.view().can_execute
    gate.confirmation_cancelled()
    assert gate.state is ExecutionGateState.VERIFIED


def test_invalidation_blocks_confirmation() -> None:
    gate = ExecutionGate()
    gate.comparison_ready(included=1)
    gate.verification_started()
    gate.verification_succeeded()
    gate.invalidate()
    assert gate.state is ExecutionGateState.COMPARISON_OUTDATED
    assert not gate.view().can_confirm
    with pytest.raises(InvalidGateTransition):
        gate.confirmation_opened()


def test_selection_change_revokes_verification() -> None:
    gate = ExecutionGate()
    gate.comparison_ready(included=2)
    gate.verification_started()
    gate.verification_succeeded()
    gate.selection_changed(included=1)
    assert gate.state is ExecutionGateState.SELECTION_READY
    assert gate.view().can_verify

def test_execution_completion_failure_and_cancel_paths() -> None:
    gate = ExecutionGate()
    gate.comparison_ready(included=1)
    gate.verification_started(); gate.verification_succeeded(); gate.confirmation_opened()
    gate.execution_started(); gate.execution_completed()
    assert gate.state is ExecutionGateState.COMPLETED

    gate = ExecutionGate()
    gate.comparison_ready(included=1)
    gate.verification_started(); gate.verification_succeeded(); gate.confirmation_opened()
    gate.execution_started(); gate.execution_failed()
    assert gate.state is ExecutionGateState.FAILED

    gate = ExecutionGate()
    gate.comparison_ready(included=1)
    gate.verification_started(); gate.verification_succeeded(); gate.confirmation_opened()
    gate.execution_started(); gate.execution_cancelled()
    assert gate.state is ExecutionGateState.CANCELLED


def test_verification_can_run_again_after_a_success() -> None:
    gate = ExecutionGate()
    gate.comparison_ready(included=1)
    gate.verification_started()
    gate.verification_succeeded()
    assert gate.state is ExecutionGateState.VERIFIED

    # Clicking Verify Actions a second time must not raise.
    gate.verification_started()
    assert gate.state is ExecutionGateState.VERIFYING
    gate.verification_succeeded()
    assert gate.state is ExecutionGateState.VERIFIED
