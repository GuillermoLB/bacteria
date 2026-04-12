# Decision: Provider-agnostic agent runners via BaseAgentRunner protocol

**Number**: 0002
**Status**: Accepted
**Date**: 2026-04-12
**Author**: GuillermoLB

> Decision records are immutable. Do not edit after acceptance.
> If this decision is superseded, mark it `Status: Superseded by [link]` and create a new record.

## Context

The reference architecture used the Claude Agent SDK exclusively for agent execution. Locking into a single provider couples the system to one vendor's API, pricing, and capabilities. The AI agent ecosystem is evolving rapidly — new frameworks (Pydantic AI, LangGraph, raw LLM APIs) offer different trade-offs.

## Decision

Define a `BaseAgentRunner` Protocol (or ABC) that all agent execution adapters must implement. Concrete adapters (Claude SDK, Pydantic AI, direct LLM API + tool loop, LangGraph) implement this interface. Workflows reference only `BaseAgentRunner` — never a concrete provider.

## Consequences

**Positive**:
- Swap providers without changing workflow code
- Can run different agent types on different queues (e.g. Claude SDK for complex tasks, raw LLM for simple ones)
- Easier to test — mock the protocol, not a specific SDK
- Budget caps (`max_turns`, `max_cost`) enforced at the protocol level

**Trade-offs**:
- Lowest common denominator API — provider-specific features require escape hatches
- Slightly more upfront abstraction to design and maintain

## Related

- Supersedes: (none)
- Related specs: `specs/architecture/architecture.md`
