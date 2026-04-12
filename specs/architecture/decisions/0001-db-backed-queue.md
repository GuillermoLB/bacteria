# Decision: Use a DB-backed job queue instead of Redis + Celery

**Number**: 0001
**Status**: Accepted
**Date**: 2026-04-12
**Author**: GuillermoLB

> Decision records are immutable. Do not edit after acceptance.
> If this decision is superseded, mark it `Status: Superseded by [link]` and create a new record.

## Context

The reference architecture (from the source video) used Redis + Celery + Celery Beat for job queuing and scheduling. This introduces two additional infrastructure dependencies (Redis, Celery) on top of PostgreSQL, which is already required for application data.

Redis is volatile by default — jobs can be lost if Redis restarts without explicit persistence configuration. Inspecting in-flight job state requires external tooling. Retry logic lives in Celery configuration rather than plain code.

## Decision

Use a PostgreSQL-backed job queue instead of Redis + Celery. Workers poll using `SELECT ... FOR UPDATE SKIP LOCKED` — the standard pattern for concurrent queue consumers without race conditions or external brokers. Scheduling is handled by a lightweight custom Scheduler component that reads cron definitions from the DB and inserts `PENDING` jobs.

## Consequences

**Positive**:
- Always durable — jobs survive process restarts by definition
- Full observability with `SELECT * FROM jobs` — no external tooling needed
- Retry logic is plain SQL (`UPDATE jobs SET status = 'pending'`)
- One fewer infrastructure dependency (no Redis, no Celery)
- Queue state is queryable, auditable, and joinable with application data

**Trade-offs**:
- Lower raw throughput than an in-memory broker (acceptable for this use case)
- `SELECT FOR UPDATE SKIP LOCKED` requires PostgreSQL 9.5+ (not a real constraint)
- Custom implementation to maintain rather than a battle-tested library

## Related

- Supersedes: (none)
- Related specs: `specs/architecture/architecture.md`
