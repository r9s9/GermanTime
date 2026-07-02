"""Content factory controls: queue status, manual run, and pre-fill upcoming topics."""

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from ..db import get_db
from ..services import factory

router = APIRouter(prefix="/api/factory", tags=["factory"])


@router.get("/status")
def status() -> dict:
    return factory.queue_status()


@router.post("/run")
async def run(limit: int = 10) -> dict:
    return await factory.run_queue(limit)


@router.post("/enqueue-upcoming")
def enqueue_upcoming(from_topic_id: str | None = None, n: int = 3, db: Session = Depends(get_db)) -> dict:
    jobs = factory.enqueue_upcoming(db, from_topic_id, n)
    return {"enqueued": len(jobs), "job_ids": [j.id for j in jobs]}
