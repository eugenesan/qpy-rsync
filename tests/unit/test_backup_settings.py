import pytest

from qpy_rsync.core.models import BackupOptions
from qpy_rsync.gui.backup_settings import decode_backup, encode_backup


def test_backup_settings_round_trip() -> None:
    options = BackupOptions(directory="/recovery", protect_nested=False)
    assert decode_backup(encode_backup(options)) == options


def test_empty_backup_settings_use_safe_defaults() -> None:
    assert decode_backup("") == BackupOptions()


def test_backup_settings_reject_non_object() -> None:
    with pytest.raises(ValueError, match="object"):
        decode_backup('["/recovery"]')
