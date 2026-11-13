"""Small helpers shared by the comparison widgets."""

from __future__ import annotations


def full_path(root: str, path: str) -> str:
    """Join an endpoint root and a relative comparison path."""
    clean_root = root.rstrip("/")
    clean_path = path.strip("/")
    if not clean_root:
        return clean_path
    if not clean_path:
        return clean_root
    return f"{clean_root}/{clean_path}"
