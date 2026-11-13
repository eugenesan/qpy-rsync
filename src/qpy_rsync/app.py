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
        ),
        qt_arguments,
    )


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


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    options, qt_arguments = parse_startup_options(arguments)
    prepare_qt_environment()
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print("PySide6 is required to run qpy-rsync.", file=sys.stderr)
        raise SystemExit(2) from exc

    from qpy_rsync.gui.main_window import MainWindow

    app = QApplication([sys.argv[0], *qt_arguments])
    app.setApplicationName("qpy-rsync")
    app.setOrganizationName("qpy-rsync")
    app.setQuitOnLastWindowClosed(True)
    from pathlib import Path

    from PySide6.QtGui import QIcon

    icon_path = Path(__file__).resolve().parents[2] / "qpy-rsync.svg"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    from qpy_rsync.storage.settings import migrate_legacy_settings

    migrate_legacy_settings()
    window = MainWindow()
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.apply_startup_options(options)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
