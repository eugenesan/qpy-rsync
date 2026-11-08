from qpy_rsync.backend.process_runner import ProcessResult, ProcessState


def test_process_states_include_starting() -> None:
    assert ProcessState.STARTING.value == "starting"


def test_process_result_defaults_to_not_crashed() -> None:
    result = ProcessResult(0, "ok", "")
    assert not result.crashed
