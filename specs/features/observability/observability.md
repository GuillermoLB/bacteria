# Feature: Observability

**Status**: Draft
**Owner**: GuillermoLB
**Last Updated**: 2026-04-21

## Purpose

Give operators visibility into what Bacteria is doing at runtime. This covers four concerns: structured logging, distributed tracing via correlation IDs, metrics, and error tracking. LLM agent execution gets its own dedicated tracing layer via Langfuse.

The observability module lives in `src/bacteria/observability/` and is a cross-cutting concern — it is imported by all other layers but never imports from them.

---

## Stack

| Concern | Tool | Rationale |
|---|---|---|
| Structured logging | `loguru` | Consensus across FastAPI+LLM projects (Langflow, Open WebUI); simpler async context than structlog |
| Tracing | OpenTelemetry (`opentelemetry-instrumentation-fastapi` + sqlalchemy + httpx) | Undisputed standard; mirrors Open WebUI's stack exactly |
| Metrics | `prometheus-client` | Standard for worker/queue systems (Celery, Dramatiq, Prefect); pairs with Grafana |
| Error tracking | `sentry-sdk` opt-in | Enabled via `SENTRY_DSN` env var; pattern from Dify and Langflow |
| LLM/agent tracing | `Langfuse` | Self-hostable, native Anthropic SDK support; used by Dify and Langflow |

---

## Structured Logging

### Library

`loguru` replaces stdlib `logging` across the entire codebase. All modules use:

```python
from loguru import logger
```

### Format

Two output modes controlled by `LOG_FORMAT` env var:

- `LOG_FORMAT=json` (production) — structured JSON, one object per line, suitable for log aggregation
- `LOG_FORMAT=text` (default/dev) — human-readable colored output

### Mandatory fields on every log line

| Field | Source | Description |
|---|---|---|
| `timestamp` | loguru | ISO 8601 |
| `level` | loguru | DEBUG, INFO, WARNING, ERROR |
| `module` | loguru | Python module name |
| `job_id` | context var | UUID of current job, if in job context |
| `trace_id` | context var | Same as job_id for job-scoped work; UUID for HTTP requests without a job |
| `queue` | context var | Job queue name, if in job context |
| `event_type` | context var | Job event_type, if in job context |
| `sender_id` | context var | User identifier from Event, if available |

### Context binding

Context fields are stored in Python `contextvars.ContextVar` and injected into every log line via a loguru patcher. This ensures all log lines within a job execution carry the same fields without passing them explicitly.

```python
# observability/context.py
from contextvars import ContextVar

_job_id: ContextVar[str | None] = ContextVar("job_id", default=None)
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_queue: ContextVar[str | None] = ContextVar("queue", default=None)
_event_type: ContextVar[str | None] = ContextVar("event_type", default=None)
_sender_id: ContextVar[str | None] = ContextVar("sender_id", default=None)

def bind_job(job: Job) -> None:
    _job_id.set(str(job.id))
    _trace_id.set(str(job.id))
    _queue.set(job.queue)
    _event_type.set(job.payload.get("event_type"))

def bind_event(event: Event) -> None:
    _sender_id.set(event.sender_id)

def clear() -> None:
    ...
```

Context is bound in `worker/_handle()` immediately after claiming a job, and cleared after completion or failure.

### Logging internals

Python has two logging systems that must be unified:

- **loguru** — used by all bacteria code (`from loguru import logger`). Simpler API, no per-module `getLogger()` boilerplate, supports keyword args, and prints local variable values on exceptions (`diagnose=True`).
- **stdlib `logging`** — used internally by SQLAlchemy, uvicorn, and every third-party library. They don't know about loguru.

`setup_logging()` (called once at startup) bridges them:

1. Removes loguru's default stderr handler and adds a single stdout sink in either JSON or text format.
2. Registers `_context_patcher` via `logger.configure(patcher=...)` — loguru calls this before writing every record, injecting `trace_id`, `job_id`, etc. from the `ContextVar`s automatically. No need to pass context to individual log calls.
3. Installs `_InterceptHandler` as the root stdlib handler. Any `logging.info(...)` call from a third-party library lands here and is re-emitted through loguru, preserving the original file and line number by walking up the call stack past logging internals.
4. Clears handlers on all known stdlib loggers so their output propagates to the root handler instead of being handled twice.

The result: all log output — from bacteria code and from third-party libraries — goes through one unified loguru pipeline with context fields injected on every line.

### Log coverage requirements

Every layer must log at these points:

**API layer**
- `INFO` — job enqueued (job_id, queue, event_type, payload size)
- `WARNING` — webhook signature verification failed (source IP, reason)
- `ERROR` — enqueue failure

**Queue layer**
- `DEBUG` — job claimed (job_id, attempts)
- `DEBUG` — job completed (job_id, duration_ms)
- `WARNING` — job failed, will retry (job_id, attempts, next_retry_at)
- `ERROR` — job permanently failed (job_id, error)
- `INFO` — stuck jobs released (count)

**Worker layer**
- `INFO` — worker started (concurrency, poll_interval)
- `DEBUG` — poll cycle, no jobs found
- `ERROR` — unregistered event_type (job_id, event_type)

**Node layer**
- `DEBUG` — node started (node_name, job_id)
- `DEBUG` — node completed (node_name, job_id, duration_ms)
- `ERROR` — node failed (node_name, job_id, error)

**Agent layer**
- `INFO` — agent run started (agent_provider, job_id)
- `INFO` — agent run completed (job_id, turns, input_tokens, output_tokens)
- `ERROR` — agent run failed (job_id, error)

---

## Correlation / Tracing

### Approach

Single-process system — no distributed tracing needed. Correlation is achieved by threading `job_id` as `trace_id` through the loguru context. All log lines for a single job share the same `trace_id`, making it trivial to reconstruct the full execution timeline from logs.

For HTTP requests that don't produce a job (health checks, list endpoints), a UUID `request_id` is generated at the middleware level and bound as `trace_id`.

### OpenTelemetry

OTel is used for **traces and metrics export only** — not for log shipping (stdout JSON collected separately is more stable than the OTel logging bridge).

Auto-instrumentation packages:

```
opentelemetry-instrumentation-fastapi
opentelemetry-instrumentation-sqlalchemy
opentelemetry-instrumentation-httpx
opentelemetry-exporter-otlp
```

These are enabled at startup if `OTEL_EXPORTER_OTLP_ENDPOINT` is set. If not set, OTel is a no-op — no startup failure.

---

## Metrics

### Exposition

`prometheus-client` exposes a `/metrics` endpoint on the FastAPI app. Prometheus scrapes this; Grafana visualizes it.

`prometheus-fastapi-instrumentator` provides automatic HTTP RED metrics (rate, errors, duration) on all routes with zero configuration.

### Custom metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `bacteria_jobs_enqueued_total` | Counter | `queue`, `event_type` | Jobs enqueued since startup |
| `bacteria_jobs_completed_total` | Counter | `queue`, `event_type` | Jobs completed successfully |
| `bacteria_jobs_failed_total` | Counter | `queue`, `event_type`, `permanent` | Jobs failed (permanent=true if exhausted) |
| `bacteria_job_duration_seconds` | Histogram | `queue`, `event_type` | End-to-end job execution time |
| `bacteria_queue_depth` | Gauge | `queue` | Current PENDING job count (polled every 30s) |
| `bacteria_worker_active` | Gauge | — | Number of currently executing workers |
| `bacteria_agent_tokens_total` | Counter | `provider`, `model`, `token_type` | LLM tokens used (token_type: input\|output) |
| `bacteria_agent_duration_seconds` | Histogram | `provider`, `model` | Agent run duration |

### Queue depth

Queue depth is a DB query — polled every 30 seconds by a background task, not on every request. The result is stored in the Gauge directly.

---

## Error Tracking

### Sentry (opt-in)

Enabled when `SENTRY_DSN` is set. Uses `sentry-sdk[fastapi]` with:
- `FastApiIntegration` — captures unhandled HTTP exceptions
- `SqlalchemyIntegration` — captures DB errors with query context
- Manual `sentry_sdk.capture_exception(e)` in worker `_handle()` after permanent job failure

If `SENTRY_DSN` is not set, the import is skipped — no startup error.

Compatible with self-hosted **Bugsink** or **Glitchtip** (Sentry-SDK protocol) — just point `SENTRY_DSN` at the self-hosted instance.

### Structured error logging

All exceptions are logged via loguru with full context regardless of Sentry. Sentry is additive, not a replacement.

---

## LLM / Agent Tracing

### Langfuse

`Langfuse` traces every agent execution. Self-hostable, no proxy required. Enabled when `LANGFUSE_SECRET_KEY` and `LANGFUSE_PUBLIC_KEY` are set.

Each agent run is wrapped with `@observe` or the Langfuse client directly:

```python
from langfuse.decorators import observe

@observe()
async def run_agent(ctx: Context) -> Context:
    ...
```

Langfuse captures:
- Input/output per agent turn
- Token usage per call
- Latency per turn and total
- Model and provider
- `job_id` passed as metadata for cross-referencing with logs

---

## Health Checks

Two endpoints on the FastAPI app:

- `GET /health` — always returns `200 {"status": "ok"}`. Used by Docker/load balancer liveness probes.
- `GET /ready` — checks DB connectivity. Returns `200` if DB is reachable, `503` otherwise. Used by readiness probes before routing traffic.

---

## Load Testing

External black-box performance testing is a separate concern from internal observability. The k6 → InfluxDB → Grafana pattern (as seen in `references/ai-python-test-main/`) can be used to measure end-to-end throughput under load.

This is tracked separately in `specs/features/observability/load-testing.md` (not yet written).

---

## Configuration

```python
class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OBSERVABILITY__")

    log_format: str = "text"           # "text" | "json"
    log_level: str = "INFO"

    sentry_dsn: str | None = None      # enables Sentry if set
    sentry_environment: str = "production"

    otel_endpoint: str | None = None   # enables OTel export if set

    langfuse_secret_key: str | None = None   # enables Langfuse if set
    langfuse_public_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    metrics_queue_poll_interval: int = 30    # seconds between queue depth polls
```

All observability features degrade gracefully — if credentials are missing, the feature is disabled, never a startup failure.

---

## Module Structure

```
src/bacteria/observability/
├── __init__.py         # setup_observability() called at startup
├── logging.py          # loguru configuration, JSON formatter, patcher
├── context.py          # contextvars: bind_job(), bind_event(), clear()
├── metrics.py          # prometheus-client metric definitions
├── tracing.py          # OTel setup, request_id middleware
├── sentry.py           # sentry-sdk initialization (no-op if DSN missing)
└── langfuse.py         # Langfuse client initialization
```

`setup_observability()` is called once at application startup before any routes or workers are registered.

---

## Acceptance Criteria

### Scenario 1: Log correlation

```
Given a job with id=abc-123 is claimed by the worker
When the worker runs the workflow (3 nodes + 1 agent call)
Then every log line emitted during that execution contains job_id=abc-123 and trace_id=abc-123
And filtering logs by trace_id=abc-123 returns the complete execution timeline
```

### Scenario 2: Job metrics

```
Given a job completes successfully
Then bacteria_jobs_completed_total increments by 1 with correct queue and event_type labels
And bacteria_job_duration_seconds records the execution duration
```

### Scenario 3: Permanent failure captured

```
Given a job exhausts all retry attempts
Then the job is logged at ERROR with full exception and context
And bacteria_jobs_failed_total increments with permanent=true
And if SENTRY_DSN is set, the exception is sent to Sentry with job_id as tag
```

### Scenario 4: Graceful degradation

```
Given SENTRY_DSN is not set
And LANGFUSE_SECRET_KEY is not set
And OTEL_EXPORTER_OTLP_ENDPOINT is not set
When the application starts
Then it starts successfully with no errors
And logging and metrics still work
```

### Scenario 5: Queue depth gauge

```
Given 10 PENDING jobs in the queue
When the queue depth poller runs
Then bacteria_queue_depth gauge is set to 10
And it is visible on the /metrics endpoint
```

### Scenario 6: Health and readiness

```
Given the application is running and DB is reachable
When GET /health is called
Then 200 {"status": "ok"} is returned

When GET /ready is called
Then 200 is returned

Given the DB is unreachable
When GET /ready is called
Then 503 is returned
```

---

## Dependencies

- `specs/features/queue/queue-and-worker.md` — Job lifecycle, retry logic
- `specs/features/workflows/workflow-engine.md` — Node and Context structure
- `specs/features/agents/agent.md` — AgentRunner protocol

---

## New Dependencies

```
loguru
prometheus-client
prometheus-fastapi-instrumentator
opentelemetry-instrumentation-fastapi
opentelemetry-instrumentation-sqlalchemy
opentelemetry-instrumentation-httpx
opentelemetry-exporter-otlp
sentry-sdk[fastapi]
langfuse
```
