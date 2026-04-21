import asyncio
import logging
from datetime import timedelta

from bacteria.entities.context import Context
from bacteria.entities.job import Job
from bacteria.queue import JobQueue
from bacteria.settings import get_settings
from bacteria.worker.exceptions import PermanentFailure
from bacteria.worker.registry import WorkflowRegistry

logger = logging.getLogger(__name__)


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
        await asyncio.gather(*[self._loop() for _ in range(self.concurrency)])

    async def _loop(self) -> None:
        settings = get_settings()
        while True:
            job = await self.queue.claim_next()
            if job:
                await self._handle(job)
            else:
                await asyncio.sleep(settings.worker.poll_interval)

    async def _handle(self, job: Job) -> None:
        try:
            workflow = self.registry.get(job.payload["event_type"])
            ctx = Context(job=job)
            ctx = await workflow.run(ctx)
            result = {"agent_result": ctx.agent_result} if ctx.agent_result else None
            await self.queue.complete(job, result=result)
        except PermanentFailure as e:
            logger.error("Job %s permanently failed: %s", job.id, e)
            # Force attempts to max so queue.fail() skips retry
            job = job.model_copy(update={"attempts": job.max_attempts})
            await self.queue.fail(job, error=str(e))
        except Exception as e:
            logger.exception("Job %s failed: %s", job.id, e)
            await self.queue.fail(job, error=str(e))
