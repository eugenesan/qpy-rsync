from __future__ import annotations

import re
from os.path import expanduser

from .enums import EndpointKind
from .models import Endpoint

_SSH_PATTERN = re.compile(r"^(?:(?P<user>[^@/:\s]+)@)?(?P<host>[^/:\s]+):(?P<path>/.*|~/.*)$")


def parse_endpoint(text: str, *, directory_contents: bool = True) -> Endpoint:
    """Parse a local or rsync-over-SSH endpoint entered in the UI.

    Remote syntax intentionally follows rsync's remote-shell operand syntax:
    ``[user@]host:/absolute/path``. A host alias from ``~/.ssh/config`` may be
    used. This parser does not accept rsync daemon ``host::module`` syntax.
    """
    value = text.strip()
    if not value:
        raise ValueError("Endpoint is empty")
    match = _SSH_PATTERN.fullmatch(value)
    if match:
        path = _directory_path(match.group("path"), directory_contents)
        return Endpoint(EndpointKind.SSH, path, host=match.group("host"), user=match.group("user"))
    if "::" in value or value.startswith("rsync://"):
        raise ValueError("rsync daemon endpoints are not supported")
    if ":" in value:
        raise ValueError("Remote endpoint must use [user@]host:/absolute/path")
    local = _directory_path(expanduser(value), directory_contents)
    return Endpoint(EndpointKind.LOCAL, local)


def _directory_path(path: str, contents: bool) -> str:
    if not contents or path == "/" or path.endswith("/"):
        return path
    return path + "/"
