# Feature: Webhook-to-Agent Flow

**Status**: Draft
**Owner**: GuillermoLB
**Last Updated**: 2026-04-14

## Purpose

Describe the full end-to-end flow from an incoming webhook to an agent reply. This is the primary Layer 1 → Layer 3 path in bacteria: a message arrives from an external channel (WhatsApp, Slack, etc.), is classified as an agent request, and handed off to an agent workflow that runs the AI loop and delivers a reply.

This spec uses WhatsApp as the concrete example but the pattern applies to any channel.

---

## Overview

Two jobs, two workflows, clean boundary:

```
POST /webhooks/whatsapp
  → [Job 1] WhatsAppWebhookJob    (queue: "webhooks")
      WhatsAppWebhookWorkflow
        VerifySignatureNode
        ParsePayloadNode
        ClassifyIntentNode
        EmitAgentJobNode          → INSERT INTO jobs (queue: "agents", ...)
      → COMPLETED

  → [Job 2] AgentRequestJob       (queue: "agents")
      AgentRequestWorkflow
        LoadContextNode           → context/memory/{sender_id}.md
        RunAgentNode              → agentic loop (tools, turns, reasoning)
        SaveMessageNode           → appends turn to memory file
        SendReplyNode             → POST to WhatsApp API
      → COMPLETED
```

Job 1 completes as soon as it emits Job 2. Job 2 runs independently — its own retry logic, its own DB row, its own failure handling.

---

## Job 1 — WhatsAppWebhookWorkflow

**Queue**: `webhooks`
**Trigger**: `POST /webhooks/whatsapp`

### Nodes

**`VerifySignatureNode`**
- Reads `X-Hub-Signature-256` header from raw payload
- Computes HMAC-SHA256 against `settings.whatsapp.webhook_secret`
- Raises if invalid — job fails immediately, no further processing

**`ParsePayloadNode`**
- Translates raw WhatsApp webhook JSON into internal `Event` domain model
- Anti-corruption layer: nothing downstream knows about WhatsApp's payload shape
- Sets `ctx.event` with normalized fields: `sender_id`, `message_text`, `media_url`, `timestamp`

**`ClassifyIntentNode`**
- Reads `ctx.event.message_text`
- Determines intent: `"agent"` | `"command"` | `"media"`
- Simple rules first (starts with `/` → `"command"`, has `media_url` → `"media"`, otherwise → `"agent"`)
- Sets `ctx.intent`

**`EmitAgentJobNode`**
- Reads `ctx.intent`
- Enqueues a new job to the appropriate queue:
  - `"agent"` → `queue="agents"`, payload carries `sender_id`, `message_text`, `channel="whatsapp"`
  - `"command"` → `queue="commands"`, payload carries parsed command
  - `"media"` → `queue="media"`, payload carries `media_url`
- This node only handles the `"agent"` path for this spec; command and media are future specs

### Context at completion

```python
Context(
    job=Job(...),
    event=Event(sender_id="...", message_text="...", channel="whatsapp"),
    intent="agent",
    emitted_job_id=UUID("..."),   # ID of the agent job just enqueued
)
```

### Failure behaviour

- `VerifySignatureNode` fails → job marked FAILED, no retry (invalid signature is not transient)
- Any other node fails → job marked FAILED, retried up to `max_attempts`
- No agent job is emitted if the webhook job fails — nothing is lost, the webhook payload is persisted in the `events` table before the job runs

---

## Job 2 — AgentRequestWorkflow

**Queue**: `agents`
**Trigger**: emitted by `EmitAgentJobNode` in Job 1

### Nodes

**`LoadContextNode`**
- Reads `context/memory/{sender_id}.md` — per-user facts, preferences, and conversation history
- Sets `ctx.sender_memory` — full file content, or `None` if no memory file exists yet

**`RunAgentNode`**
- Calls `AgentRunner.run(ctx)` — the concrete runner is injected via `dependencies.py`
- The runner assembles the system prompt (soul.md + sender_memory), runs the agentic loop, and returns a text reply
- The loop runs until the model produces a final text response or hits `max_turns`
- Sets `ctx.agent_result`

**`SaveMessageNode`**
- Appends the user message and agent reply to `context/memory/{sender_id}.md`
- Creates the file if it doesn't exist yet

**`SendReplyNode`**
- Reads `ctx.agent_result` and `ctx.event.sender_id`
- POSTs reply to WhatsApp API via the channel client
- Sets `ctx.delivered = True`
- On delivery failure: job retried — agent does not re-run, only delivery retries

### Context at completion

```python
Context(
    job=Job(...),
    event=Event(sender_id="...", message_text="...", channel="whatsapp"),
    sender_memory="name: Guillermo\n...",
    agent_result="Here is what I found...",
    delivered=True,
)
```

### Failure behaviour

- `RunAgentNode` fails (timeout, provider error) → job marked FAILED, retried
- `SendReplyNode` fails (WhatsApp API down) → job marked FAILED, retried — agent result is in `ctx`, no re-run needed on retry (future optimisation: persist `agent_result` to avoid re-running agent on delivery retry)
- Job exhausts `max_attempts` → marked FAILED permanently, error visible in `jobs` table

---

## The two-job boundary — why it matters

| Concern | Job 1 (webhook) | Job 2 (agent) |
|---|---|---|
| Latency budget | Must complete fast — external system is waiting | Can take 30–60s — no caller is waiting |
| Retry on failure | Retry the full webhook processing | Retry only the agent run |
| Observability | Did we receive and parse the message? | Did the agent run and deliver? |
| Failure blast radius | Webhook failure doesn't affect agent queue | Agent failure doesn't affect webhook processing |

Emitting a new job at the boundary is not overhead — it is the boundary. It makes the two concerns independently observable, independently retriable, and independently scalable (more agent workers, same webhook workers).

---

## Registry entries

```python
registry = {
    ("whatsapp", "webhook"):       whatsapp_webhook_workflow,
    ("whatsapp", "agent_request"): agent_request_workflow,
    # future:
    # ("whatsapp", "command"):     command_workflow,
    # ("whatsapp", "media"):       media_workflow,
    # ("slack",    "webhook"):     slack_webhook_workflow,
}
```

---

## Acceptance Criteria

### Scenario 1: Happy path

```
Given a valid WhatsApp webhook POST with a text message
When the webhook is received
Then Job 1 completes with status COMPLETED
And Job 2 is enqueued with queue="agents" and correct sender_id and message_text
And Job 2 completes with status COMPLETED
And the reply is delivered to the sender via WhatsApp API
```

### Scenario 2: Invalid signature

```
Given a WhatsApp webhook POST with an invalid signature
When VerifySignatureNode runs
Then Job 1 is marked FAILED immediately
And no agent job is enqueued
And the webhook endpoint returns 401
```

### Scenario 3: Agent failure with retry

```
Given Job 2 is running and RunAgentNode raises a provider timeout
When the worker catches the exception
Then Job 2 is marked FAILED with attempts incremented
And Job 2 is re-enqueued as PENDING (if attempts < max_attempts)
And on retry, the full AgentRequestWorkflow runs again from LoadIdentityNode
```

### Scenario 4: Delivery failure

```
Given RunAgentNode completes and sets ctx.agent_result
And SendReplyNode fails (WhatsApp API 503)
Then Job 2 is marked FAILED
And on retry, the full workflow re-runs (agent re-runs — acceptable for now)
```

### Scenario 5: Webhook job failure does not lose the message

```
Given ParsePayloadNode raises an unexpected error
When Job 1 is marked FAILED
Then the raw webhook payload is already persisted in the events table
And the event is not lost
And the job can be manually re-enqueued for reprocessing
```

---

## Dependencies

- `specs/features/scaffold/project-scaffold.md` — module structure
- `specs/features/workflows/workflow-engine.md` — Node, Context, Workflow building blocks
- `specs/features/queue/` — worker loop and job lifecycle (not yet written)
- `specs/features/scheduler/` — not needed for this flow (webhook-triggered, not scheduled)

---

**Status History**: Draft (2026-04-14)
