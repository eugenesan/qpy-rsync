from __future__ import annotations


def format_size(size: int | None) -> str:
    """Format a number of bytes the way every pane displays it."""
    if size is None:
        return ""
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""
