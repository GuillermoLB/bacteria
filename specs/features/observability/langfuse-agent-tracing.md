# Feature: Langfuse Agent Tracing

**Status**: Implemented (with known limitation — see below)
**Owner**: GuillermoLB
**Last Updated**: 2026-04-29

## Purpose

Give operators full visibility into agent execution: per-turn LLM requests, tool calls, latency, token usage, and cost — visible in the Langfuse UI per job. The existing `observability/langfuse.py` wires up the Langfuse client but the `@observe` decorator only captures outer wall-clock latency. This spec defines the correct implementation.

---

## Why the current approach is insufficient

The `claude-agent-sdk` runs the Claude Code CLI as a **subprocess**. LLM API calls, token counts, and tool call executions all happen inside that subprocess — they are invisible to Python-side decorators. Wrapping `runner.run()` with `@observe` gives you one span with a duration, nothing inside it.

The SDK exposes its internal telemetry via **OTel env vars injected into the subprocess**. When configured, the CLI emits its own spans (LLM requests, tool calls, interaction turns) to the configured OTLP endpoint.

**Important**: The Claude CLI Bun binary (v2.x) does **not** implement W3C `TRACEPARENT` propagation from environment variables — it ignores both `TRACEPARENT` and `OTEL_RESOURCE_ATTRIBUTES`, always generating its own root trace IDs. CLI spans therefore land in Langfuse as **separate root traces**, not as children of the Python `agent_run` span.

The implemented approach: start an OTel span in `ClaudeAgentRunner.run()`, configure the subprocess env vars to export to Langfuse's OTLP endpoint (base URL, not `/v1/traces` — the CLI appends that path automatically), and read `ResultMessage` directly for authoritative cost/token data (the OTel cache token breakdown has a known bug — always reports 0 — causing ~35% cost overcounting). After the run, stamp the Python span with `claude_session_id` so CLI traces can be correlated via Langfuse's session filter.

---

## What Langfuse receives

Each agent run produces **two separate traces** in Langfuse (not nested — see limitation above):

**Trace 1 — Python span** (`agent_run`):
```
[SPAN] agent_run
  └── [EVENT] agent_result   ← total_cost_usd, num_turns, input/output tokens
Attributes: job_id, sender_id, model, session_id, claude_session_id
```

**Trace 2 — CLI spans** (one per agent run, separate root trace):
```
[SPAN] claude_code.interaction      ← one turn of the agent loop
  ├── [SPAN] claude_code.llm_request   ← each API call (model, tokens, latency)
  └── [SPAN] claude_code.tool          ← each tool invocation
        └── [SPAN] claude_code.tool.execution
[SPAN] claude_code.interaction      ← next turn
  └── ...
Attributes: session.id = claude_session_id (matches agent_run.claude_session_id)
```

**Correlation**: filter CLI traces in Langfuse by `session.id` = the `claude_session_id` attribute from the `agent_run` trace.

---

## Architecture

Two things work together:

1. **OTel subprocess export** — the CLI subprocess exports its spans to Langfuse's OTLP base endpoint (`/api/public/otel`, not `/api/public/otel/v1/traces` — the CLI appends `/v1/traces` automatically per OTel spec). Spans land as separate root traces in Langfuse.
2. **`ResultMessage` event + `claude_session_id`** — after the loop completes, `ResultMessage.total_cost_usd`, `ResultMessage.usage`, and `ResultMessage.session_id` are recorded to the Python span. The `session_id` (as `claude_session_id`) enables manual correlation with CLI traces in Langfuse's session filter.

---

## Settings changes

Add three fields to `ObservabilitySettings`:

```python
class ObservabilitySettings(BaseSettings):
    ...
    langfuse_secret_key: str | None = None
    langfuse_public_key: str | None = None
    langfuse_otlp_endpoint: str | None = None
    # e.g. "https://cloud.langfuse.com/api/public/otel/v1/traces"
    # or   "http://localhost:3000/api/public/otel/v1/traces" for self-hosted
```

All three must be set for Langfuse to activate. If any is absent, `setup_langfuse()` is not called and tracing continues console-only (or OTLP-only if `OBSERVABILITY__OTEL_ENDPOINT` is set).

---

## `observability/langfuse.py` changes

Replace the stub with two helpers:

1. `setup_langfuse(secret_key, public_key, otlp_endpoint)` — builds the Base64 auth header and registers Langfuse as a second OTLP exporter on the existing `TracerProvider` via `tracing.add_otlp_exporter()`. Never creates its own provider.
2. `get_langfuse_subprocess_env()` — returns the subprocess env vars needed to route CLI spans to Langfuse, or `{}` if not configured.

```python
import base64

_otlp_headers: dict | None = None
_otlp_endpoint: str | None = None


def setup_langfuse(secret_key: str, public_key: str, otlp_endpoint: str) -> None:
    global _otlp_headers, _otlp_endpoint
    from bacteria.observability.tracing import add_otlp_exporter

    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    _otlp_headers = {"Authorization": f"Basic {token}"}
    _otlp_endpoint = otlp_endpoint

    add_otlp_exporter(endpoint=otlp_endpoint, headers=_otlp_headers)


def get_langfuse_subprocess_env() -> dict[str, str]:
    if not _otlp_endpoint:
        return {}
    headers_str = ",".join(f"{k}={v}" for k, v in (_otlp_headers or {}).items())
    return {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": _otlp_endpoint,
        "OTEL_EXPORTER_OTLP_HEADERS": headers_str,
        "OTEL_LOG_TOOL_DETAILS": "1",
    }
```

---

## `ClaudeAgentRunner` changes

`agents/claude.py` already creates the `agent_run` span via `tracing.get_tracer()` — no change needed there. The only addition is subprocess env var injection so the CLI routes its spans to Langfuse.

`_build_subprocess_env()` is extended to merge in Langfuse subprocess vars:

```python
from bacteria.observability.langfuse import get_langfuse_subprocess_env
from opentelemetry.propagate import inject as otel_inject

def _build_subprocess_env() -> dict[str, str]:
    env = get_langfuse_subprocess_env()
    if env:
        carrier = {}
        otel_inject(carrier)
        if traceparent := carrier.get("traceparent"):
            env["TRACEPARENT"] = traceparent
    return env
```

`TRACEPARENT` injection propagates the active `agent_run` span context into the subprocess so CLI spans are recorded as children in Langfuse.

---

## `setup_observability()` changes

```python
if obs.langfuse_secret_key and obs.langfuse_public_key and obs.langfuse_otlp_endpoint:
    from bacteria.observability.langfuse import setup_langfuse
    setup_langfuse(
        secret_key=obs.langfuse_secret_key,
        public_key=obs.langfuse_public_key,
        otlp_endpoint=obs.langfuse_otlp_endpoint,
    )
```

`setup_tracing()` is always called first. `setup_langfuse()` then adds Langfuse as a second processor on the same provider — one provider, two exporters.

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
# Required — all three must be set
OBSERVABILITY__LANGFUSE_SECRET_KEY=sk-lf-...
OBSERVABILITY__LANGFUSE_PUBLIC_KEY=pk-lf-...
OBSERVABILITY__LANGFUSE_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel/v1/traces

# Optional: log prompt/tool content
# OTEL_LOG_USER_PROMPTS=1
# OTEL_LOG_TOOL_CONTENT=1
```

For self-hosted Langfuse:
```
OBSERVABILITY__LANGFUSE_SECRET_KEY=sk-lf-...
OBSERVABILITY__LANGFUSE_PUBLIC_KEY=pk-lf-...
OBSERVABILITY__LANGFUSE_OTLP_ENDPOINT=http://langfuse:3000/api/public/otel/v1/traces
```

---

## File changes summary

| File | Change |
|---|---|
| `settings.py` | Add `langfuse_secret_key`, `langfuse_public_key`, `langfuse_otlp_endpoint` to `ObservabilitySettings` |
| `observability/langfuse.py` | Replace stub with `setup_langfuse()` (adds exporter to existing provider) + `get_langfuse_subprocess_env()` |
| `observability/__init__.py` | Call `setup_langfuse()` after `setup_tracing()` when keys are present |
| `agents/claude.py` | Extend `_build_subprocess_env()` to merge Langfuse env vars + inject `TRACEPARENT` |

No other files change. `tracing.py` and the `agent_run` span creation in `ClaudeAgentRunner.run()` are unchanged.

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

- **No parent-child nesting** — the Claude CLI Bun binary (v2.x) ignores `TRACEPARENT` and `OTEL_RESOURCE_ATTRIBUTES`. CLI spans always land as separate root traces in Langfuse. Correlation is via `claude_session_id` attribute on the `agent_run` span matching the `session.id` attribute on CLI traces. If a future CLI version supports W3C context propagation, re-enable `TRACEPARENT` injection in `_build_subprocess_env()`.
- **OTLP endpoint URL** — the Python OTel exporter takes the full `/v1/traces` URL; the CLI subprocess takes the base URL (without `/v1/traces`) and appends it per OTel spec. `langfuse.py` stores both: `_otlp_endpoint` (full, for Python) and `_otlp_base_endpoint` (base, for subprocess env).
- **Cache token breakdown** — `cache_read_input_tokens` and `cache_creation_input_tokens` always report 0 in OTel spans (SDK bug, open as of March 2026). Mitigated by reading `ResultMessage.usage` directly for the `agent_result` event. Cost displayed by Langfuse from OTel spans will overcount by ~35% for cached requests; the `agent_result` event carries the correct total.
- **Subagent spans** — if the agent spawns a subagent via the `Agent` tool, subagent tool calls may not appear as nested spans (known SDK limitation). Top-level agent spans are always captured.

---

## Dependencies

- `specs/features/observability/observability.md` — overall observability stack
- `specs/features/agents/agent.md` — ClaudeAgentRunner
- `references/claude-agent-sdk.md` — OTel env vars, ResultMessage fields

---

**Status History**: Draft (2026-04-27)
