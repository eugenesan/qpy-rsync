from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from PySide6.QtWidgets import QMessageBox, QWidget

from qpy_rsync import __version__

_DESCRIPTION = (
    "A preview-driven frontend for rsync.\n\n"
    "Source and Destination are compared with a dry run, the selected "
    "actions are verified and only then written. Every command is shown in "
    "the journal before it runs."
)


def build_stamp() -> str:
    """The commit of the checkout, when the application runs from one.

    The application often runs from a copy that is synchronized from
    another machine, so the commit tells which build is on the screen.
    """
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        return ""
    try:
        result = subprocess.run(
            ("git", "rev-parse", "--short", "HEAD"),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def show_about(parent: QWidget | None = None) -> None:
    """Show the About dialog of the application."""
    from PySide6 import __version__ as pyside_version

    stamp = build_stamp()
    version = f"qpy-rsync {__version__}"
    if stamp:
        version = f"{version} ({stamp})"
    text = (
        f"{version}\n\n"
        f"{_DESCRIPTION}\n\n"
        f"PySide6 {pyside_version}\n"
        f"Python {sys.version.split()[0]}"
    )
    QMessageBox.about(parent, "About qpy-rsync", text)
