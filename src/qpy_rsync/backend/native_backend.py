"""Selection of the optional native extension.

The shipped application uses the pure-Python implementations. The extension
is opt-in via QPY_RSYNC_NATIVE=1, and =auto selects it only when the module is
present. Anything else, including an unset variable, stays on Python.
"""

from __future__ import annotations

import os

from .diagnostics import debug

NATIVE_FLAG = "QPY_RSYNC_NATIVE"

NATIVE_ACTION_CODE = {
    "create": 0,
    "update_content": 1,
    "update_metadata": 2,
    "delete": 3,
    "destination_only": 4,
    "no_change": 5,
    "message": 6,
}

NATIVE_ACTIONS = (
    "create",
    "update_content",
    "update_metadata",
    "delete",
    "destination_only",
    "no_change",
    "message",
)

NATIVE_KINDS = (
    "file",
    "directory",
    "symlink",
    "device",
    "special",
    "unknown",
)


def native_module():
    """Return the extension module when requested, else None."""
    flag = os.environ.get(NATIVE_FLAG, "").strip().lower()
    if flag not in {"1", "true", "yes", "on", "auto"}:
        return None
    try:
        from qpy_rsync import _qpy_native

        return _qpy_native
    except (ImportError, OSError):
        debug("native.backend_unavailable", flag=flag)
        return None
