from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from qpy_rsync.backend.rsync_command import build_compare_spec, build_sync_spec
from qpy_rsync.core.validation import validate_profile
from qpy_rsync.storage.profile_store import load_profile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qpy-rsync-cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview", help="validate a profile and print generated commands")
    preview.add_argument("profile", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    profile = load_profile(args.profile)
    messages = validate_profile(profile)
    compare = build_compare_spec(profile)
    sync = build_sync_spec(profile)
    result = {
        "profile": profile.name,
        "validation": [{"severity": item.severity.value, "code": item.code, "message": item.message} for item in messages],
        "compare_argv": compare.argv(),
        "compare_display": shlex.join(compare.argv()),
        "sync_argv": sync.argv(),
        "sync_display": shlex.join(sync.argv()),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
