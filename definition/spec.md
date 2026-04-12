# Bacteria — Formal Project Specification

## 1. Vision

Bacteria is a self-hosted AI operating system: a single, extensible Python backend that unifies **trigger-based automations**, **scheduled workflows**, and **conversational agents** under one infrastructure. New capabilities are added as workflows — not as separate deployments.

The name reflects the design philosophy: small, self-contained units that compose into complex living systems.

---

## 2. Computing Paradigm

The system treats AI as a new computing primitive. Each request flows through:

```
Multi-modal input (text, voice, image, webhook payload)
  → Memory (short-term + long-term)
  → LLMs
  → Sub-agents + Skills
  → Tools / MCP servers / Computer use
  → Files (structured DB + unstructured file system)
```

This is not a chatbot wrapper. It is infrastructure.

---

## 3. The Three Layers

### Layer 1 — Trigger-Based Actions
**Pattern:** When X happens, do Y.

- Incoming webhooks from external systems (WhatsApp, email, forms, YouTube, meetings, etc.)
- FastAPI endpoints receive and verify payloads
- Events are immediately persisted to the database (never lost)
- Processing is dispatched asynchronously to the Worker via the Job Queue

### Layer 2 — Scheduled Workflows
**Pattern:** Every Tuesday at 9 AM, do Y.

- Cron-style scheduling managed by the Scheduler component
- Triggers follow the exact same execution path as Layer 1 (persisted event → worker)
- Examples: daily reports, CRM sync, competitive analysis, data recovery jobs

### Layer 3 — Agent Layer
**Pattern:** User sends a message → agent dynamically decides what to do.

- Conversational, user-invoked via chat interfaces (WhatsApp, Slack, Telegram, Claude Code, etc.)
- Same infrastructure as Layer 1 (webhook in → persist → worker) but the worker runs an AI agent instead of a deterministic function
- Agents can themselves trigger Layer 1 webhooks or Layer 2 scheduled jobs

All three layers share the same infrastructure. They differ only in their trigger mechanism and processing step.

---

## 4. Architecture

### 4.1 Deployment

Single repository, single Docker Compose deployment. No microservices until genuinely needed.

```
Internet (webhooks, API calls)
  → Caddy (reverse proxy + HTTPS)
    → FastAPI (HTTP API)
      ├── Beat Scheduler  (cron triggers)
      └── Job Queue (DB-backed, custom)
            → Workers
              ├── PostgreSQL
              ├── External APIs
              ├── AI Runtime (agent SDK, LLM providers)
              └── Context Hub (file system)
```

### 4.2 Core Architectural Patterns

| Pattern | Application |
|---|---|
| **Event-Driven Architecture (EDA)** | Decouple API intake from processing. Accept fast, persist immediately, process in background. |
| **Dependency Injection** | All components receive their dependencies externally. Enables proper mocking and testing. |
| **Clean Architecture** (conceptual) | Domain / Application / Infrastructure / Serving as mental layers — never as folder names. |
| **Chain of Responsibility** | Workflows are composed as DAG-based node chains. Each node receives input, transforms it, passes output forward. |
| **Protocol / ABC interfaces** | Swappable components (LLM providers, job queues, storage) behind abstract interfaces. |

### 4.3 Key Design Decisions vs. Source Reference

| Area | Original (video) | Bacteria |
|---|---|---|
| Task queue | Redis + Celery + Celery Beat | **Custom DB-backed queue + Worker + Scheduler** |
| Agent provider | Claude Agent SDK only | **Provider-agnostic** (Claude SDK, Pydantic AI, raw LLM API, etc.) |
| Queue persistence | Redis (in-memory, volatile) | **PostgreSQL** (durable, queryable, auditable) |
| Scheduling | Celery Beat | **Custom Scheduler component** reading from DB |

---

## 5. The Custom Queue-Worker System

This is the central departure from the reference architecture. Instead of Redis + Celery, Bacteria uses a **database-backed job queue**.

### 5.1 Job Lifecycle

```
PENDING → CLAIMED → RUNNING → COMPLETED
                           └→ FAILED → (retry → PENDING)
```

### 5.2 Jobs Table (PostgreSQL)

```sql
jobs (
  id            UUID PRIMARY KEY,
  queue         TEXT NOT NULL,          -- logical queue name (e.g. "webhooks", "agents", "scheduled")
  payload       JSONB NOT NULL,
  status        TEXT NOT NULL,          -- pending | claimed | running | completed | failed
  priority      INT DEFAULT 0,
  attempts      INT DEFAULT 0,
  max_attempts  INT DEFAULT 3,
  scheduled_at  TIMESTAMPTZ,            -- NULL = run immediately; set for scheduled jobs
  claimed_at    TIMESTAMPTZ,
  completed_at  TIMESTAMPTZ,
  result        JSONB,
  error         TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
)
```

### 5.3 Worker Loop

Workers poll the queue using `SELECT ... FOR UPDATE SKIP LOCKED` — the standard PostgreSQL pattern for concurrent queue consumers without race conditions or external brokers.

```
loop:
  job = SELECT FROM jobs
        WHERE status = 'pending'
          AND (scheduled_at IS NULL OR scheduled_at <= now())
        ORDER BY priority DESC, created_at ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED

  if job:
    mark job CLAIMED
    execute handler(job.payload)
    mark job COMPLETED or FAILED
  else:
    sleep(poll_interval)
```

Multiple workers can run concurrently — the `SKIP LOCKED` clause ensures each job is processed exactly once without coordination overhead.

### 5.4 Scheduler Component

The Scheduler is a lightweight process that reads cron definitions from the DB and inserts `PENDING` jobs with a `scheduled_at` timestamp on the appropriate cadence. It does not execute work itself — it is only a trigger injector.

```
schedules (
  id          UUID PRIMARY KEY,
  name        TEXT NOT NULL,
  cron_expr   TEXT NOT NULL,    -- standard cron expression
  queue       TEXT NOT NULL,
  payload     JSONB NOT NULL,
  enabled     BOOL DEFAULT true,
  last_run_at TIMESTAMPTZ,
  next_run_at TIMESTAMPTZ
)
```

### 5.5 Why DB-Backed vs. Redis + Celery

| Concern | Redis + Celery | DB Queue |
|---|---|---|
| Durability | Volatile unless persisted explicitly | Always durable |
| Observability | External tooling needed | `SELECT * FROM jobs` — full history |
| Debuggability | Hard to inspect in-flight state | Queryable at any point |
| Retry logic | Celery config | Plain SQL update |
| Dependencies | Redis + Celery + Celery Beat | PostgreSQL (already required) |
| Throughput | Higher (in-memory) | Sufficient for this use case |

---

## 6. Webhook Flow (Layer 1)

```
POST /webhooks/{source}
  1. Verify signature       → reject if invalid (401)
  2. Parse payload          → source-specific parser
  3. Persist to DB          → Event(status=pending), never lose data
  4. Enqueue job            → INSERT INTO jobs (queue='webhooks', payload=event.id, ...)
  5. Return 202 Accepted    → fast response, async processing
```

Worker picks up the job, executes the workflow handler for that source/event type.

---

## 7. Agent Flow (Layer 3)

```
Incoming message (WhatsApp, Slack, etc.)
  → POST /webhooks/{platform}  [same as Layer 1]
  → Verify + Persist + Enqueue (queue='agents')
  → Worker: run AI agent
      ├── Load identity (soul.md)
      ├── Load task instructions
      ├── Resolve tools
      └── Execute via agent provider (pluggable)
  → Send reply via platform API
```

Agent providers are abstracted behind a `BaseAgentRunner` protocol, allowing any of:
- Claude Agent SDK (subprocess)
- Pydantic AI
- Direct LLM API + tool loop
- LangGraph

---

## 8. Workflow Engine

Workflows are DAG-based chains of nodes. Each node is an atomic unit:

```python
class Node(Protocol):
    async def run(self, ctx: Context) -> Context: ...
```

A workflow assembles nodes and defines edges:

```
WebhookReceivedNode
  → VerifySignatureNode
  → ParsePayloadNode
  → EnrichContextNode
  → DispatchToAgentNode
  → SendReplyNode
```

Context flows through the chain. Nodes are independent, testable, and reusable across workflows.

---

## 9. Project Structure

```
bacteria/
├── pyproject.toml
├── Makefile
├── docker-compose.yml
├── configs/              # Environment-specific config, model params
├── scripts/              # One-off admin/migration scripts
├── tests/
└── src/
    └── bacteria/
        ├── api/          # FastAPI routers, webhook endpoints, middleware
        ├── worker/       # Worker loop, job dispatcher, worker registry
        ├── scheduler/    # Cron scheduler, schedule definitions
        ├── queue/        # Job queue: enqueue, claim, complete, fail
        ├── workflows/    # Assembled workflow DAGs per use case
        ├── nodes/        # Atomic processing units (one task per node)
        ├── agents/       # Agent runners, BaseAgentRunner protocol, provider adapters
        ├── llms/         # LLM client abstractions (BaseLLM, provider adapters)
        ├── tools/        # Tool definitions available to agents
        ├── skills/       # Markdown-based skill files loaded into agent context
        ├── memory/       # Short-term (conversation) and long-term (DB/file) memory
        ├── context/      # Context hub: file system crawler, tiered loading
        ├── entities/     # Pydantic domain models (Job, Event, Schedule, etc.)
        ├── db/           # DB connection, session factory, base models
        ├── observability/# Logging, tracing, metrics (Sentry, Grafana)
        └── utils/        # Shared helpers
```

**Rules:**
- Organize by **functionality**, never by layer name (`domain/`, `application/`, `infrastructure/`)
- Inner layers (entities, nodes) never import from outer layers (api, worker)
- All swappable components (LLM, agent runner, storage) implement a Protocol or ABC
- No circular imports

---

## 10. Context Hub

A structured file system that agents can navigate, version-controlled separately (or as a sub-directory). Uses a **tiered loading** system to keep context windows lean:

```
context/
├── identity/         # Who we are: mission, values, goals (soul.md lives here)
├── inbox/            # Temporary: ideas, TODOs — always processed, never accumulates
├── areas/            # Ongoing domains: content, clients, products, health...
├── projects/         # Active time-bounded work
├── knowledge/        # SOPs, research, reference docs
└── archive/          # Completed/inactive — agents skip by default
```

Every folder contains:
- `abstract.md` — one line: what is this folder (scanned at level 0, ~2000 tokens for the whole hub)
- `overview.md` — short description: what is here, which workflows use it, relationships
- Full files — only loaded when the agent determines they are needed

Agents navigate: abstract → overview → full file. They never blindly crawl.

---

## 11. Security

- All webhook endpoints validate signatures before any processing
- No secrets in code — environment variables only
- Workers run with minimal privileges
- Agent runners have configurable budget caps (`max_turns`, `max_cost`)
- All events and job results are logged and auditable via the DB

---

## 12. Observability

- **Sentry**: error tracking and alerting for all worker failures and agent errors
- **Grafana**: server health, job queue depth, worker throughput, latency
- **DB audit trail**: every job, event, and schedule run is persisted with status and result
- Structured logging throughout (JSON, correlation IDs on all jobs)

---

## 13. CI/CD

- Push to `main` → GitHub Actions pipeline → Docker build + deploy → Slack notification
- All deployments are zero-downtime (rolling workers, Caddy stays up)

---

## 14. What This Is Not

- Not a Celery clone — the queue is simpler, more observable, and requires no additional infrastructure
- Not a LangChain/CrewAI wrapper — agent frameworks are adapters, not the foundation
- Not microservices — one deployment, one repo, until the complexity genuinely demands otherwise
- Not a weekend script — built to be extended incrementally without rebuilding

---

## 15. Glossary

| Term | Definition |
|---|---|
| **Job** | A unit of work in the queue. Has a payload, status, queue name, and retry logic. |
| **Event** | An incoming external signal (webhook, schedule trigger). Persisted before a Job is created. |
| **Worker** | A process that polls the queue, claims jobs, and executes handlers. |
| **Scheduler** | A process that reads cron schedules from DB and inserts jobs at the right time. |
| **Workflow** | A DAG of Nodes assembled to handle a specific use case. |
| **Node** | An atomic, single-responsibility processing unit within a Workflow. |
| **Agent Runner** | A pluggable adapter that executes an AI agent (Claude SDK, Pydantic AI, etc.). |
| **Skill** | A markdown file describing a capability. Loaded into agent context. |
| **Context Hub** | The structured file system that agents use as long-term knowledge. |
| **Soul** | `soul.md` — the identity file loaded at the start of every agent system prompt. |
