"""Manual backup trigger + listing. Automatic daily backup runs from
main.py's startup instead (see services/backup.maybe_daily_backup)."""

from fastapi import APIRouter

from ..services import backup

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("")
def list_backups() -> dict:
    return {"backups": backup.list_backups()}


@router.post("")
def create_backup() -> dict:
    path = backup.create_backup()
    return {"name": path.name}
