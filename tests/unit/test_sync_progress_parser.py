from qpy_rsync.backend.sync_progress import parse_sync_progress


def test_parse_sync_progress() -> None:
    progress = parse_sync_progress(" (xfr#4, to-chk=3/8) ")
    assert progress is not None
    assert progress.files_completed == 4
    assert progress.files_remaining == 3
    assert progress.files_total == 8
    assert progress.percent == 57


def test_parse_sync_progress_missing() -> None:
    assert parse_sync_progress("no progress here") is None