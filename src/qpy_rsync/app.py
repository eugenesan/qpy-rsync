from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import sys
from typing import Sequence

from qpy_rsync.core.enums import SyncMode


@dataclass(slots=True, frozen=True)
class StartupOptions:
    source: str | None = None
    destination: str | None = None
    backup: str | None = None
    mode: SyncMode | None = None
    compare: bool = False
    log_file: str | None = None
    logging_enabled: bool | None = None
    version: bool = False


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qpy-rsync",
        description="Launch the qpy-rsync GUI with optional comparison settings.",
    )
    parser.add_argument(
        "--dir-pair",
        nargs=2,
        metavar=("SOURCE", "DESTINATION"),
        help="populate the one-way Source and Destination fields",
    )
    parser.add_argument(
        "--backup",
        metavar="DIRECTORY",
        help="populate the destination-side backup directory",
    )
    parser.add_argument(
        "--mode",
        choices=("update", "mirror", "new-only"),
        help="select Update, Mirror, or New Only",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="start comparison after the GUI event loop initializes",
    )
    logging_group = parser.add_mutually_exclusive_group()
    logging_group.add_argument(
        "--log-file",
        metavar="PATH",
        help="enable session logging and override the XDG state log path",
    )
    logging_group.add_argument(
        "--no-log-file",
        action="store_true",
        help="disable persistent session logging for this launch",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the version and the build, then exit",
    )
    return parser


def parse_startup_options(argv: Sequence[str]) -> tuple[StartupOptions, list[str]]:
    parser = build_argument_parser()
    namespace, qt_arguments = parser.parse_known_args(list(argv))
    if namespace.compare and not namespace.dir_pair:
        parser.error("--compare requires --dir-pair SOURCE DESTINATION")
    source = destination = None
    if namespace.dir_pair:
        source, destination = namespace.dir_pair
    mode = None
    if namespace.mode:
        mode = SyncMode(namespace.mode.replace("-", "_"))
    return (
        StartupOptions(
            source,
            destination,
            namespace.backup,
            mode,
            namespace.compare,
            namespace.log_file,
            False if namespace.no_log_file else (True if namespace.log_file else None),
            namespace.version,
        ),
        qt_arguments,
    )


def install_qt_message_filter() -> None:
    """Keep the harmless OpenGL notices out of the terminal.

    Every other message is passed on, so a real problem is still reported.
    """

    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:  # pragma: no cover - PySide6 is always there
        return

    def handler(mode: object, _context: object, message: str) -> None:
        text = str(message)
        from qpy_rsync.backend.diagnostics import BENIGN_QT_MESSAGES

        if any(pattern in text for pattern in BENIGN_QT_MESSAGES):
            return
        sys.stderr.write(text + "\n")
        if mode == QtMsgType.QtFatalMsg:
            sys.stderr.flush()
            os.abort()

    qInstallMessageHandler(handler)


def prepare_qt_environment() -> None:
    """Keep Qt away from OpenGL on remote X11 sessions.

    The KDE platform theme loads Qt Quick, which asks for a graphics context.
    A remote X server often has no usable GLX or EGL config, so the software
    renderer is requested before Qt is initialized.
    """
    os.environ.setdefault("QT_XCB_GL_INTEGRATION", "none")
    # Qt Quick has a software adaptation, but the RHI backends have no
    # "software" value: asking for one makes Qt fall back to OpenGL, which is
    # exactly what produces the qglx_findConfig warnings.
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    # The platform theme can still probe GLX even though this application is
    # widgets-only. The probe is harmless but noisy, so its warnings are kept
    # out of the terminal.
    rules = os.environ.get("QT_LOGGING_RULES", "")
    if "qt.glx" not in rules:
        os.environ["QT_LOGGING_RULES"] = (
            f"{rules}\nqt.glx.warning=false" if rules else "qt.glx.warning=false"
        )


_TOOLTIP_STYLE_CLASS = None


def install_tooltip_style(qt_app: object) -> None:
    """Give every tooltip the same wake-up delay and no fall-asleep grace.

    Qt's own defaults (700 ms wake-up, 2000 ms asleep) make the tooltip of
    the widget under the pointer appear immediately after leaving another
    one. A proxy style with a uniform 250 ms wake-up and zero grace keeps the
    delay the same everywhere, just like the native Qt build.
    """
    global _TOOLTIP_STYLE_CLASS
    from PySide6.QtWidgets import QProxyStyle, QStyle

    if _TOOLTIP_STYLE_CLASS is None:

        class TooltipStyle(QProxyStyle):
            def styleHint(  # noqa: N802
                self,
                hint: object,
                option: object = None,
                widget: object = None,
                returnData: object = None,  # noqa: N803
            ) -> int:
                if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
                    return 250
                if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
                    return 0
                return super().styleHint(  # type: ignore[arg-type]
                    hint, option, widget, returnData  # type: ignore[arg-type]
                )

        _TOOLTIP_STYLE_CLASS = TooltipStyle
    TooltipStyle = _TOOLTIP_STYLE_CLASS
    # Installing twice must not stack proxy styles on top of each other.
    if isinstance(qt_app.style(), TooltipStyle):  # type: ignore[attr-defined]
        return
    qt_app.setStyle(TooltipStyle(qt_app.style()))  # type: ignore[attr-defined]


def install_interrupt_handler(qt_app: object) -> None:
    """Make Ctrl+C close a startup dialog instead of being swallowed by Qt.

    A modal ``exec()`` runs a nested C++ event loop, where Python's SIGINT
    flag is never checked. Defer the shutdown to a zero-timer so the Python
    callback runs inside that loop and can close the dialog.
    """
    import signal

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog

    def shutdown() -> None:
        for widget in qt_app.topLevelWidgets():  # type: ignore[attr-defined]
            if isinstance(widget, QDialog) and widget.isVisible():
                try:
                    widget.reject()
                except Exception:  # noqa: BLE001
                    pass
        qt_app.quit()  # type: ignore[attr-defined]

    def handle(_signum: int, _frame: object) -> None:
        QTimer.singleShot(0, shutdown)

    signal.signal(signal.SIGINT, handle)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    options, qt_arguments = parse_startup_options(arguments)
    if options.version:
        from qpy_rsync.gui.about import version_string

        print(version_string())
        return 0
    prepare_qt_environment()
    install_qt_message_filter()
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print("PySide6 is required to run qpy-rsync.", file=sys.stderr)
        raise SystemExit(2) from exc

    from qpy_rsync.gui.main_window import MainWindow

    app = QApplication([sys.argv[0], *qt_arguments])
    install_tooltip_style(app)
    install_interrupt_handler(app)
    app.setApplicationName("qpy-rsync")
    app.setOrganizationName("qpy-rsync")
    app.setQuitOnLastWindowClosed(True)
    from pathlib import Path

    from PySide6.QtGui import QIcon

    icon = QIcon.fromTheme("qpy-rsync")
    if icon.isNull():
        icon_path = (
            Path(__file__).resolve().parents[2] / "resources" / "qpy-rsync.svg"
        )
        if icon_path.is_file():
            icon = QIcon(str(icon_path))
    if not icon.isNull():
        app.setWindowIcon(icon)
    window = MainWindow()
    if getattr(window, "_startup_abort", False):
        # The user chose to quit when the profile was locked; nothing was
        # loaded, locked or written. Tear the window down before returning so
        # its C++ object is not destroyed during interpreter shutdown.
        from PySide6.QtCore import Qt

        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        window.close()
        app.processEvents()
        app.quit()
        app.processEvents()
        return 0
    window.setWindowTitle("qpy-rsync")
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.apply_startup_options(options)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
