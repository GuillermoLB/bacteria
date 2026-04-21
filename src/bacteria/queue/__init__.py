from datetime import datetime, timedelta
from typing import Protocol

from bacteria.entities.job import Job


class JobQueue(Protocol):
    async def enqueue(
        self,
        payload: dict,
        queue: str = "default",
        priority: int = 0,
        scheduled_at: datetime | None = None,
        max_attempts: int = 3,
    ) -> Job: ...

    async def claim_next(self) -> Job | None: ...

    async def complete(self, job: Job, result: dict | None = None) -> None: ...

    async def fail(self, job: Job, error: str) -> None: ...

    async def release_stuck(self, stuck_after: timedelta) -> int: ...
