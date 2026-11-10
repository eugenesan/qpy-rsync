from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections import Counter
from typing import Sequence

from qpy_rsync.backend.rsync_command import ProcessSpec, build_compare_spec
from qpy_rsync.backend.rsync_parser import parse_output
from qpy_rsync.core.endpoints import parse_endpoint
from qpy_rsync.core.enums import SyncMode
from qpy_rsync.core.models import BackupOptions, SyncProfile, TransferOptions


_MODE_ARGUMENTS = {
    "update": SyncMode.UPDATE,
    "mirror": SyncMode.MIRROR,
    "new-only": SyncMode.NEW_ONLY,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qpy-rsync-cli",
        description="Compare one Source/Destination pair using qpy-rsync's rsync backend.",
    )
    parser.add_argument(
        "--dir-pair",
        nargs=2,
        metavar=("SOURCE", "DESTINATION"),
        required=True,
        help="one-way Source and Destination paths; either side may use [user@]host:/path",
    )
    parser.add_argument(
        "--backup",
        metavar="DIRECTORY",
        default="",
        help="destination-side backup directory; an empty value disables backups",
    )
    parser.add_argument(
        "--mode",
        choices=tuple(_MODE_ARGUMENTS),
        default="update",
        help="update (default), mirror, or new-only",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="run an rsync dry-run comparison and print normalized actions",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable comparison output",
    )
    parser.add_argument(
        "--show-command",
        action="store_true",
        help="print the exact argument vector before comparison",
    )
    return parser


def profile_from_args(args: argparse.Namespace) -> SyncProfile:
    source_text, destination_text = args.dir_pair
    return SyncProfile(
        name="command-line comparison",
        source=parse_endpoint(source_text),
        destination=parse_endpoint(destination_text),
        transfer=TransferOptions(sync_mode=_MODE_ARGUMENTS[args.mode]),
        backup=BackupOptions(directory=args.backup),
    )


def run_process(spec: ProcessSpec) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in (
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "QML2_IMPORT_PATH",
        "QML_IMPORT_PATH",
        "LD_LIBRARY_PATH",
        "PYTHONHOME",
        "PYTHONPATH",
    ):
        environment.pop(name, None)
    environment.update(spec.environment)
    return subprocess.run(
        spec.argv(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
    )


def _change_record(change) -> dict[str, object]:
    return {
        "path": change.path,
        "action": change.action.value,
        "kind": change.kind.value,
        "size": change.size,
        "modified_time": change.modified_time,
        "link_target": change.link_target,
        "itemized_code": change.itemized_code,
        "reason": change.reason,
    }


def print_result(profile: SyncProfile, parsed, *, as_json: bool) -> None:
    counts = Counter(change.action.value for change in parsed.changes)
    if as_json:
        print(
            json.dumps(
                {
                    "source": profile.source.rsync_operand(),
                    "destination": profile.destination.rsync_operand(),
                    "mode": profile.transfer.sync_mode.value,
                    "backup": profile.backup.directory or None,
                    "counts": dict(sorted(counts.items())),
                    "changes": [_change_record(change) for change in parsed.changes],
                    "diagnostics": parsed.diagnostics,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    print(f"Source:      {profile.source.rsync_operand()}")
    print(f"Destination: {profile.destination.rsync_operand()}")
    print(f"Mode:        {profile.transfer.sync_mode.value}")
    print(f"Backup:      {profile.backup.directory or 'disabled'}")
    print()
    if not parsed.changes:
        print("No changed objects.")
    else:
        for change in parsed.changes:
            print(f"{change.action.value:18} {change.kind.value:10} {change.path}")
    print()
    summary = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
    print(f"Summary: {summary or 'no changes'}")
    for diagnostic in parsed.diagnostics:
        print(f"Diagnostic: {diagnostic}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.compare:
        parser.error("no operation selected; add --compare")
    try:
        profile = profile_from_args(args)
        spec = build_compare_spec(profile)
    except ValueError as exc:
        parser.error(str(exc))

    if args.show_command:
        print("$ " + shlex.join(spec.argv()), file=sys.stderr)

    process = run_process(spec)
    if process.stderr:
        print(process.stderr.rstrip(), file=sys.stderr)
    if process.returncode != 0:
        print(f"qpy-rsync-cli: rsync exited with status {process.returncode}", file=sys.stderr)
        return process.returncode

    try:
        parsed = parse_output(
            process.stdout,
            delete_enabled=profile.transfer.mirror_enabled,
        )
    except ValueError as exc:
        print(f"qpy-rsync-cli: could not parse rsync output: {exc}", file=sys.stderr)
        return 2
    print_result(profile, parsed, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
