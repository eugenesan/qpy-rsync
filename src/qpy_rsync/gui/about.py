from __future__ import annotations

import sys

from PySide6.QtWidgets import QMessageBox, QWidget

from qpy_rsync import __version__

_DESCRIPTION = (
    "A preview-driven frontend for rsync.\n\n"
    "Source and Destination are compared with a dry run, the selected "
    "actions are verified and only then written. Every command is shown in "
    "the journal before it runs."
)


def show_about(parent: QWidget | None = None) -> None:
    """Show the About dialog of the application."""
    from PySide6 import __version__ as pyside_version

    text = (
        f"qpy-rsync {__version__}\n\n"
        f"{_DESCRIPTION}\n\n"
        f"PySide6 {pyside_version}\n"
        f"Python {sys.version.split()[0]}"
    )
    QMessageBox.about(parent, "About qpy-rsync", text)
