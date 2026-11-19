"""Differential check: native parser vs Python parser, full Change equality.

Every field of every Change is compared, plus the error message for malformed
records. This is the oracle for Stage 4 of docs/native-backend-plan.md.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qpy_rsync import _qpy_native  # noqa: E402
from qpy_rsync.backend.rsync_parser import parse_record  # noqa: E402
from qpy_rsync.core.changes import ChangeAction, ObjectKind  # noqa: E402

SEP = "|qpy-rsync|"
ACTION_CODE = {
    action: index
    for index, action in enumerate(
        (
            ChangeAction.CREATE,
            ChangeAction.UPDATE_CONTENT,
            ChangeAction.UPDATE_METADATA,
            ChangeAction.DELETE,
            ChangeAction.DESTINATION_ONLY,
            ChangeAction.NO_CHANGE,
        )
    )
}
KIND_CODE = {
    kind: index
    for index, kind in enumerate(
        (
            ObjectKind.FILE,
            ObjectKind.DIRECTORY,
            ObjectKind.SYMLINK,
            ObjectKind.DEVICE,
            ObjectKind.SPECIAL,
            ObjectKind.UNKNOWN,
        )
    )
}


def record(code: str, size: str, time: str, name: str) -> str:
    return f"{code}{SEP}{size}{SEP}{time}{SEP}{name}"


RECORDS = [
    record(">f+++++++++", "10", "2026/01/01-00:00:00", "dir/new.txt"),
    record(">f.st......", "20", "2026/01/02-00:00:00", "dir/updated.txt"),
    record(".d..t......", "4096", "2026/01/03-00:00:00", "dir/"),
    record(">d+++++++++", "4096", "2026/01/03-00:00:00", "newdir/"),
    record("*deleting   ", "0", "1970/01/01-00:00:00", "dir/gone.txt"),
    record("*deleting   ", "0", "1970/01/01-00:00:00", "emptydir/"),
    record("cL+++++++++", "5", "2026/01/04-00:00:00", "link -> target/file"),
    record(">D..t......", "0", "2026/01/04-00:00:00", "dev/node"),
    record(">S..t......", "0", "2026/01/04-00:00:00", "sock/socket"),
    record(".f.........", "7", "2026/01/04-00:00:00", "nochange.txt"),
    record("<f..t......", "8", "2026/01/05-00:00:00", "received.txt"),
    record(">f+++++++++", "8", "2026/01/05-00:00:00", "."),
    record(">f+++++++++", "8", "2026/01/05-00:00:00", "./"),
    "an informational line",
    record("bad", "1", "t", "name"),
    record(">f+++++++++", "not-a-size", "t", "name"),
    record(">f+++++++++", "1", "t", ""),
]

FIELDS = (
    "path",
    "action",
    "kind",
    "itemized_code",
    "size",
    "modified_time",
    "link_target",
    "reason",
)


def as_dict(change: object) -> dict[str, object]:
    values = {field: getattr(change, field) for field in FIELDS}
    values["action"] = ACTION_CODE[values["action"]]
    values["kind"] = KIND_CODE[values["kind"]]
    return values


def main() -> None:
    stream = "\n".join(RECORDS) + "\n"
    native = _qpy_native.parse_records(stream, False)

    expected: list[dict[str, object]] = []
    expected_error = ""
    for line in RECORDS:
        try:
            change = parse_record(line.strip(), delete_enabled=False)
        except ValueError as exc:
            expected_error = str(exc)
            break
        if change is not None:
            expected.append(as_dict(change))

    assert native.error == expected_error, (native.error, expected_error)
    assert len(native.paths) == len(expected), (len(native.paths), len(expected))
    for index, change in enumerate(expected):
        actual = {
            "path": native.paths[index],
            "action": native.actions[index],
            "kind": native.kinds[index],
            "itemized_code": native.codes[index],
            "size": None if native.size_none[index] else native.sizes[index],
            "modified_time": native.times[index] or None,
            "link_target": native.link_targets[index] or None,
            "reason": native.reasons[index],
        }
        assert actual == change, (index, actual, change)

    # Deletions are validated with delete_enabled too.
    deleting = _qpy_native.parse_records(RECORDS[4] + "\n", True)
    py_delete = parse_record(RECORDS[4].strip(), delete_enabled=True)
    assert deleting.paths[0] == py_delete.path
    assert deleting.actions[0] == 3  # DELETE in the ChangeAction enum

    print(f"matched {len(expected)} records and the malformed-record error")


if __name__ == "__main__":
    main()
