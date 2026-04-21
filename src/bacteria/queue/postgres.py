from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bacteria.entities.job import Job


def _row_to_job(row) -> Job:
    return Job(
        id=row.id,
        queue=row.queue,
        payload=row.payload,
        status=row.status,
        priority=row.priority,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        scheduled_at=row.scheduled_at,
        claimed_at=row.claimed_at,
        completed_at=row.completed_at,
        failed_at=row.failed_at,
        result=row.result,
        error=row.error,
        created_at=row.created_at,
    )


class PostgresJobQueue:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def enqueue(
        self,
        payload: dict,
        queue: str = "default",
        priority: int = 0,
        scheduled_at: datetime | None = None,
        max_attempts: int = 3,
    ) -> Job:
        async with self._engine.connect() as conn:
            row = (await conn.execute(
                text("""
                    INSERT INTO jobs (queue, payload, status, priority, scheduled_at, max_attempts)
                    VALUES (:queue, cast(:payload as jsonb), 'pending', :priority, :scheduled_at, :max_attempts)
                    RETURNING *
                """),
                {
                    "queue": queue,
                    "payload": _serialize(payload),
                    "priority": priority,
                    "scheduled_at": scheduled_at,
                    "max_attempts": max_attempts,
                },
            )).one()
            await conn.commit()
        return _row_to_job(row)

    async def claim_next(self) -> Job | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(text("""
                UPDATE jobs
                SET status = 'claimed', claimed_at = now(), attempts = attempts + 1
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE status = 'pending'
                      AND (scheduled_at IS NULL OR scheduled_at <= now())
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
            """))).one_or_none()
            await conn.commit()
        return _row_to_job(row) if row else None

    async def complete(self, job: Job, result: dict | None = None) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(
                text("""
                    UPDATE jobs
                    SET status = 'completed', completed_at = now(), result = cast(:result as jsonb)
                    WHERE id = :id
                """),
                {"id": job.id, "result": _serialize(result or {})},
            )
            await conn.commit()

    async def fail(self, job: Job, error: str) -> None:
        async with self._engine.connect() as conn:
            if job.attempts >= job.max_attempts:
                await conn.execute(
                    text("""
                        UPDATE jobs
                        SET status = 'failed', error = :error, failed_at = now()
                        WHERE id = :id
                    """),
                    {"id": job.id, "error": error},
                )
            else:
                backoff = min(30 * (2 ** job.attempts), 1800)
                await conn.execute(
                    text("""
                        UPDATE jobs
                        SET status = 'pending',
                            error = :error,
                            scheduled_at = now() + :backoff * interval '1 second'
                        WHERE id = :id
                    """),
                    {"id": job.id, "error": error, "backoff": backoff},
                )
            await conn.commit()

    async def release_stuck(self, stuck_after: timedelta) -> int:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text("""
                    UPDATE jobs
                    SET status = 'pending', claimed_at = NULL
                    WHERE status = 'claimed'
                      AND claimed_at < now() - :stuck_after * interval '1 second'
                """),
                {"stuck_after": int(stuck_after.total_seconds())},
            )
            await conn.commit()
        return result.rowcount


def _serialize(data: dict) -> str:
    import json
    return json.dumps(data, default=str)
