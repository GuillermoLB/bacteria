# Feature: Workflow Engine

**Status**: Draft
**Owner**: GuillermoLB
**Last Updated**: 2026-04-13

## Purpose

Define how multi-step processing pipelines are composed in bacteria. Every job that enters the system — whether from a webhook, a schedule, or an agent request — is executed by running a workflow. This spec defines the building blocks: `Node`, `Context`, `Workflow`, and how routing, branching, and registration work.

## Core concepts

### Node

An atomic, single-responsibility processing unit. Takes a `Context`, does one thing, returns an enriched `Context`. Nodes are independent and reusable across workflows.

```python
class Node(Protocol):
    async def run(self, ctx: Context) -> Context: ...
```

Concrete nodes receive their dependencies via constructor injection:

```python
class ParsePayloadNode:
    async def run(self, ctx: Context) -> Context:
        payload = parse_whatsapp(ctx.raw_payload)
        return ctx.model_copy(update={"payload": payload})

class DispatchToAgentNode:
    def __init__(self, runner: AgentRunner):
        self.runner = runner

    async def run(self, ctx: Context) -> Context:
        result = await self.runner.run(ctx.payload)
        return ctx.model_copy(update={"agent_result": result})
```

### Context

The shared state that flows through a workflow. A Pydantic model — immutable, extended via `model_copy(update={...})`. Every node reads what it needs and adds what it produces.

```python
class Context(BaseModel):
    model_config = ConfigDict(frozen=True)

    job: Job
    event: Event | None = None
    raw_payload: dict = {}
    payload: dict = {}
    intent: str | None = None
    agent_result: str | None = None
```

Context is a domain type. It knows nothing about the workflow engine. Nodes that return `Context` are decoupled from infrastructure.

### Workflow

A generic executor — an ordered list of nodes run in sequence. Not subclassed per use case. Workflows are instances, not classes.

```python
class Workflow:
    def __init__(self, nodes: list[Node]):
        self.nodes = nodes

    async def run(self, ctx: Context) -> Context:
        for node in self.nodes:
            ctx = await node.run(ctx)
        return ctx
```

Wiring a workflow is constructing an instance:

```python
whatsapp_workflow = Workflow(nodes=[
    VerifySignatureNode(secret=settings.whatsapp_secret),
    ParsePayloadNode(),
    DispatchToAgentNode(runner=agent_runner),
    SendReplyNode(client=whatsapp_client),
])
```

## Routing — how jobs reach the right workflow

The worker claims a job and looks up the right workflow in a registry keyed by `(source, event_type)`:

```python
registry = {
    ("whatsapp", "message"):  whatsapp_workflow,
    ("slack",    "message"):  slack_workflow,
    ("github",   "push"):     github_push_workflow,
    ("schedule", "report"):   daily_report_workflow,
}
```

Dispatch is a dict lookup — no guard functions, no `if/elif` chains. If no workflow is registered for a `(source, event_type)` pair, the job is marked FAILED with a clear error.

## Branching

Two patterns, used at different granularities.

### Pattern 1 — Emit a new event (preferred)

A node completes its work, determines the next step, and emits a new job with a different event type. The worker picks it up and routes it to the right workflow via the registry.

```
ParsePayloadNode
  → determines intent = "agent_request"
  → enqueues new job: (source="whatsapp", event_type="agent_request")

Worker picks up new job
  → registry routes to AgentWorkflow
```

Use this when:
- The branch is a meaningful state transition worth observing in the DB
- The two paths are substantially different workflows
- Latency of a second DB round trip is acceptable (almost always)

### Pattern 2 — Branch node (intra-workflow)

A node that delegates to a sub-workflow based on context state. Use when branching must happen mid-workflow without a queue round trip.

```python
class RouteByIntentNode:
    def __init__(self, routes: dict[str, Workflow]):
        self.routes = routes

    async def run(self, ctx: Context) -> Context:
        workflow = self.routes[ctx.intent]
        return await workflow.run(ctx)
```

Wired as:

```python
whatsapp_workflow = Workflow(nodes=[
    VerifySignatureNode(secret=secret),
    ParsePayloadNode(),              # sets ctx.intent
    RouteByIntentNode(routes={
        "command":  command_workflow,
        "question": agent_workflow,
        "media":    transcription_workflow,
    }),
])
```

Use this when:
- The branch decision depends on data only available mid-workflow
- A queue round trip would add unacceptable latency
- The paths reconverge (same nodes after the branch)

## Parallelism

Independent nodes that don't depend on each other's output can run in parallel using `asyncio.gather`. This is expressed as a node:

```python
class ParallelNode:
    def __init__(self, nodes: list[Node]):
        self.nodes = nodes

    async def run(self, ctx: Context) -> Context:
        results = await asyncio.gather(*[node.run(ctx) for node in self.nodes])
        # merge results into a single context
        merged = {}
        for result_ctx in results:
            merged.update(result_ctx.model_dump(exclude_unset=True))
        return ctx.model_copy(update=merged)
```

Use this when two nodes are genuinely independent and latency matters (e.g. loading conversation history from DB while loading skill files from disk).

## What lives where

| Concept | Location |
|---|---|
| `Node` protocol | `nodes/__init__.py` |
| `Context` model | `entities/context.py` |
| `Workflow` class | `workflows/__init__.py` |
| Concrete nodes | `nodes/<name>.py` |
| Workflow instances (wired) | `workflows/<domain>.py` |
| Registry | `worker/registry.py` |

Workflow files in `workflows/` are not class definitions — they are module-level instances, wired with their concrete nodes and dependencies. The registry maps `(source, event_type)` to these instances.

## What bacteria does NOT do

- No `.set_next()` chain — steps are not linked to their successors
- No `can_handle()` guard on every node — routing is done at dispatch, not inside the pipeline
- No `StepHandler` / `FunctionalProcessor` wrapping layers — a node is just a class with `run()`
- No subclassing `Workflow` per use case — `Workflow` is generic, instances carry the variation

## Acceptance Criteria

- [ ] `Node` protocol defined in `nodes/`
- [ ] `Context` Pydantic model defined in `entities/`
- [ ] `Workflow` generic class defined in `workflows/`
- [ ] Worker dispatches jobs via registry lookup `(source, event_type) → Workflow`
- [ ] At least one concrete workflow wired and tested end-to-end (worker → workflow → nodes)
- [ ] Branch node pattern tested: `RouteByIntentNode` delegates to correct sub-workflow
- [ ] No node imports from `api/` or `worker/` (inner layer boundary enforced)

## Dependencies

- `specs/features/scaffold/project-scaffold.md` — module structure must exist first
- `specs/features/queue/` — worker must be able to claim jobs before workflows run (not yet written)

---

**Status History**: Draft (2026-04-13)
