# Architecture: Bacteria

**Last Updated**: 2026-04-17
**Maintained By**: GuillermoLB

> This is a living document. It describes the *current* state of the system architecture.
> Update it when the structure changes — not for every PR.
> For *why* decisions were made, see `specs/architecture/decisions/`.
> The full original specification lives in `definition/spec.md`.

## Overview

Bacteria is a self-hosted AI operating system: a single Python backend that unifies trigger-based automations, scheduled workflows, and conversational agents. All three modes share the same infrastructure (FastAPI → Job Queue → Workers → PostgreSQL) and differ only in their trigger mechanism.

## Codemap

```
bacteria/
├── src/bacteria/
│   ├── api/            # FastAPI routers, webhook endpoints, signature verification, middleware
│   ├── worker/         # Worker poll loop, job dispatcher, handler registry
│   ├── scheduler/      # Cron scheduler — reads schedules from DB, injects PENDING jobs
│   ├── queue/          # Job queue: enqueue, claim (SELECT FOR UPDATE SKIP LOCKED), complete, fail
│   ├── workflows/      # Assembled DAG workflows per use case (webhook, agent, scheduled)
│   ├── nodes/          # Atomic Node units: VerifySignature, ParsePayload, DispatchToAgent, etc.
│   ├── agents/         # AgentRunner protocol + provider adapters (ClaudeAgentRunner, etc.)
│   ├── tools/          # Tool definitions exposed to agents
│   ├── skills/         # Markdown skill files loaded into agent context
│   ├── memory/         # Short-term (conversation) and long-term (DB/file) memory
│   ├── context/        # Context Hub: tiered file system loader (abstract → overview → full)
│   ├── entities/       # Pydantic domain models: Job, Event, Schedule, etc.
│   ├── db/             # DB connection, session factory, base models
│   ├── observability/  # Sentry, Grafana, structured logging, correlation IDs
│   └── utils/          # Shared helpers
├── definition/         # Original project definition documents (source of truth for intent)
├── specs/              # Specifications (this folder)
└── references/         # Agent-legible distillations of tools and conventions
```

**`api/`** — Receives all incoming traffic. Verifies webhook signatures, persists Events to DB, enqueues Jobs, returns 202 immediately. Never does processing.

**`worker/`** — Polls the jobs table using `SELECT FOR UPDATE SKIP LOCKED`. Claims jobs, dispatches to the right handler, marks COMPLETED or FAILED. Multiple workers run concurrently without coordination.

**`scheduler/`** — Lightweight process that reads the `schedules` table and inserts `PENDING` jobs with a `scheduled_at` timestamp. Does not execute work itself.

**`queue/`** — The job queue abstraction. Backed by PostgreSQL. Exposes enqueue, claim, complete, fail operations.

**`workflows/`** — DAG chains of Nodes. One workflow per use case (e.g. WhatsApp webhook, agent request, daily report).

**`nodes/`** — Atomic `async def run(ctx) -> ctx` units. Independent, testable, reusable across workflows.

**`agents/`** — `AgentRunner` protocol + concrete adapters per provider (`ClaudeAgentRunner`, etc.). Provider choice injected via `dependencies.py` — never referenced directly from workflows or nodes.

**`entities/`** — Pydantic models for Job, Event, Schedule. No business logic here.

## Architectural Invariants

- `entities/` and `nodes/` never import from `api/` or `worker/` — inner layers don't depend on outer layers
- `api/` never executes workflow logic — it only persists and enqueues
- `scheduler/` never executes jobs — it only inserts them
- All swappable components (`queue`) implement a Protocol or ABC — concrete implementations are never referenced directly from workflows
- `agents/` concrete runners are never imported outside `dependencies.py`
- No circular imports across any module

## Layer Boundaries

**API → Queue boundary**: The API layer accepts, verifies, persists, and enqueues. It never runs workflow code. All processing happens asynchronously in workers.
- Allowed: `api/` calls `queue/enqueue()` and `db/` for Event persistence
- Not allowed: `api/` calling `workflows/`, `agents/`, or `nodes/`

**Worker → Handler boundary**: Workers dispatch to registered handlers by queue name + event type. They don't know what the handler does.
- Allowed: Workers calling any registered handler
- Not allowed: Workers importing specific workflow implementations directly

**Inner → Outer boundary**: Domain models and nodes are the innermost layer.
- Allowed: `workflows/` importing `nodes/` and `entities/`
- Not allowed: `entities/` or `nodes/` importing from `api/`, `worker/`, `agents/`

## Cross-Cutting Concerns

- **Authentication**: Webhook signature verification in `api/middleware/` — runs before any handler
- **Error handling**: Workers catch exceptions, mark jobs FAILED, trigger retry logic in `queue/`
- **Logging / Observability**: Structured JSON logs with correlation IDs on all jobs; Sentry for errors; Grafana for queue depth and worker throughput — all in `observability/`
- **Configuration**: Environment variables only — no secrets in code

## Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.12 | |
| Build | uv | Package manager and build backend |
| Framework | FastAPI | HTTP API and webhook endpoints |
| Database | PostgreSQL | Job queue, events, schedules, audit trail |
| Infra | Docker Compose | Single-repo deployment |
| Reverse Proxy | Caddy | HTTPS termination |
| Observability | Sentry + Grafana | Error tracking + metrics |

## Architectural Decisions

| Decision | Record |
|---|---|
| DB-backed queue instead of Redis + Celery | `decisions/0001-db-backed-queue.md` |
| Provider-agnostic agent runners | `decisions/0002-provider-agnostic-agents.md` |

---

*Keep this short. A map of a country, not an atlas of its states.*
