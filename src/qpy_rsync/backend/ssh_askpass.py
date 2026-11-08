from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from shutil import which

_CANDIDATES = (
    "ksshaskpass",
    "ssh-askpass",
    "ssh-askpass-gnome",
    "gnome-ssh-askpass",
)


@dataclass(slots=True, frozen=True)
class AskpassConfiguration:
    executable: str
    source: str


def discover_askpass(environment: dict[str, str] | None = None) -> AskpassConfiguration | None:
    env = os.environ if environment is None else environment
    configured = env.get("SSH_ASKPASS", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return AskpassConfiguration(str(path), "SSH_ASKPASS")
    for name in _CANDIDATES:
        executable = which(name, path=env.get("PATH"))
        if executable:
            return AskpassConfiguration(executable, "PATH")
    return None


def askpass_environment(environment: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ if environment is None else environment
    config = discover_askpass(env)
    if config is None:
        raise ValueError(
            "No SSH askpass helper was found. On KDE Plasma install ksshaskpass, "
            "or set SSH_ASKPASS to an executable askpass program."
        )

    result = {
        "SSH_ASKPASS": config.executable,
        "SSH_ASKPASS_REQUIRE": "force",
    }

    # A Wayland Plasma session may have no DISPLAY. Some Qt askpass helpers
    # otherwise default to xcb and abort before showing the password dialog.
    platform = env.get("QT_QPA_PLATFORM", "").strip()
    wayland_display = env.get("WAYLAND_DISPLAY", "").strip()
    x11_display = env.get("DISPLAY", "").strip()
    if platform:
        result["QT_QPA_PLATFORM"] = platform
    elif wayland_display:
        result["QT_QPA_PLATFORM"] = "wayland"
    elif not x11_display:
        raise ValueError(
            "SSH askpass is installed, but no graphical session endpoint was found "
            "(neither WAYLAND_DISPLAY nor DISPLAY is set). Launch qpy-rsync from "
            "the Plasma desktop session or configure SSH key authentication."
        )
    return result
