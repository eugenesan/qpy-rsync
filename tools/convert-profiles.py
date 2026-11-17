#!/usr/bin/env python3
"""Convert old qpy-rsync profile files to the filter_lines format.

Old profiles stored filters twice: as a structured "filters" list and as a
"filter_text" string. Current profiles store only "filter_lines", a list of
editor lines, and derive the structured list on load.

Usage:
    tools/convert-profiles.py [PROFILE_OR_DIRECTORY ...]
    tools/convert-profiles.py --dry-run ~/.config/qpy-rsync/profiles

With no paths, the default profile directory is used. Existing .bak files
are never overwritten; use --backup to keep a copy of each converted file.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent / "src"))

from qpy_rsync.backend.rsync_filters import rules_to_filter_text
from qpy_rsync.core.enums import FilterRuleType
from qpy_rsync.core.models import FilterRule


def default_profile_directory() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return root / "qpy-rsync" / "profiles"


def _rule_from_dict(item: object) -> FilterRule:
    if not isinstance(item, dict):
        raise ValueError(f"filter entry is not an object: {item!r}")
    return FilterRule(
        rule=str(item.get("rule", "")),
        enabled=bool(item.get("enabled", True)),
        rule_type=FilterRuleType(item.get("rule_type", "advanced")),
        comment=str(item.get("comment", "")),
    )


def convert_payload(payload: object) -> tuple[dict, bool]:
    """Return the converted payload and whether a change was needed."""
    if not isinstance(payload, dict):
        raise ValueError("profile root must be a JSON object")
    data = dict(payload)
    if (
        "filter_lines" in data
        and "filter_text" not in data
        and "filters" not in data
    ):
        return data, False

    # filter_text was authoritative in the old application. The structured
    # list is only used as a fallback for hand-written or very old profiles.
    text = data.pop("filter_text", None)
    old_filters = data.pop("filters", None)
    if text is None:
        rules = [_rule_from_dict(item) for item in (old_filters or [])]
        text = rules_to_filter_text(rules)
    if not isinstance(text, str):
        raise ValueError("filter_text must be a string")
    data["filter_lines"] = text.split("\n")
    return data, True


def iter_files(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        if path.is_dir():
            result.extend(sorted(path.glob("*.json")))
        else:
            result.append(path)
    return result


def convert_file(path: Path, *, dry_run: bool, backup: bool) -> str:
    raw = path.read_text(encoding="utf-8")
    converted, changed = convert_payload(json.loads(raw))
    if not changed:
        return "unchanged"
    if dry_run:
        return "would convert"
    payload = json.dumps(converted, indent=2, sort_keys=True) + "\n"
    if backup:
        backup_path = path.with_name(path.name + ".bak")
        if not backup_path.exists():
            shutil.copy2(path, backup_path)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return "converted"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="profile files or directories")
    parser.add_argument("--dry-run", action="store_true", help="show what would change")
    parser.add_argument("--backup", action="store_true", help="save a .bak copy before writing")
    args = parser.parse_args(argv)
    paths = args.paths or [default_profile_directory()]
    files = iter_files(paths)
    if not files:
        print(f"No profile files found in: {', '.join(str(p) for p in paths)}", file=sys.stderr)
        return 1
    for path in files:
        try:
            status = convert_file(path, dry_run=args.dry_run, backup=args.backup)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR {path}: {exc}", file=sys.stderr)
            return 1
        print(f"{status}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
