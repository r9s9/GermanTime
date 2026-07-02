"""DB backup: zip a consistent snapshot, keep the last 8.

Uses sqlite3's online backup API rather than copying germantime.db
directly — the DB runs in WAL mode, so recent commits can still be
sitting in the -wal sidecar file; a raw file copy wouldn't be corrupt,
but could silently miss the last few minutes of writes. .backup() drains
the WAL into the snapshot properly.
"""

import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from .. import config

KEEP = 8
_NAME_PREFIX = "germantime_"


def create_backup() -> Path:
    config.ensure_dirs()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_db = config.BACKUP_DIR / f"_tmp_{timestamp}.db"
    dest = config.BACKUP_DIR / f"{_NAME_PREFIX}{timestamp}.zip"

    src = sqlite3.connect(str(config.DB_PATH))
    try:
        dst = sqlite3.connect(str(tmp_db))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(tmp_db, "germantime.db")
    tmp_db.unlink()

    _prune_old_backups()
    return dest


def _prune_old_backups() -> None:
    backups = sorted(config.BACKUP_DIR.glob(f"{_NAME_PREFIX}*.zip"), key=lambda p: p.name)
    for old in backups[:-KEEP]:
        old.unlink()


def list_backups() -> list[dict]:
    backups = sorted(config.BACKUP_DIR.glob(f"{_NAME_PREFIX}*.zip"), key=lambda p: p.name, reverse=True)
    return [
        {"name": p.name, "size_bytes": p.stat().st_size,
         "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()}
        for p in backups
    ]


def maybe_daily_backup() -> Path | None:
    """Called once at startup — creates a backup only if none exists yet
    for today, so restarting the app repeatedly doesn't spam backups."""
    if not config.DB_PATH.exists():
        return None
    today = datetime.now().strftime("%Y%m%d")
    config.ensure_dirs()
    if any(config.BACKUP_DIR.glob(f"{_NAME_PREFIX}{today}_*.zip")):
        return None
    return create_backup()
