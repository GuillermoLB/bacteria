from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class Job(BaseModel):
    id: UUID
    queue: str
    payload: dict
    status: str
    priority: int
    attempts: int
    max_attempts: int
    scheduled_at: datetime | None
    claimed_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    result: dict | None
    error: str | None
    created_at: datetime
