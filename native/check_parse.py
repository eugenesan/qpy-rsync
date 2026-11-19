"""Differential check: native parser vs Python parser on tricky records."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qpy_rsync.backend.rsync_parser import parse_record  # noqa: E402
from qpy_rsync.core.changes import ChangeAction, ObjectKind  # noqa: E402

from qpy_rsync import _qpy_native  # noqa: E402

SEP = "|qpy-rsync|"
RECORDS = [
    f">f+++++++++{SEP}10{SEP}2026/01/01-00:00:00{SEP}dir/new.txt",
    f">f.st......{SEP}20{SEP}2026/01/02-00:00:00{SEP}dir/updated.txt",
    f".d..t......{SEP}4096{SEP}2026/01/03-00:00:00{SEP}dir/",
    f"*deleting   {SEP}0{SEP}1970/01/01-00:00:00{SEP}dir/gone.txt",
    f"*deleting   {SEP}0{SEP}1970/01/01-00:00:00{SEP}emptydir/",
    f"cL+++++++++{SEP}5{SEP}2026/01/04-00:00:00{SEP}link -> target",
    f">f+++++++++{SEP}8{SEP}2026/01/05-00:00:00{SEP}.",
    f"not a record",
    f"garbage{SEP}1{SEP}t{SEP}name",
]
ACTION_CODES = {
    ChangeAction.CREATE: 0,
    ChangeAction.UPDATE_CONTENT: 1,
    ChangeAction.UPDATE_METADATA: 2,
    ChangeAction.DELETE: 4,
    ChangeAction.DESTINATION_ONLY: 5,
    ChangeAction.NO_CHANGE: 6,
}
KIND_CODES = {
    ObjectKind.FILE: 0,
    ObjectKind.DIRECTORY: 1,
    ObjectKind.SYMLINK: 2,
}


def main() -> None:
    stream = "\n".join(RECORDS) + "\n"
    native = _qpy_native.parse_records(stream, False)
    py_changes = []
    for line in RECORDS:
        try:
            change = parse_record(line, delete_enabled=False)
        except ValueError:
            change = None
        if change is not None:
            py_changes.append(change)
    assert len(native.paths) == len(py_changes), (len(native.paths), len(py_changes))
    for path, action, kind, code, change in zip(
        native.paths, native.actions, native.kinds, native.codes, py_changes
    ):
        assert path == change.path, (path, change.path)
        assert action == ACTION_CODES[change.action], (code, action, change.action)
        assert kind == KIND_CODES[change.kind], (code, kind, change.kind)
        assert code == change.itemized_code
    print(f"matched {len(py_changes)} records")


if __name__ == "__main__":
    main()
