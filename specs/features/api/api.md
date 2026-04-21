# Feature: API

**Status**: Draft
**Owner**: GuillermoLB
**Last Updated**: 2026-04-20

## Purpose

Expose Bacteria to the outside world. Two surfaces: a WebSocket endpoint for the browser chat UI (direct agent execution, no queue), and HTTP webhook endpoints for external platforms (WhatsApp). The API is the intake layer — it never executes workflow logic directly, except for the chat WebSocket which runs the agent inline for real-time streaming.

---

## Phase 1 — Worker validation (current)

Before building the chat UI or WhatsApp integration, validate the queue and worker end-to-end using FastAPI's built-in Swagger UI (`/docs`) as the interface.

### What gets built

**`POST /jobs`** — enqueue any job manually:

```json
{
  "event_type": "whatsapp.agent_request",
  "queue": "agents",
  "payload": {
    "sender_id": "test_user",
    "message_text": "hello from swagger"
  },
  "priority": 0,
  "max_attempts": 3
}
```

**`GET /jobs`** — list recent jobs with status, queue, attempts, error:

```json
[
  {
    "id": "uuid",
    "event_type": "whatsapp.agent_request",
    "queue": "agents",
    "status": "completed",
    "attempts": 1,
    "created_at": "...",
    "error": null
  }
]
```

Swagger at `/docs` provides the submit form and response display for free — no custom UI needed.

### Worker entrypoint

```toml
[project.scripts]
bacteria-worker = "bacteria.worker:main"
```

```python
# src/bacteria/worker/__init__.py
def main() -> None:
    asyncio.run(get_worker().run())
```

### Test flow

```
1. uv run bacteria-worker          ← polls queue, processes jobs
2. uv run bacteria-api             ← serves FastAPI + Swagger at /docs
3. Browser → /docs → POST /jobs    ← enqueue a job
4. Worker picks it up, runs agent, logs reply
5. GET /jobs → see status = completed
```

### Acceptance Criteria

```
Given the worker is running
When POST /jobs is called with a valid whatsapp.agent_request payload
Then a job appears in the queue with status=pending
And the worker picks it up within poll_interval seconds
And the job transitions to completed
And GET /jobs shows the job with status=completed
```

```
Given a job that fails (e.g. agent error)
When GET /jobs is called
Then the job shows status=failed, attempts incremented, error message visible
```

---

---

## Surfaces

### 1. Chat WebSocket (`/ws/chat`)

Browser connects over WebSocket. Each message runs the agent workflow directly and streams the reply back token by token.

```
Browser → WS connect → /ws/chat
Browser → send: {"message": "hello"}
Server  → stream: {"type": "token", "text": "Hi"}
Server  → stream: {"type": "token", "text": "!"}
Server  → stream: {"type": "done", "text": "Hi!"}
```

No queue involved. The agent runs in the FastAPI process, same as the CLI. `sender_id` is derived from the WebSocket session (initially a generated UUID, later tied to auth).

### 2. WhatsApp Webhook (`/webhooks/whatsapp`)

Two endpoints required by Meta:

**`GET /webhooks/whatsapp`** — verification handshake. Meta sends `hub.challenge` and expects it echoed back. Must respond within 5s.

**`POST /webhooks/whatsapp`** — incoming messages. Verify signature, persist raw payload, enqueue `whatsapp.webhook` job, return 202 immediately.

---

## Chat WebSocket — detail

### Connection lifecycle

```
1. Client connects: WS /ws/chat?session_id={uuid}
2. Server loads or creates session (sender_id = session_id)
3. Client sends message
4. Server runs AgentRequestWorkflow directly
5. Server streams tokens as they arrive from ClaudeAgentRunner
6. Server sends "done" event when agent finishes
7. Repeat from 3
```

### Message protocol

Client → Server:
```json
{"message": "your text here"}
```

Server → Client (streamed):
```json
{"type": "token", "text": "partial text"}
{"type": "done",  "text": "full reply"}
{"type": "error", "text": "error message"}
```

### Streaming

`ClaudeAgentRunner` currently collects the full response before returning. To stream tokens the runner needs to yield tokens as they arrive from the SDK's `async for message in query(...)` loop. The WebSocket handler calls the runner in streaming mode and forwards each token to the client.

---

## WhatsApp Webhook — detail

### GET /webhooks/whatsapp — verification

```
Query params: hub.mode, hub.verify_token, hub.challenge
If hub.verify_token == settings.whatsapp.verify_token:
    return 200, hub.challenge
Else:
    return 403
```

Requires a new `verify_token` setting (`WHATSAPP__VERIFY_TOKEN`).

### POST /webhooks/whatsapp — incoming message

```
1. Read X-Hub-Signature-256 header
2. Verify HMAC-SHA256 against raw body + webhook_secret
   → 401 if invalid
3. Parse body (JSON)
4. Enqueue job: queue="webhooks", payload={
       "event_type": "whatsapp.webhook",
       "signature": header_value,
       "raw_body": raw_body_str,
       "sender_id": extracted_from_body,
       "message_text": extracted_from_body,
   }
5. Return 202 Accepted
```

Signature verification happens here (in the API layer) AND inside `VerifySignatureNode` (in the workflow). The API check is a fast gate to reject obviously invalid requests before they touch the queue.

---

## FastAPI app structure

```
api/
├── __init__.py       # create_app() factory
├── routes/
│   ├── chat.py       # WebSocket /ws/chat
│   └── webhooks.py   # GET+POST /webhooks/whatsapp
└── middleware.py     # request logging, correlation IDs
```

`create_app()` in `api/__init__.py`:

```python
def create_app() -> FastAPI:
    app = FastAPI(title="Bacteria")
    app.include_router(chat_router)
    app.include_router(webhooks_router)
    return app
```

---

## Settings

```python
class WhatsAppSettings(BaseSettings):
    webhook_secret: str = "dev-secret"
    verify_token: str = "dev-verify-token"  # new

class ServerSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
```

---

## Entrypoints

```toml
[project.scripts]
bacteria-chat    = "bacteria.cli:chat"
bacteria-worker  = "bacteria.worker:main"
bacteria-api     = "bacteria.api:main"
```

`bacteria-api` starts uvicorn:
```python
def main():
    uvicorn.run("bacteria.api:create_app", host=settings.server.host, port=settings.server.port)
```

---

## Acceptance Criteria

### Chat WebSocket

```
Given a browser connects to /ws/chat
When the user sends {"message": "hello"}
Then the server streams tokens back as {"type": "token", "text": "..."}
And sends {"type": "done", "text": "<full reply>"} when complete
And the turn is saved to context/memory/{session_id}.md
```

```
Given a returning session_id
When the user connects and sends a message
Then the agent has memory of previous conversations
```

### WhatsApp Webhook

```
Given a valid GET /webhooks/whatsapp with correct verify_token
When Meta sends the verification request
Then the server returns 200 with hub.challenge
```

```
Given a valid POST /webhooks/whatsapp with correct signature
When the webhook is received
Then the server returns 202 immediately
And a whatsapp.webhook job is enqueued
```

```
Given a POST /webhooks/whatsapp with invalid signature
When the webhook is received
Then the server returns 401
And no job is enqueued
```

---

## Dependencies

- `specs/features/scaffold/project-scaffold.md` — Implemented
- `specs/features/queue/queue-and-worker.md` — Implemented
- `specs/features/workflows/webhook-to-agent-flow.md` — Implemented
- `specs/features/agents/agent.md` — Implemented

---

**Status History**: Draft (2026-04-20)
