"""Completion sounds, using the desktop sounds when they are available."""

from __future__ import annotations

import shutil
import subprocess

from PySide6.QtWidgets import QApplication

# The freedesktop sound names most desktops ship.
_SOUNDS = {
    "success": ("complete", "ok", "bell"),
    "warning": ("dialog-warning", "bell"),
    "error": ("dialog-error", "bell"),
}


def _play_freedesktop(kind: str) -> bool:
    if shutil.which("canberra-gtk-play") is None:
        return False
    for name in _SOUNDS.get(kind, ("bell",)):
        try:
            result = subprocess.run(
                ["canberra-gtk-play", "-i", name],
                check=False,
                timeout=2,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode == 0:
            return True
    return False


def play_completion_sound(kind: str = "success") -> None:
    """Play a short sound for a finished operation.

    The desktop sound is preferred; the terminal bell is the fallback so the
    feature also works on a minimal session.
    """
    if _play_freedesktop(kind):
        return
    QApplication.beep()
