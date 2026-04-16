# Decision: Single package — no uv workspace

**Number**: 0003
**Status**: Accepted
**Date**: 2026-04-12
**Author**: GuillermoLB

> Decision records are immutable. Do not edit after acceptance.
> If this decision is superseded, mark it `Status: Superseded by [link]` and create a new record.

## Context

uv supports workspaces — a collection of installable packages sharing a single lockfile. The question was whether to split bacteria into workspace members (e.g. `bacteria-shared`, `bacteria-api`, `bacteria-worker`, `bacteria-agents`).

Several splits were considered:

1. **By conceptual layer** (core / api / worker / agents) — rejected because layers are mental models, not deployment boundaries. This would force artificial splits and risk circular imports with no operational benefit.
2. **By process boundary** (shared + app) — closer to reasonable, but still premature. All processes (API, Worker, Scheduler) share the same codebase, deploy together via Docker Compose, and have no conflicting dependencies.

The project's own reference (`references/python-ai-project-structure.md`) states: *"Decouple only what is worth decoupling. Don't build abstractions for hypothetical future scenarios."*

## Decision

Keep a single package (`bacteria`) under `src/bacteria/` with a flat, functionality-scoped layout. No uv workspace.

## Consequences

**Positive**:
- No structural overhead — one `pyproject.toml`, one lockfile, one virtual environment
- Flat imports — no cross-package dependency management
- Easier to refactor module boundaries as the system evolves
- Consistent with the reference architecture's recommendation against premature abstraction

**Trade-offs**:
- Cannot isolate conflicting dependencies between components (not currently a problem)
- Cannot publish individual components as separate packages (not currently needed)

## When to revisit

Introduce a workspace if any of these become true:
- A component (e.g. `bacteria-agents`) needs to be consumed by an external project
- Two components develop genuinely conflicting dependency requirements
- A component needs independent versioning and release cycles

## Related

- Supersedes: (none)
- Related: `references/python-ai-project-structure.md`, `references/uv-workspaces.md`
