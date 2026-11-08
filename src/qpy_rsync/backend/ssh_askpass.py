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
    """Return explicit environment entries required by graphical SSH askpass.

    We copy the display/session variables deliberately instead of relying only
    on QProcessEnvironment inheritance. This also makes diagnostics show the
    exact display endpoint supplied to the askpass process launched by ssh.
    """
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

    for name in (
        "DISPLAY",
        "XAUTHORITY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "DESKTOP_STARTUP_ID",
    ):
        value = env.get(name, "").strip()
        if value:
            result[name] = value

    platform = env.get("QT_QPA_PLATFORM", "").strip()
    if platform:
        result["QT_QPA_PLATFORM"] = platform
    elif result.get("WAYLAND_DISPLAY") and not result.get("DISPLAY"):
        result["QT_QPA_PLATFORM"] = "wayland"
    elif result.get("DISPLAY"):
        result["QT_QPA_PLATFORM"] = "xcb"
    else:
        raise ValueError(
            "SSH askpass is installed, but no graphical session endpoint was found "
            "(neither WAYLAND_DISPLAY nor DISPLAY is set). Launch qpy-rsync from "
            "the Plasma desktop session or configure SSH key authentication."
        )
    return result
