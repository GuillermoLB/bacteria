# Feature: Queue and Worker

**Status**: Implemented
**Owner**: GuillermoLB
**Last Updated**: 2026-04-20

## Purpose

Define the job queue and worker loop — the central nervous system of bacteria. Every unit of work in the system, regardless of trigger (webhook, schedule, manual), is a job in this queue. The worker claims jobs and dispatches them to the right workflow.

---

## Job lifecycle

```
PENDING → CLAIMED → COMPLETED
                 └→ FAILED → (retry → PENDING | exhausted → FAILED permanently)
```

- **PENDING** — job is waiting to be picked up
- **CLAIMED** — a worker has claimed it and is executing it
- **COMPLETED** — workflow ran successfully
- **FAILED** — workflow raised an exception; retried up to `max_attempts`

---

## Schema

### `jobs` table

```sql
jobs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  queue         TEXT NOT NULL DEFAULT 'default',
  payload       JSONB NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending',
  priority      INT DEFAULT 0,
  attempts      INT DEFAULT 0,
  max_attempts  INT DEFAULT 3,
  scheduled_at  TIMESTAMPTZ,
  claimed_at    TIMESTAMPTZ,
  completed_at  TIMESTAMPTZ,
  failed_at     TIMESTAMPTZ,
  result        JSONB,
  error         TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
)
```

**Key fields:**

- `queue` — reserved for future multi-queue routing. Always `"default"` for now
- `scheduled_at` — NULL means run immediately; set by the scheduler for cron jobs
- `priority` — higher value = claimed first. Default 0
- `attempts` — incremented on each failure
- `max_attempts` — job is permanently failed when `attempts >= max_attempts`
- `error` — last exception message, for debugging

**Indexes:**

```sql
CREATE INDEX jobs_claim_idx ON jobs (status, priority DESC, created_at ASC)
  WHERE status = 'pending' AND (scheduled_at IS NULL OR scheduled_at <= now());
```

---

## Queue interface

The queue is a protocol — the worker depends on the interface, not the PostgreSQL implementation.

```python
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
```

### `claim_next` — the core query

```sql
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
```

`FOR UPDATE SKIP LOCKED` ensures multiple concurrent workers never claim the same job. Each worker atomically claims one job per call.

### `fail` — retry or exhaust

```python
async def fail(self, job: Job, error: str) -> None:
    if job.attempts >= job.max_attempts:
        # permanently failed
        UPDATE jobs SET status='failed', error=error, failed_at=now()
    else:
        # back to pending with exponential backoff
        backoff = min(30 * (2 ** job.attempts), 1800)  # 30s, 60s, 120s... cap 30min
        UPDATE jobs
        SET status='pending',
            error=error,
            scheduled_at=now() + interval '{backoff} seconds'
```

Retry uses exponential backoff — attempt 1 waits 30s, attempt 2 waits 60s, attempt 3 waits 120s. Capped at 30 minutes.

### `release_stuck` — visibility timeout

If a worker crashes mid-execution, the job stays `CLAIMED` forever. A periodic call to `release_stuck` resets these back to `PENDING`:

```sql
UPDATE jobs
SET status = 'pending', claimed_at = NULL
WHERE status = 'claimed'
  AND claimed_at < now() - interval '{stuck_after}'
```

Default stuck threshold: 10 minutes. Called by the worker on startup and periodically during the poll loop.

---

## Worker

### Structure

```python
class Worker:
    def __init__(
        self,
        queue: JobQueue,
        registry: WorkflowRegistry,
        concurrency: int = 5,
    ):
        self.queue = queue
        self.registry = registry
        self.concurrency = concurrency

    async def run(self) -> None:
        await self.queue.release_stuck(stuck_after=timedelta(minutes=10))
        await asyncio.gather(*[self._loop() for _ in range(self.concurrency)])

    async def _loop(self) -> None:
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
            await workflow.run(ctx)
            await self.queue.complete(job)
        except Exception as e:
            await self.queue.fail(job, error=str(e))
```

### Concurrency model

- One OS process, `concurrency` asyncio coroutines running concurrently
- Concurrency is I/O bound — correct for DB queries, LLM API calls, webhook delivery
- Configured via `WORKER__CONCURRENCY` env var, default 5
- All coroutines share one DB connection pool

### Poll interval

- When no jobs are available, each coroutine sleeps `WORKER__POLL_INTERVAL` seconds
- Default: 5 seconds
- Configured via env var — lower for lower latency, higher to reduce DB load

---

## Workflow registry

The registry maps `event_type` to a `Workflow` instance. The worker looks up the right workflow per job.

```python
class WorkflowRegistry:
    def __init__(self):
        self._registry: dict[str, Workflow] = {}

    def register(self, event_type: str, workflow: Workflow) -> None:
        self._registry[event_type] = workflow

    def get(self, event_type: str) -> Workflow:
        workflow = self._registry.get(event_type)
        if not workflow:
            raise UnregisteredEventType(event_type)
        return workflow
```

Workflows are registered at startup in `dependencies.py`:

```python
registry = WorkflowRegistry()
registry.register("whatsapp.message",   whatsapp_webhook_workflow)
registry.register("whatsapp.agent",     agent_request_workflow)
registry.register("schedule.report",    daily_report_workflow)
```

Event types follow `{source}.{event}` naming convention.

---

## Settings

```python
class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKER__")
    concurrency: int = 5
    poll_interval: int = 5        # seconds
    stuck_threshold: int = 600    # seconds (10 minutes)
```

---

## Multi-queue evolution

The `queue` column is in the schema from day one. When load requires separate worker pools per queue:

1. Add `WORKER__QUEUES=webhooks,agents,scheduled` config
2. `claim_next` filters by queue name
3. Deploy separate worker processes per queue with different concurrency settings

No schema migration needed — the column already exists.

---

## Acceptance Criteria

### Scenario 1: Happy path

```
Given a PENDING job in the queue
When the worker polls
Then the job is claimed atomically (no other worker can claim it)
And the workflow runs
And the job is marked COMPLETED with the result
```

### Scenario 2: Concurrent workers never double-claim

```
Given 5 concurrent worker coroutines polling the same queue
And 5 PENDING jobs
When all coroutines poll simultaneously
Then each job is claimed by exactly one coroutine
And no job is executed twice
```

### Scenario 3: Failed job retries with backoff

```
Given a job with max_attempts=3
When the workflow raises an exception on attempt 1
Then the job is marked PENDING with scheduled_at = now() + 30s
And attempts = 1, error = exception message

When the workflow raises again on attempt 2
Then scheduled_at = now() + 60s, attempts = 2

When the workflow raises again on attempt 3
Then the job is marked FAILED permanently, attempts = 3
```

### Scenario 4: Stuck job recovery

```
Given a job stuck in CLAIMED for more than 10 minutes
When release_stuck runs
Then the job is reset to PENDING with claimed_at = NULL
And the worker picks it up on the next poll
```

### Scenario 5: Unregistered event type

```
Given a job with event_type = "unknown.event"
When the worker dispatches it
Then WorkflowRegistry raises UnregisteredEventType
And the job is marked FAILED with a clear error message
```

---

## Dependencies

- `specs/features/scaffold/project-scaffold.md` — module structure
- `specs/features/workflows/workflow-engine.md` — Workflow and Context building blocks

---

**Status History**: Draft (2026-04-14) → Implemented (2026-04-20)
