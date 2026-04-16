# Decision: No Separate `llms/` Module — LLM Access Lives in `agents/`

**Number**: 0004
**Status**: Accepted
**Date**: 2026-04-12
**Author**: GuillermoLB

> Decision records are immutable. Do not edit after acceptance.
> If this decision is superseded, mark it `Status: Superseded by [link]` and create a new record.

## Context

The project scaffold includes an `llms/` directory alongside `agents/`. A separate `llms/` module implies a boundary where some parts of the system call the LLM directly (without going through an agent runner), distinct from the higher-level `agents/` module that orchestrates multi-turn interactions.

No reference project, existing spec, or concrete use case in bacteria requires this separation today. The OpenClaw reference has no direct `llms/` equivalent — LLM access is owned by the agent runner abstraction. The `agents/` module is the correct home for all LLM interaction until a concrete case requires otherwise.

## Decision

Remove `llms/` as a separate top-level module. All LLM interaction goes through `agents/`.

Extract `llms/` only when a concrete case emerges: a `nodes/` DAG node that needs direct LLM access without a full agent runner (e.g. a classification step, a structured extraction node) and that access is meaningfully different from what `agents/` provides.

## Consequences

**Positive**:
- Avoids a premature abstraction boundary with no current use case
- Keeps the module count low and each module's purpose clear
- Follows the pattern from the reference analysis: `agents/` is the LLM interaction layer

**Trade-offs**:
- If a `nodes/` DAG step later needs lightweight LLM access, it will temporarily call into `agents/` at a higher level of abstraction than needed — this is the trigger for extraction

## When to revisit

Extract `llms/` when:
1. A `nodes/` workflow node needs direct LLM access (no session, no memory, no tools — just a completion or structured extraction)
2. That access pattern is meaningfully simpler than what `agents/` provides
3. Two or more nodes share this pattern (not a one-off)

## Related

- Supersedes: (none)
- Related specs: `specs/features/scaffold/project-scaffold.md`
- Reference: `references/openclaw-patterns.md` — agents/ owns LLM interaction
