from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from bacteria.db import get_engine
from bacteria.dependencies import get_job_queue

router = APIRouter(prefix="/jobs", tags=["jobs"])


class EnqueueRequest(BaseModel):
    event_type: str
    queue: str = "default"
    payload: dict = {}
    priority: int = 0
    max_attempts: int = 3


class JobSummary(BaseModel):
    id: UUID
    queue: str
    event_type: str | None
    status: str
    priority: int
    attempts: int
    max_attempts: int
    created_at: datetime
    claimed_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    error: str | None
    result: dict | None


@router.post("", status_code=202, summary="Enqueue a job")
async def enqueue_job(body: EnqueueRequest):
    queue = get_job_queue() # TODO: a fastapi dependency??
    job = await queue.enqueue(
        payload={"event_type": body.event_type, **body.payload},
        queue=body.queue,
        priority=body.priority,
        max_attempts=body.max_attempts,
    )
    return {"id": str(job.id), "status": job.status}


@router.get("", response_model=list[JobSummary], summary="List recent jobs")
async def list_jobs(limit: int = 50, status: str | None = None):
    async with get_engine().connect() as conn:
        query = "SELECT * FROM jobs"
        params = {}
        if status:
            query += " WHERE status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit
        rows = (await conn.execute(text(query), params)).fetchall()

    return [
        JobSummary(
            id=row.id,
            queue=row.queue,
            event_type=row.payload.get("event_type") if row.payload else None,
            status=row.status,
            priority=row.priority,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            created_at=row.created_at,
            claimed_at=row.claimed_at,
            completed_at=row.completed_at,
            failed_at=row.failed_at,
            error=row.error,
            result=row.result,
        )
        for row in rows
    ]
