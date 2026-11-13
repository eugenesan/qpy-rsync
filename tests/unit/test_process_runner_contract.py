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
    # A failed assertion must not leave the process running: Qt aborts on a
    # QProcess that is destroyed while its process is alive.
    import atexit

    atexit.register(runner.shutdown)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not runner.state is ProcessState.RUNNING:
        application.processEvents()
        time.sleep(0.01)
    assert runner.state is ProcessState.RUNNING
    pid = int(runner._process.processId())

    def process_state() -> str:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            return handle.read().rsplit(")", 1)[1].split()[0]

    def wait_for_state(expected: str, *, present: bool) -> str:
        """Wait until the process reaches (or leaves) the given state.

        The signal is delivered asynchronously, so the state cannot be read
        back immediately after ``kill``.
        """
        deadline = time.monotonic() + 5
        state = process_state()
        while time.monotonic() < deadline:
            state = process_state()
            if (state == expected) is present:
                return state
            application.processEvents()
            time.sleep(0.01)
        return state

    assert runner.pause()
    assert runner.paused
    assert wait_for_state("T", present=True) == "T"

    time.sleep(0.5)
    application.processEvents()
    assert finished == []

    assert runner.resume()
    assert not runner.paused
    assert wait_for_state("T", present=False) != "T"

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not finished:
        application.processEvents()
        time.sleep(0.01)
    assert finished
    assert finished[0].exit_code == 0
