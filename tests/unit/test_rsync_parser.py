from pathlib import Path

import pytest

from qpy_rsync.backend.rsync_parser import RsyncParseError, parse_output, parse_record
from qpy_rsync.core.changes import ChangeAction, ObjectKind

FIXTURE = Path(__file__).parents[1] / "fixtures" / "rsync_output" / "basic.txt"


def test_parses_controlled_fixture() -> None:
    result = parse_output(FIXTURE.read_text())
    assert len(result.changes) == 5
    assert result.changes[0].action is ChangeAction.CREATE
    assert result.changes[1].action is ChangeAction.UPDATE_CONTENT
    assert result.changes[2].action is ChangeAction.UPDATE_METADATA
    assert result.changes[3].kind is ObjectKind.SYMLINK
    assert result.changes[3].link_target == "target"
    assert result.changes[4].action is ChangeAction.DELETE


def test_non_record_line_becomes_diagnostic() -> None:
    result = parse_output("sending incremental file list\n")
    assert result.changes == []
    assert result.diagnostics == ["sending incremental file list"]


def test_bad_size_is_rejected() -> None:
    with pytest.raises(RsyncParseError):
        parse_record(">f+++++++++\x1fnot-a-size\x1ftime\x1ffile")
