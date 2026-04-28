# Feature: OpenTelemetry Tracing

**Status**: Implemented
**Owner**: GuillermoLB
**Last Updated**: 2026-04-28

## Purpose

Give operators a working trace view of every agent run — tool calls, LLM requests, latency, token counts — without requiring any external backend. Console output is the baseline; OTLP export to any backend (Langfuse, Grafana Tempo, Jaeger) is additive via env var.

This spec covers the OTel foundation only. Backend integrations (Langfuse, etc.) are specified separately and build on top of this.

---

## Current state

`tracing.py` has a `setup_otel()` function that creates a `TracerProvider` with an OTLP exporter — but only when `OBSERVABILITY__OTEL_ENDPOINT` is set. If the env var is absent, no provider is created and no spans are emitted. There is no console fallback.

`agents/claude.py` creates no spans. There is no agent tracing of any kind.

The result: **no traces are visible in any environment.**

---

## What changes

### Single TracerProvider, always created

`setup_tracing()` (replacing `setup_otel()`) creates the global `TracerProvider` unconditionally at startup. It always adds a `ConsoleSpanExporter` so traces are visible in logs immediately with zero configuration. An OTLP exporter is added on top when `OBSERVABILITY__OTEL_ENDPOINT` is set.

```
startup
  └── setup_tracing()
        ├── ConsoleSpanExporter    ← always active
        └── OTLPSpanExporter       ← active only if OTEL_ENDPOINT is set
```

Any future backend (Langfuse, Grafana) adds a second OTLP processor to the same provider via `add_otlp_exporter()` — never creates its own provider.

### Agent tracing decoupled from Langfuse

`ClaudeAgentRunner` gets its tracer from `tracing.get_tracer()`, not from `langfuse.get_tracer()`. The `agent_run` span and subprocess `TRACEPARENT` injection work whenever OTel is configured — which is always, since the provider is always created.

### Subprocess env vars always injected when OTLP endpoint is set

The SDK CLI subprocess needs to know where to send its spans. This is controlled by `OTEL_EXPORTER_OTLP_ENDPOINT` and related vars injected into `ClaudeAgentOptions.env`. These are built from `OBSERVABILITY__OTEL_ENDPOINT` (or a backend-specific endpoint if set).

For local development with console-only output, subprocess spans are not captured — the CLI subprocess would need its own OTLP backend to export to. The `agent_run` root span and its attributes are visible in the console; the per-turn and per-tool child spans require an OTLP backend.

---

## TracerProvider ownership

One provider. One place it is created. All other modules add processors to it — they never call `trace.set_tracer_provider()` themselves.

```
tracing.py          → creates provider, owns it, exposes get_tracer() and add_otlp_exporter()
agents/claude.py    → calls tracing.get_tracer() to create agent_run spans
future backends     → call tracing.add_otlp_exporter(endpoint, headers) to add their exporter
```

---

## Span structure

### What is always traced (console + OTLP)

```
[span] agent_run                     ← ClaudeAgentRunner, always
  attributes:
    sender_id
    model
    job_id
    session_id (if resuming)
  events:
    agent_result:
      total_cost_usd                 ← from ResultMessage (authoritative)
      num_turns
      input_tokens
      output_tokens
      stop_reason
```

### What requires an OTLP backend (subprocess spans)

```
[span] agent_run
  [span] claude_code.interaction     ← CLI subprocess, one per agent loop turn
    [span] claude_code.llm_request   ← per API call: model, tokens, latency
    [span] claude_code.tool          ← per tool call: tool name, execution time
      [span] claude_code.tool.execution
```

Subprocess spans attach to `agent_run` via W3C `TRACEPARENT` propagation — the Python process injects its current span's trace context into the subprocess env, and the CLI uses it as the parent.

---

## Console output (development)

With no env vars set, every agent run prints something like:

```
{
    "name": "agent_run",
    "context": {"trace_id": "0x1a2b3c...", "span_id": "0xaabbcc..."},
    "attributes": {
        "sender_id": "cli",
        "model": "claude-sonnet-4-6",
        "job_id": "cli"
    },
    "events": [
        {
            "name": "agent_result",
            "attributes": {
                "total_cost_usd": "0.003421",
                "num_turns": 3,
                "input_tokens": 1240,
                "output_tokens": 87,
                "stop_reason": "end_turn"
            }
        }
    ],
    "duration_ns": 4231000000
}
```

This is immediately useful: you can see cost per run, number of turns, and total tokens without any backend.

---

## Settings

```python
class ObservabilitySettings(BaseSettings):
    ...
    otel_endpoint: str | None = None        # OTLP endpoint for traces (any backend)
    otel_console: bool = True               # console exporter, default on
```

`OBSERVABILITY__OTEL_CONSOLE=false` disables console output in production (where OTLP export is used instead and console output is noise).

---

## Module changes

### `tracing.py`

- Replace `setup_otel(endpoint, app)` with:
  - `setup_tracing(otlp_endpoint, console)` — creates provider, adds console exporter when `console=True`, optionally adds OTLP exporter.
  - `add_otlp_exporter(endpoint, headers)` — adds a second OTLP processor to the existing provider.
  - `instrument_app(app)` — wires FastAPI, SQLAlchemy, httpx auto-instrumentation. Called separately so CLI (no FastAPI) can call `setup_tracing()` without instrumenting a non-existent app.
  - `get_tracer(name)` — returns a tracer from the global provider.

### `agents/claude.py`

- Replace `from bacteria.observability.langfuse import get_tracer` with `from bacteria.observability.tracing import get_tracer`
- `_build_subprocess_env()` reads `OBSERVABILITY__OTEL_ENDPOINT` (and headers if set) — no Langfuse dependency
- `agent_run` span is created whenever the provider has been set up (always)

### `observability/__init__.py`

- Call `setup_tracing()` unconditionally (before Sentry, before Langfuse)
- Pass `otlp_endpoint` and `otel_console` from settings

### `settings.py`

- Add `otel_console: bool = True` to `ObservabilitySettings`

---

## Implementation plan

### Step 1 — Rewrite `tracing.py`

Implement `setup_tracing()`, `add_otlp_exporter()`, `instrument_app()`, `get_tracer()`. Remove `setup_otel()`.

### Step 2 — Update `observability/__init__.py`

Call `setup_tracing()` first. Remove the `if app is not None and obs.otel_endpoint` guard — tracing is always set up.

### Step 3 — Update `agents/claude.py`

- Import `get_tracer` from `tracing` instead of `langfuse`
- `_build_subprocess_env()` reads from settings directly, no Langfuse dependency

### Step 4 — Update `settings.py`

Add `otel_console: bool = True`.

### Step 5 — Run CLI, verify console output

```bash
bacteria chat
# send a message
# agent_run span should print to stdout
```

---

## Acceptance Criteria

```
Given no env vars set
When the application starts
Then setup_tracing() runs without error
And a TracerProvider with ConsoleSpanExporter is active
```

```
Given no env vars set
When a CLI message triggers an agent run
Then an "agent_run" span is printed to stdout
And it includes sender_id, model, job_id attributes
And an "agent_result" event with total_cost_usd and num_turns
```

```
Given OBSERVABILITY__OTEL_ENDPOINT is set
When a CLI message triggers an agent run
Then the agent_run span is exported via OTLP to the configured endpoint
And console output is still active (unless OBSERVABILITY__OTEL_CONSOLE=false)
And subprocess env vars include OTEL_EXPORTER_OTLP_ENDPOINT
So claude_code.interaction child spans appear in the backend
```

```
Given OBSERVABILITY__OTEL_CONSOLE=false and OBSERVABILITY__OTEL_ENDPOINT is set
When the application runs
Then no spans are printed to stdout
And all spans go to the OTLP backend only
```

```
Given a future backend (Langfuse) calls add_otlp_exporter()
Then spans are exported to both the original OTLP endpoint and Langfuse
And no second TracerProvider is created
```

---

## Dependencies

- `specs/features/observability/observability.md` — overall stack
- `specs/features/agents/agent.md` — ClaudeAgentRunner
- `specs/features/observability/langfuse-agent-tracing.md` — builds on top of this

---

**Status History**: Draft (2026-04-27)
