from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bacteria.entities.job import Job
from bacteria.observability.metrics import jobs_enqueued


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

        job = _row_to_job(row)
        event_type = payload.get("event_type", "unknown")
        logger.info("Job enqueued", job_id=str(job.id), queue=queue, event_type=event_type)
        jobs_enqueued.labels(queue=queue, event_type=event_type).inc()
        return job

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

        if row is None:
            return None

        job = _row_to_job(row)
        logger.debug("Job claimed", job_id=str(job.id), attempts=job.attempts)
        return job

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
        logger.debug("Job completed", job_id=str(job.id))

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
                logger.error("Job permanently failed", job_id=str(job.id), error=error)
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
                logger.warning(
                    "Job failed, will retry",
                    job_id=str(job.id),
                    attempts=job.attempts,
                    backoff_seconds=backoff,
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

        count = result.rowcount
        if count:
            logger.info("Released stuck jobs", count=count)
        return count


def _serialize(data: dict) -> str:
    import json
    return json.dumps(data, default=str)
