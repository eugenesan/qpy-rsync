from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Callable

from .diagnostics import debug
from .rsync_command import ProcessSpec

if TYPE_CHECKING:
    from PySide6.QtCore import QObject


_SANITIZED_ENVIRONMENT_VARIABLES = (
    "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QML2_IMPORT_PATH",
    "QML_IMPORT_PATH",
    "LD_LIBRARY_PATH",
    "PYTHONHOME",
    "PYTHONPATH",
)


def sanitize_process_environment(environment: object) -> object:
    """Remove Python and Qt runtime paths before launching system programs."""
    for name in _SANITIZED_ENVIRONMENT_VARIABLES:
        environment.remove(name)
    return environment


class ProcessState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED_TO_START = "failed_to_start"


@dataclass(slots=True, frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    crashed: bool = False


class QtProcessRunner:
    """Asynchronous QProcess adapter with captured and incremental output."""

    def __init__(self, parent: QObject | None = None) -> None:
        try:
            from PySide6.QtCore import QProcess
        except ImportError as exc:
            raise RuntimeError("PySide6 is required for QtProcessRunner") from exc
        self._process = QProcess(parent)
        self._state = ProcessState.IDLE
        self._stdout = bytearray()
        self._stderr = bytearray()
        self.on_started: Callable[[], None] = lambda: None
        self.on_stdout: Callable[[str], None] = lambda _text: None
        self.on_stderr: Callable[[str], None] = lambda _text: None
        self.on_finished: Callable[[ProcessResult], None] = lambda _result: None
        self.on_error: Callable[[str], None] = lambda _message: None
        self._process.started.connect(self._started)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.finished.connect(self._finished)
        self._process.errorOccurred.connect(self._error)

    @property
    def state(self) -> ProcessState:
        return self._state

    def start(self, spec: ProcessSpec) -> None:
        if self._state in {ProcessState.STARTING, ProcessState.RUNNING}:
            raise RuntimeError("A process is already running")
        from PySide6.QtCore import QProcessEnvironment

        self._stdout.clear()
        self._stderr.clear()
        environment = QProcessEnvironment.systemEnvironment()
        sanitize_process_environment(environment)
        for key, value in spec.environment.items():
            environment.insert(key, value)
        self._process.setProcessEnvironment(environment)
        # Rsync/ssh must not wait forever on an unreadable QProcess stdin.
        # OpenSSH is forced through SSH_ASKPASS for remote profiles.
        self._process.closeWriteChannel()
        self._state = ProcessState.STARTING
        debug(
            "process.start",
            program=spec.program,
            arguments=spec.arguments,
            environment=spec.environment,
            sanitized=_SANITIZED_ENVIRONMENT_VARIABLES,
        )
        self._process.start(spec.program, list(spec.arguments))

    def cancel(self, force_after_ms: int = 3000) -> None:
        if self._state not in {ProcessState.STARTING, ProcessState.RUNNING}:
            return
        self._process.terminate()
        if force_after_ms >= 0:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(force_after_ms, self._kill_if_running)

    def _started(self) -> None:
        self._state = ProcessState.RUNNING
        debug("process.started", pid=int(self._process.processId()))
        self.on_started()

    def _kill_if_running(self) -> None:
        if self._state in {ProcessState.STARTING, ProcessState.RUNNING}:
            self._process.kill()

    def _read_stdout(self) -> None:
        data = bytes(self._process.readAllStandardOutput())
        if not data:
            return
        self._stdout.extend(data)
        debug("process.stdout", bytes=len(data), sample=repr(data[:500]))
        self.on_stdout(data.decode("utf-8", errors="replace"))

    def _read_stderr(self) -> None:
        data = bytes(self._process.readAllStandardError())
        if not data:
            return
        self._stderr.extend(data)
        debug("process.stderr", bytes=len(data), sample=repr(data[:500]))
        self.on_stderr(data.decode("utf-8", errors="replace"))

    def _finished(self, exit_code: int, exit_status: object) -> None:
        # Do not cast PySide enums with int(). Some supported PySide6 versions
        # reject that conversion, causing the UI to remain in "Comparing...".
        from PySide6.QtCore import QProcess

        self._read_stdout()
        self._read_stderr()
        self._state = ProcessState.FINISHED
        debug(
            "process.finished",
            exit_code=exit_code,
            exit_status=repr(exit_status),
            stdout_bytes=len(self._stdout),
            stderr_bytes=len(self._stderr),
        )
        crashed = exit_status == QProcess.ExitStatus.CrashExit
        self.on_finished(
            ProcessResult(
                exit_code,
                self._stdout.decode("utf-8", errors="replace"),
                self._stderr.decode("utf-8", errors="replace"),
                crashed,
            )
        )

    def _error(self, error: object) -> None:
        from PySide6.QtCore import QProcess

        if error == QProcess.ProcessError.FailedToStart:
            self._state = ProcessState.FAILED_TO_START
            message = f"Failed to start {self._process.program()!r}. Is rsync installed and in PATH?"
        else:
            message = f"Process error: {getattr(error, 'name', str(error))}"
        debug("process.error", error=repr(error), message=message)
        self.on_error(message)
