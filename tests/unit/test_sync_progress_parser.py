from qpy_rsync.backend.sync_progress import (
    is_rsync_summary_line,
    parse_sync_progress,
)


def test_parse_sync_progress() -> None:
    progress = parse_sync_progress(" (xfr#4, to-chk=3/8) ")
    assert progress is not None
    assert progress.files_completed == 4
    assert progress.files_remaining == 3
    assert progress.files_total == 8
    # The counter reports the files that are still to be checked, so five of
    # the eight files are done.
    assert progress.percent == 62


def test_parse_sync_progress_missing() -> None:
    assert parse_sync_progress("no progress here") is None


def test_parse_sync_progress_handles_the_incremental_counter() -> None:
    # A dry run walks the trees incrementally and never transfers a file.
    progress = parse_sync_progress(
        "              0   0%    0.00kB/s    0:00:00 (xfr#0, ir-chk=1017/1581)"
    )
    assert progress is not None
    assert progress.files_completed == 0
    assert progress.files_remaining == 1017
    assert progress.files_total == 1581
    assert progress.percent == 36

def test_only_summary_lines_are_kept_from_sync_output() -> None:
    assert is_rsync_summary_line("Number of files: 10")
    assert is_rsync_summary_line("sent 1,234 bytes  received 56 bytes")
    assert is_rsync_summary_line("rsync: failed: permission denied")
    assert not is_rsync_summary_line(">f+++++++++|qpy-rsync|8|qpy-rsync|2024/01/01|qpy-rsync|file.txt")
    assert not is_rsync_summary_line("  8 100%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)")
