"""Weekly report: generated on demand, cached per ISO week."""

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from ..db import get_db
from ..services import weekly_report

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/weekly/latest")
async def latest(db: Session = Depends(get_db)) -> dict:
    return await weekly_report.generate(db)
