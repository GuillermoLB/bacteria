# Feature: Langfuse Agent Tracing

**Status**: Draft
**Owner**: GuillermoLB
**Last Updated**: 2026-04-27

## Purpose

Give operators full visibility into agent execution: per-turn LLM requests, tool calls, latency, token usage, and cost — visible in the Langfuse UI per job. The existing `observability/langfuse.py` wires up the Langfuse client but the `@observe` decorator only captures outer wall-clock latency. This spec defines the correct implementation.

---

## Why the current approach is insufficient

The `claude-agent-sdk` runs the Claude Code CLI as a **subprocess**. LLM API calls, token counts, and tool call executions all happen inside that subprocess — they are invisible to Python-side decorators. Wrapping `runner.run()` with `@observe` gives you one span with a duration, nothing inside it.

The SDK exposes its internal telemetry via **OTel env vars injected into the subprocess**. When configured, the CLI emits its own spans (LLM requests, tool calls, interaction turns) and automatically attaches them as children of the active OTel span in the parent process via W3C `TRACEPARENT` propagation.

The correct approach: start an OTel span in `ClaudeAgentRunner.run()`, configure the subprocess env vars to export to Langfuse's OTLP endpoint, and read `ResultMessage` directly for authoritative cost/token data (the OTel cache token breakdown has a known bug — always reports 0 — causing ~35% cost overcounting).

---

## What Langfuse receives

With this implementation, each agent run produces a trace in Langfuse with the following span hierarchy:

```
[SPAN] agent_run                          ← created by ClaudeAgentRunner
  ├── [SPAN] claude_code.interaction      ← one turn of the agent loop
  │     ├── [SPAN] claude_code.llm_request   ← each API call (model, tokens, latency)
  │     └── [SPAN] claude_code.tool          ← each tool invocation
  │           └── [SPAN] claude_code.tool.execution
  ├── [SPAN] claude_code.interaction      ← next turn
  │     └── ...
  └── [EVENT] agent_result               ← cost + token totals from ResultMessage
```

Metadata on the root span: `job_id`, `sender_id`, `model`, `session_id`.

---

## Architecture

Two things work together:

1. **OTel subprocess export** — the CLI subprocess exports its spans to Langfuse's OTLP endpoint. These become children of the active span via `TRACEPARENT`.
2. **`ResultMessage` event** — after the loop completes, `ResultMessage.total_cost_usd` and `ResultMessage.usage` are recorded directly to the Langfuse span as an event. This is the authoritative cost/token source.

---

## Settings changes

Add `langfuse_otlp_endpoint` to `ObservabilitySettings`. This is the OTLP endpoint Langfuse exposes for receiving spans — distinct from the Langfuse SDK host.

```python
class ObservabilitySettings(BaseSettings):
    ...
    langfuse_otlp_endpoint: str | None = None
    # e.g. "https://cloud.langfuse.com/api/public/otel/v1/traces"
    # or   "http://localhost:3000/api/public/otel/v1/traces" for self-hosted
```

`OBSERVABILITY__LANGFUSE_OTLP_ENDPOINT` env var. If unset, subprocess OTel export is disabled — only the outer span is recorded.

---

## `observability/langfuse.py` changes

Replace the current decorator-based stub with:

1. A `get_otlp_headers()` helper that returns the Base64-encoded `Authorization` header Langfuse requires for OTLP.
2. A `get_tracer()` helper that returns an OTel tracer for creating the root `agent_run` span.
3. A `record_result()` helper that appends a `ResultMessage` event to the current span.

```python
import base64
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

_tracer: trace.Tracer | None = None
_otlp_headers: dict | None = None


def setup_langfuse(secret_key: str, public_key: str, host: str, otlp_endpoint: str | None = None) -> None:
    global _tracer, _otlp_headers

    # OTLP auth header: Base64("public_key:secret_key")
    if otlp_endpoint:
        token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        _otlp_headers = {"Authorization": f"Basic {token}"}

        resource = Resource(attributes={"service.name": "bacteria"})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=otlp_endpoint, headers=_otlp_headers)
            )
        )
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("bacteria.agent")


def get_tracer() -> trace.Tracer | None:
    return _tracer


def get_otlp_headers() -> dict:
    return _otlp_headers or {}
```

---

## `ClaudeAgentRunner` changes

```python
from opentelemetry import trace as otel_trace
from opentelemetry.propagate import inject as otel_inject

from bacteria.observability.langfuse import get_tracer, get_otlp_headers

class ClaudeAgentRunner:
    async def run(self, ctx: Context) -> tuple[str, str | None]:
        tracer = get_tracer()

        with (tracer.start_as_current_span("agent_run") if tracer else nullcontext()) as span:
            if span and span.is_recording():
                span.set_attribute("job_id", str(ctx.job.id) if ctx.job else "cli")
                span.set_attribute("sender_id", ctx.event.sender_id)
                span.set_attribute("model", self.model)
                if ctx.session_id:
                    span.set_attribute("session_id", ctx.session_id)

            # Propagate TRACEPARENT into subprocess so CLI spans attach here
            carrier = {}
            otel_inject(carrier)
            traceparent = carrier.get("traceparent")

            subprocess_env = {}
            otlp_headers = get_otlp_headers()
            otlp_endpoint = _get_otlp_endpoint()  # reads from settings
            if otlp_endpoint:
                subprocess_env = {
                    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
                    "OTEL_TRACES_EXPORTER": "otlp",
                    "OTEL_LOGS_EXPORTER": "otlp",
                    "OTEL_METRICS_EXPORTER": "otlp",
                    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": otlp_endpoint,
                    "OTEL_EXPORTER_OTLP_HEADERS": _format_otlp_headers(otlp_headers),
                    "OTEL_LOG_TOOL_DETAILS": "1",
                    **({"TRACEPARENT": traceparent} if traceparent else {}),
                }

            options = ClaudeAgentOptions(
                ...
                env=subprocess_env,
            )

            result = ""
            result_session_id = ctx.session_id
            async for message in query(prompt=ctx.event.message_text, options=options):
                if isinstance(message, AssistantMessage):
                    text = _extract_text(message)
                    if text:
                        result = text
                if isinstance(message, ResultMessage):
                    result_session_id = message.session_id
                    if span and span.is_recording():
                        span.add_event("agent_result", attributes={
                            "total_cost_usd": str(message.total_cost_usd or 0),
                            "num_turns": message.num_turns,
                            "input_tokens": message.usage.get("input_tokens", 0) if message.usage else 0,
                            "output_tokens": message.usage.get("output_tokens", 0) if message.usage else 0,
                            "stop_reason": message.stop_reason or "",
                        })

            return result, result_session_id
```

`nullcontext()` is `contextlib.nullcontext` — used when no tracer is configured, so the code path is identical with or without Langfuse.

`_format_otlp_headers(headers: dict) -> str` formats `{"Authorization": "Basic ..."}` as `"Authorization=Basic ..."` (OTLP env var format).

`_get_otlp_endpoint()` reads `get_settings().observability.langfuse_otlp_endpoint`.

---

## `setup_observability()` changes

Pass `otlp_endpoint` to `setup_langfuse`:

```python
if obs.langfuse_secret_key and obs.langfuse_public_key:
    setup_langfuse(
        secret_key=obs.langfuse_secret_key,
        public_key=obs.langfuse_public_key,
        host=obs.langfuse_host,
        otlp_endpoint=obs.langfuse_otlp_endpoint,
    )
```

---

## OTel TracerProvider deduplication

`setup_otel()` (in `tracing.py`) and `setup_langfuse()` both call `trace.set_tracer_provider()`. They must not conflict. Two options:

1. **Preferred**: merge — `setup_langfuse()` adds a second `BatchSpanProcessor` to the existing provider if one is already set, rather than creating a new one.
2. **Simple**: only one OTel endpoint is active at a time. `setup_langfuse()` skips provider setup if `OTEL_EXPORTER_OTLP_ENDPOINT` is already set (letting the app OTel pipeline handle it, with Langfuse as just another exporter).

Option 2 is simpler and correct for Bacteria's single-process setup. Document it explicitly in code.

---

## What is traced

| Signal | Source | What you see in Langfuse |
|---|---|---|
| `agent_run` span | `ClaudeAgentRunner` (Python OTel) | Root span per job: job_id, sender_id, model, total duration |
| `claude_code.interaction` | CLI subprocess (OTel) | One span per agent loop turn |
| `claude_code.llm_request` | CLI subprocess (OTel) | Per-API-call: model, latency, token counts (input/output) |
| `claude_code.tool` | CLI subprocess (OTel) | Per-tool-call: tool name, execution time |
| `agent_result` event | `ResultMessage` (Python) | Authoritative: total_cost_usd, num_turns, input/output tokens |

**Content logging** (opt-in, controlled by env vars):
- `OTEL_LOG_USER_PROMPTS=1` — logs prompt text
- `OTEL_LOG_TOOL_DETAILS=1` — logs tool input arguments (enabled by default in this spec)
- `OTEL_LOG_TOOL_CONTENT=1` — logs full tool input/output

---

## What is NOT traced

- Conversation content (prompt/response text) — not sent to Langfuse by default. Enable with `OTEL_LOG_USER_PROMPTS=1` only if privacy requirements allow.
- Memory file contents — tool args are logged (`OTEL_LOG_TOOL_DETAILS=1`) but not full tool output by default.

---

## Environment variables

```
# Required for Langfuse
OBSERVABILITY__LANGFUSE_SECRET_KEY=sk-lf-...
OBSERVABILITY__LANGFUSE_PUBLIC_KEY=pk-lf-...
OBSERVABILITY__LANGFUSE_HOST=https://cloud.langfuse.com        # or self-hosted URL
OBSERVABILITY__LANGFUSE_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel/v1/traces

# Optional: log prompt/tool content
# OTEL_LOG_USER_PROMPTS=1
# OTEL_LOG_TOOL_CONTENT=1
```

For self-hosted Langfuse:
```
OBSERVABILITY__LANGFUSE_HOST=http://langfuse:3000
OBSERVABILITY__LANGFUSE_OTLP_ENDPOINT=http://langfuse:3000/api/public/otel/v1/traces
```

---

## File changes summary

| File | Change |
|---|---|
| `settings.py` | Add `langfuse_otlp_endpoint: str | None` to `ObservabilitySettings` |
| `observability/langfuse.py` | Replace stub with OTel provider setup + `get_tracer()` + `get_otlp_headers()` |
| `observability/__init__.py` | Pass `otlp_endpoint` to `setup_langfuse()` |
| `agents/claude.py` | Start `agent_run` span, inject `TRACEPARENT`, pass subprocess env, record `ResultMessage` event |

No other files change.

---

## Acceptance Criteria

```
Given LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_OTLP_ENDPOINT are set
When a WhatsApp message triggers an agent job
Then a trace appears in the Langfuse UI for that job
And the root span is named "agent_run" with job_id and sender_id attributes
And child spans exist for each claude_code.interaction turn
And each turn has claude_code.llm_request spans with token counts and latency
And tool calls appear as claude_code.tool spans with tool names
And an "agent_result" event on the root span shows total_cost_usd and num_turns
```

```
Given none of the LANGFUSE env vars are set
When the application starts and an agent job runs
Then no errors occur
And the agent runs normally with no tracing overhead
```

```
Given LANGFUSE env vars are set but LANGFUSE_OTLP_ENDPOINT is not
When an agent job runs
Then the root "agent_run" span is recorded in Langfuse
But no subprocess spans (llm_request, tool) appear as children
```

```
Given OTEL_LOG_USER_PROMPTS is not set (default)
When an agent job runs
Then prompt text does not appear in any Langfuse span attributes
```

---

## Known limitations

- **Cache token breakdown** — `cache_read_input_tokens` and `cache_creation_input_tokens` always report 0 in OTel spans (SDK bug, open as of March 2026). Mitigated by reading `ResultMessage.usage` directly for the `agent_result` event. Cost displayed by Langfuse from OTel spans will overcount by ~35% for cached requests; the `agent_result` event carries the correct total.
- **Subagent spans** — if the agent spawns a subagent via the `Agent` tool, subagent tool calls may not appear as nested spans (known SDK limitation). Top-level agent spans are always captured.

---

## Dependencies

- `specs/features/observability/observability.md` — overall observability stack
- `specs/features/agents/agent.md` — ClaudeAgentRunner
- `references/claude-agent-sdk.md` — OTel env vars, ResultMessage fields

---

**Status History**: Draft (2026-04-27)
