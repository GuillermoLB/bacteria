# Feature: Context Refactor — Layered State

**Status**: rejeted
**Owner**: GuillermoLB
**Last Updated**: 2026-04-21

## Purpose

Improve the `Context` model to separate infrastructure concerns from domain pipeline state. Remove `job` from `Context`, replace flat optional fields with a typed mutable `PipelineState`, and move all raw payload handling (signature verification, Event construction) into the worker before the pipeline starts. This makes `Context` a pure domain carrier and allows workflow-specific state to grow without becoming a god object.

## Problems with the current design

1. **`job` pollutes domain state.** `job: Job | None` is queue infrastructure — it describes how work arrived, not what the pipeline is doing. It does not belong alongside `intent`, `agent_result`, and `delivered`.

2. **`Event` is created inside nodes, not before the pipeline.** `ParseWhatsAppPayloadNode` and `LoadContextNode` both construct `Event` from `job.payload` — duplicating the same logic in two places. This happens because `job` travels inside `Context` all the way to the nodes that need it.

3. **Signature verification is a node, not middleware.** `VerifySignatureNode` reads `job.payload["signature"]` and `job.payload["raw_body"]` — HTTP-layer concerns that have no place in a domain pipeline. Verification should happen before the workflow starts.

4. **Flat optional fields encode execution order.** Every field is `None` until a specific node sets it. Comments like `# Set by ParsePayloadNode` reveal implicit ordering assumptions baked into the schema. `Context` ends up documenting pipeline structure rather than carrying data.

5. **Schema grows with every workflow.** Adding a second workflow means adding more optional fields to a shared `Context`. Over time it becomes a god object where most fields are irrelevant for any given execution.

## Target design

### `PipelineState` — mutable, workflow-specific accumulation

```python
class PipelineState(BaseModel):
    intent: str | None = None
    sender_memory: str | None = None
    agent_result: str | None = None
    delivered: bool = False
```

- Non-frozen Pydantic model — nodes mutate fields directly (`ctx.state.intent = "agent"`)
- Runtime validation on assignment — wrong types raise `ValidationError` immediately
- Default values — `PipelineState()` constructs with no arguments
- Grows per workflow in the future without touching `Context`

### `Context` — frozen domain envelope

```python
class Context(BaseModel, frozen=True):
    event: Event
    state: PipelineState = Field(default_factory=PipelineState)
```

- No `job` — infrastructure is gone from the domain model
- `event` is required and always set before the pipeline starts
- `state` is mutable — Pydantic allows mutating a non-frozen nested model inside a frozen parent
- `event` remains frozen — no node can swap out the inbound message mid-pipeline

### Node mutation pattern

Before (immutable copy):
```python
return ctx.model_copy(update={"intent": "agent"})
```

After (direct state mutation):
```python
ctx.state.intent = "agent"
return ctx
```

### Pre-pipeline handling in the worker

All raw payload concerns are resolved in `Worker._handle` before the workflow runs, keyed by `event_type`:

```python
async def _handle(self, job: Job) -> None:
    if job.payload["event_type"] == "whatsapp.webhook":
        verify_signature(
            secret=settings.whatsapp.webhook_secret,
            raw_body=job.payload["raw_body"],
            signature=job.payload["signature"],
        )  # raises PermanentFailure if invalid

    event = Event(
        sender_id=job.payload["sender_id"],
        message_text=job.payload["message_text"],
        channel=job.payload["channel"],
        media_url=job.payload.get("media_url"),
    )
    ctx = Context(event=event)
    workflow = self.registry.get(job.payload["event_type"])
    ctx = await workflow.run(ctx)
    result = {"agent_result": ctx.state.agent_result} if ctx.state.agent_result else None
    await self.queue.complete(job, result=result)
```

`verify_signature` is a plain function, not a node:

```python
def verify_signature(secret: str, raw_body: str, signature: str) -> None:
    expected = "sha256=" + hmac.new(secret.encode(), raw_body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PermanentFailure("Invalid webhook signature")
```

### CLI flow — unchanged

The CLI already constructs `Event` directly and has no `job`:

```python
ctx = Context(
    event=Event(sender_id="cli", message_text=user_input, channel="cli")
)
ctx = await workflow.run(ctx)
print(ctx.state.agent_result)
```

## Future: webhook route (spec 2)

When `POST /webhooks/whatsapp` is implemented, signature verification moves from the worker into FastAPI middleware. At that point `raw_body` and `signature` are no longer enqueued in `job.payload`, and the `verify_signature` call in `_handle` is removed. This refactor does not block that change — it makes it easier by keeping all raw payload logic in one place (`_handle`) rather than spread across nodes.

## Why not alternatives

| Alternative | Rejected because |
|---|---|
| Keep flat fields, stay frozen | God object grows with every workflow; same rigidity problem |
| Nested frozen Pydantic state | Just moves the flat fields one level down — same rigidity, no flexibility gain |
| `dict` + string constants | Loses runtime field-level validation; typos in key names silently return `None` |
| Generic `Context[S]` | Clean but adds Pydantic generic complexity before it's needed |
| `TypedDict` for state | Type hints only, no runtime enforcement; plain dict at runtime |
| Keep `job` on `Context` | Infrastructure leaks into domain model; forces all nodes to know about queue mechanics |
| `raw_payload` field on `Context` | Temporary bridge that introduces a field we already know is wrong |
| Pass `job` to `Workflow.run` | Leaks infrastructure into the workflow executor; all workflows would depend on `Job` |

## Files affected

| File | Change |
|---|---|
| `entities/context.py` | Remove `job` and flat fields; `event` required; add `state: PipelineState` |
| `entities/pipeline_state.py` | New file — `PipelineState` model |
| `nodes/verify_signature.py` | **Deleted** — replaced by `verify_signature()` function |
| `nodes/parse_whatsapp_payload.py` | **Deleted** — `Event` constructed in worker before pipeline |
| `nodes/load_context.py` | Remove `Event` reconstruction fallback; only loads `sender_memory` |
| `nodes/classify_intent.py` | `ctx.state.intent = ...` |
| `nodes/emit_agent_job.py` | Read `ctx.state.intent` |
| `nodes/run_agent.py` | Read `ctx.state.sender_memory`; `ctx.state.agent_result = ...` |
| `nodes/save_message.py` | Read `ctx.state.agent_result` |
| `nodes/send_reply.py` | Read `ctx.state.agent_result`; `ctx.state.delivered = True` |
| `nodes/route_by_intent.py` | Read `ctx.state.intent` |
| `nodes/parallel.py` | Merge `state` via `model_dump` + `PipelineState(**merged)` |
| `workflows/whatsapp.py` | Remove `VerifySignatureNode` and `ParseWhatsAppPayloadNode` from webhook workflow |
| `worker/__init__.py` | Pre-pipeline: verify signature, build `Event`, construct `Context`; read `ctx.state.agent_result` |
| `agents/claude.py` | Read `ctx.state.sender_memory` |
| `cli.py` | Read `ctx.state.agent_result` |
| `specs/features/workflows/workflow-engine.md` | Update Context and Node sections |

## Acceptance Criteria

- [ ] `PipelineState` defined in `entities/pipeline_state.py` as a non-frozen Pydantic model
- [ ] `Context` has no `job` field; `event` is required; `state: PipelineState` is the only accumulator
- [ ] `verify_signature` is a plain function, not a node
- [ ] `VerifySignatureNode` and `ParseWhatsAppPayloadNode` are deleted
- [ ] `Event` is constructed in `Worker._handle` before the workflow runs
- [ ] `LoadContextNode` no longer reconstructs `Event` from `job.payload`
- [ ] All nodes read/write pipeline data via `ctx.state.*`
- [ ] `worker/__init__.py` reads `ctx.state.agent_result`
- [ ] `cli.py` reads `ctx.state.agent_result`
- [ ] `agents/claude.py` reads `ctx.state.sender_memory`
- [ ] `ParallelNode` correctly merges two `PipelineState` instances
- [ ] `workflow-engine.md` spec updated to reflect the new `Context` shape
- [ ] All existing CLI and worker flows run correctly end-to-end

## Dependencies

- `specs/features/workflows/workflow-engine.md` — Implemented
