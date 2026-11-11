from qpy_rsync.backend.process_runner import ProcessResult, ProcessState


def test_process_states_include_starting() -> None:
    assert ProcessState.STARTING.value == "starting"


def test_process_result_defaults_to_not_crashed() -> None:
    result = ProcessResult(0, "ok", "")
    assert not result.crashed


def test_running_process_can_be_paused_and_resumed() -> None:
    import time

    from PySide6.QtWidgets import QApplication

    from qpy_rsync.backend.process_runner import QtProcessRunner
    from qpy_rsync.backend.rsync_command import ProcessSpec

    application = QApplication.instance() or QApplication([])
    runner = QtProcessRunner()
    finished: list[ProcessResult] = []
    runner.on_finished = finished.append
    runner.start(ProcessSpec("sleep", ("5",), {}))

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not runner.state is ProcessState.RUNNING:
        application.processEvents()
        time.sleep(0.01)
    assert runner.state is ProcessState.RUNNING
    pid = int(runner._process.processId())

    def process_state() -> str:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            return handle.read().rsplit(")", 1)[1].split()[0]

    assert runner.pause()
    assert runner.paused
    assert process_state() == "T"

    time.sleep(0.5)
    application.processEvents()
    assert finished == []

    assert runner.resume()
    assert not runner.paused
    assert process_state() != "T"

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not finished:
        application.processEvents()
        time.sleep(0.01)
    assert finished
    assert finished[0].exit_code == 0
