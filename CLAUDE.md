# Bacteria Development Standards

**Last Updated**: 2026-04-12
**Maintained By**: GuillermoLB

**Name**: Bacteria
**Description**: A self-hosted AI operating system — a single, extensible Python backend that unifies trigger-based automations, scheduled workflows, and conversational agents under one infrastructure.
**Language**: Python 3.12

## Core Principles

1. **Specification First**: Never implement features without a written specification
2. **Specs Stay Current**: Feature specs must be updated in the same PR as behavior changes
3. **Validation Required**: Every implementation must be validated against its spec

## Spec Types

| Type | Purpose | Lifecycle |
|---|---|---|
| **Living specs** | Describe what the system does *now* | Updated when behavior changes — never left stale |
| **Decision records** | Capture *why* a decision was made | Immutable — superseded, never edited |

**Living specs**: `specs/architecture/architecture.md`, `specs/features/`
**Decision records**: `specs/architecture/decisions/`

> The `definition/` folder contains the original project definition documents (spec.md, definition.md). These are the source of truth for project intent and will be migrated into `specs/` incrementally.

## Workflow

**Phase 1 — Specify**: Read `specs/architecture/architecture.md`. Run `/spec-driven:status` to see existing specs. If no spec exists, create one before writing any code.

**Phase 2 — Plan**: For non-trivial work, outline the approach before implementing. Use `EnterPlanMode` or write a brief plan in the chat.

**Phase 3 — Implement**: Follow the spec. Check off acceptance criteria as you go.

**Phase 4 — Validate**: All criteria met? Update the feature spec to reflect current behavior. Record architectural decisions in `specs/architecture/decisions/`.

## File Organization

```
bacteria/
├── CLAUDE.md                       # This file — the map
├── definition/                     # Original project definition (spec.md, definition.md)
├── .claude/
│   └── settings.json               # Plugin and MCP configuration
├── specs/
│   ├── architecture/
│   │   ├── architecture.md         # Living: current system design
│   │   └── decisions/              # Immutable: ADR-style decision history
│   │       └── index.md            # Start here — lists all decisions
│   └── features/                   # Living: current feature behavior
│       └── [domain]/               # Organize by business domain
│           └── [feature].md
├── references/                     # Agent-legible: tool/library/convention distillations
└── src/
    └── bacteria/                   # Main Python package
        ├── api/                    # FastAPI routers, webhook endpoints, middleware
        ├── worker/                 # Worker loop, job dispatcher
        ├── scheduler/              # Cron scheduler
        ├── queue/                  # Job queue: enqueue, claim, complete, fail
        ├── workflows/              # Assembled workflow DAGs per use case
        ├── nodes/                  # Atomic processing units
        ├── agents/                 # Agent runners, BaseAgentRunner protocol
        ├── llms/                   # LLM client abstractions
        ├── tools/                  # Tool definitions available to agents
        ├── skills/                 # Markdown-based skill files
        ├── memory/                 # Short-term and long-term memory
        ├── context/                # Context hub: file system crawler
        ├── entities/               # Pydantic domain models
        ├── db/                     # DB connection, session factory
        ├── observability/          # Logging, tracing, metrics
        └── utils/                  # Shared helpers
```

## Quality Standards

- No dead code — remove commented code and unused imports
- Error handling — handle errors explicitly, don't silently fail
- Testing — critical paths must have tests
- Comments — explain "why", not "what"
- Inner layers (`entities`, `nodes`) never import from outer layers (`api`, `worker`)
- All swappable components implement a Protocol or ABC
- No circular imports

## When Specs Are Missing

If asked to implement without a spec: stop, create a draft spec, get approval, then implement. Exception: trivial changes (typos, formatting).

---

*Spec-driven development — keep this file short. Detailed guidance lives in `specs/` and plugin skills.*
