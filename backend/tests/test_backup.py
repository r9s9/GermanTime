"""DB backup: online-snapshot creation, retention pruning, daily dedup."""

import zipfile

import pytest

from app import config
from app.services import backup


@pytest.fixture()
def backup_dir(db_session, tmp_path, monkeypatch):
    d = tmp_path / "backups"
    d.mkdir()
    monkeypatch.setattr(config, "BACKUP_DIR", d)
    return d


def test_create_backup_produces_a_valid_zip_with_the_db(backup_dir):
    path = backup.create_backup()
    assert path.exists()
    with zipfile.ZipFile(path) as zf:
        assert "germantime.db" in zf.namelist()
        assert zf.testzip() is None  # no corruption


def test_prune_keeps_only_the_last_8(backup_dir):
    for i in range(10):
        (backup_dir / f"germantime_2026010{i}_000000.zip").write_bytes(b"x")
    backup._prune_old_backups()
    remaining = sorted(backup_dir.glob("germantime_*.zip"))
    assert len(remaining) == 8
    # kept the newest-named 8, pruned the oldest 2
    assert remaining[0].name == "germantime_20260102_000000.zip"


def test_list_backups_sorted_newest_first(backup_dir):
    (backup_dir / "germantime_20260101_000000.zip").write_bytes(b"x")
    (backup_dir / "germantime_20260103_000000.zip").write_bytes(b"x")
    (backup_dir / "germantime_20260102_000000.zip").write_bytes(b"x")
    names = [b["name"] for b in backup.list_backups()]
    assert names == [
        "germantime_20260103_000000.zip", "germantime_20260102_000000.zip", "germantime_20260101_000000.zip",
    ]


def test_maybe_daily_backup_only_creates_one_per_day(backup_dir):
    first = backup.maybe_daily_backup()
    assert first is not None
    second = backup.maybe_daily_backup()
    assert second is None  # already have one for today


def test_maybe_daily_backup_noop_when_db_missing(backup_dir, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", backup_dir / "does_not_exist.db")
    assert backup.maybe_daily_backup() is None
