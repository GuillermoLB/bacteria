import asyncio
import time
from datetime import timedelta

from loguru import logger

from bacteria.entities.context import Context
from bacteria.entities.job import Job
from bacteria.observability import context as obs_ctx
from bacteria.observability.metrics import job_duration, jobs_completed, jobs_failed, worker_active
from bacteria.observability.sentry import capture_exception
from bacteria.queue import JobQueue
from bacteria.settings import get_settings
from bacteria.worker.exceptions import PermanentFailure
from bacteria.worker.registry import WorkflowRegistry


class Worker:
    def __init__(
        self,
        queue: JobQueue,
        registry: WorkflowRegistry,
        concurrency: int = 5,
    ) -> None:
        self.queue = queue
        self.registry = registry
        self.concurrency = concurrency

    async def run(self) -> None:
        settings = get_settings()
        stuck = timedelta(seconds=settings.worker.stuck_threshold)
        await self.queue.release_stuck(stuck_after=stuck)
        logger.info(
            "Worker started",
            concurrency=self.concurrency,
            poll_interval=settings.worker.poll_interval,
        )
        await asyncio.gather(*[self._loop() for _ in range(self.concurrency)])

    async def _loop(self) -> None:
        settings = get_settings()
        while True:
            job = await self.queue.claim_next()
            if job:
                await self._handle(job)
            else:
                logger.debug("Poll cycle: no jobs found")
                await asyncio.sleep(settings.worker.poll_interval)

    async def _handle(self, job: Job) -> None:
        obs_ctx.bind_job(job)
        if job.payload.get("event") and hasattr(job.payload["event"], "sender_id"):
            obs_ctx.bind_event(job.payload["event"])

        event_type = job.payload.get("event_type", "unknown")
        started_at = time.monotonic()
        worker_active.inc()

        try:
            workflow = self.registry.get(job.payload["event_type"])
            ctx = Context(job=job)
            ctx = await workflow.run(ctx)
            result = {"agent_result": ctx.agent_result} if ctx.agent_result else None
            await self.queue.complete(job, result=result)
            duration = time.monotonic() - started_at
            jobs_completed.labels(queue=job.queue, event_type=event_type).inc()
            job_duration.labels(queue=job.queue, event_type=event_type).observe(duration)
        except PermanentFailure as e:
            duration = time.monotonic() - started_at
            logger.error("Job permanently failed: {}", str(e))
            capture_exception(e, job_id=str(job.id), event_type=event_type)
            job = job.model_copy(update={"attempts": job.max_attempts})
            await self.queue.fail(job, error=str(e))
            jobs_failed.labels(queue=job.queue, event_type=event_type, permanent="true").inc()
            job_duration.labels(queue=job.queue, event_type=event_type).observe(time.monotonic() - started_at)
        except Exception as e:
            logger.exception("Job failed: {}", str(e))
            await self.queue.fail(job, error=str(e))
            permanent = str(job.attempts >= job.max_attempts).lower()
            jobs_failed.labels(queue=job.queue, event_type=event_type, permanent=permanent).inc()
            job_duration.labels(queue=job.queue, event_type=event_type).observe(time.monotonic() - started_at)
        finally:
            worker_active.dec()
            obs_ctx.clear()
