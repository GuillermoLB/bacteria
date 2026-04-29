# Feature: Observability Hardening

**Status**: Implemented
**Owner**: GuillermoLB
**Last Updated**: 2026-04-29

## Purpose

Fix seven structural issues found during a review of the observability implementation. The issues fall into three categories: correctness bugs (open spans on exception, blocking event loop), design debt (agent coupled to Langfuse, plumbing in wrong layer), and fragility (URL manipulation, hardcoded values). None require architectural changes — all are contained to `observability/` and `agents/claude.py`.

---

## Issues Being Fixed

| # | Issue | Category | File |
|---|---|---|---|
| 1 | Agent imports and calls Langfuse SDK directly | Design | `agents/claude.py` |
| 2 | No error isolation — observability can crash agent runs | Correctness | `agents/claude.py` |
| 3 | Open spans when `query()` raises an exception | Correctness | `agents/claude.py` |
| 4 | `SimpleSpanProcessor` blocks the async event loop | Performance | `observability/tracing.py` |
| 5 | Langfuse host derived by stripping URL path suffixes | Fragility | `observability/langfuse.py` |
| 6 | `service.name` hardcoded as `"bacteria"` | Fragility | `observability/tracing.py` |
| 7 | Subprocess env assembled inside agent code | Design | `agents/claude.py` |

---

## Design

### Fix 1 + 7 — Decouple agent from Langfuse via `AgentTracer` protocol

Introduce a thin protocol in `observability/agent_tracer.py`. `ClaudeAgentRunner` depends only on the protocol, never on Langfuse. The Langfuse implementation lives entirely in `observability/`.

```python
# observability/agent_tracer.py
from typing import Protocol

class AgentSpan(Protocol):
    def finish(self, output: str, usage: dict, metadata: dict) -> None: ...

class AgentTracer(Protocol):
    def start(self, name: str, input: str, metadata: dict) -> AgentSpan: ...
    def get_subprocess_env(self) -> dict[str, str]: ...
```

`ClaudeAgentRunner` receives an `AgentTracer | None` (injected, not imported). `_build_subprocess_env()` disappears from `claude.py` — the tracer owns that logic.

```python
# agents/claude.py — no observability imports
class ClaudeAgentRunner:
    def __init__(self, ..., tracer: AgentTracer | None = None):
        self.tracer = tracer
```

`observability/langfuse.py` provides `LangfuseAgentTracer` implementing the protocol.

---

### Fix 2 — Error isolation

All observability calls are wrapped so they cannot propagate exceptions into the agent:

```python
try:
    span = self.tracer.start(...)
except Exception:
    span = None
```

Same pattern on `span.finish(...)`. The agent run continues regardless of observability state.

---

### Fix 3 — Close spans on exception

Use try/finally so spans are always closed even if `query()` raises:

```python
span = _start_span(...)
try:
    async for message in query(...):
        ...
finally:
    _finish_span(span, ...)
```

On exception, `finish()` is called with whatever partial result was accumulated and an error status.

---

### Fix 4 — Replace `SimpleSpanProcessor` with `BatchSpanProcessor`

`add_otlp_exporter()` in `tracing.py` currently uses `SimpleSpanProcessor` which exports spans synchronously, blocking the event loop. Replace with `BatchSpanProcessor` to match the other exporter already using it.

```python
# tracing.py
_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**kwargs)))
```

---

### Fix 5 — Add `langfuse_host` setting

Stop deriving the host from the OTLP endpoint URL. Add an explicit `langfuse_host` field to `ObservabilitySettings`. If not set, fall back to stripping the known suffix (for backwards compatibility), but log a warning.

```python
class ObservabilitySettings(BaseSettings):
    ...
    langfuse_host: str | None = None  # e.g. "https://cloud.langfuse.com"
    langfuse_otlp_endpoint: str | None = None
```

```
OBSERVABILITY__LANGFUSE_HOST=https://cloud.langfuse.com
OBSERVABILITY__LANGFUSE_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel/v1/traces
```

---

### Fix 6 — Make `service.name` configurable

Add `service_name` to `ObservabilitySettings` defaulting to `"bacteria"`. Pass it to `setup_tracing()`.

```python
class ObservabilitySettings(BaseSettings):
    ...
    service_name: str = "bacteria"
```

```python
resource = Resource(attributes={"service.name": obs.service_name})
```

---

## File Changes

| File | Change |
|---|---|
| `observability/agent_tracer.py` | **New** — `AgentSpan` and `AgentTracer` protocols |
| `observability/langfuse.py` | Add `LangfuseAgentTracer` implementing the protocol; remove host URL surgery; accept `langfuse_host` directly |
| `observability/tracing.py` | `SimpleSpanProcessor` → `BatchSpanProcessor` in `add_otlp_exporter()`; accept `service_name` param |
| `observability/__init__.py` | Pass `service_name` to `setup_tracing()`; pass `langfuse_host` to `setup_langfuse()`; build and inject `LangfuseAgentTracer` |
| `agents/claude.py` | Accept `tracer: AgentTracer | None`; remove all observability imports; wrap in try/finally |
| `settings.py` | Add `service_name` and `langfuse_host` to `ObservabilitySettings` |

---

## Acceptance Criteria

```
Given Langfuse is configured and the agent runs successfully
When ClaudeAgentRunner.run() completes
Then a trace appears in Langfuse with input, output, and token usage
And no Langfuse-specific imports exist in agents/claude.py
```

```
Given Langfuse is down or misconfigured
When ClaudeAgentRunner.run() is called
Then the agent run completes normally and returns a result
And no exception from the observability layer propagates to the caller
```

```
Given query() raises an exception mid-run
When the exception propagates
Then lf_generation.end() and lf_span.end() are both called before the exception escapes
And the trace in Langfuse shows an error status with whatever partial data was collected
```

```
Given the application starts with OBSERVABILITY__SERVICE_NAME=bacteria-staging
When a trace is emitted to Langfuse
Then the trace's service.name attribute is "bacteria-staging"
```

```
Given OBSERVABILITY__LANGFUSE_HOST is set explicitly
When setup_langfuse() initializes the SDK client
Then the host is taken directly from the setting, not derived from the OTLP endpoint URL
```

```
Given Langfuse is not configured (no env vars)
When the application starts
Then no AgentTracer is injected and ClaudeAgentRunner runs with tracer=None
And no errors occur
```

---

## What Does NOT Change

- The subprocess OTLP env vars wiring — CLI telemetry continues to work as-is, now owned by `LangfuseAgentTracer.get_subprocess_env()`
- The two-trace structure in Langfuse (SDK trace + CLI subprocess spans) — this is a known CLI limitation, not in scope here
- `tracing.py`'s `setup_tracing()`, `instrument_app()`, `get_tracer()` — unchanged except `service_name` param

---

## Dependencies

- `specs/features/observability/langfuse-agent-tracing.md` — existing implementation being hardened
- `specs/features/observability/observability.md` — overall stack
