# Spec Cleanup: Agent Architecture Consistency

**Status**: Implemented
**Owner**: GuillermoLB
**Last Updated**: 2026-04-17
**Priority**: High

## Purpose

Several specs have drifted out of sync after decisions made during the agent and memory design sessions. This cleanup aligns all specs with the current design before implementation begins.

## What changed (and why)

During design of the agent and memory features, two decisions were made that affect multiple specs:

1. **File-based memory instead of DB** — conversation history and long-term facts live in `context/memory/{sender_id}.md`, not in a `messages` DB table.

2. **`LoadIdentityNode` and `LoadSkillsNode` removed** — soul.md is passed directly as `system_prompt` to the runner; skills are loaded natively by the Claude Agent SDK (and injected as text by other providers). `LoadContextNode` handles memory file loading only.

One decision was **reconsidered** before being applied:

3. **Per-provider nodes reverted** — we briefly moved provider logic into per-node classes (`RunClaudeAgentNode`), but this loses the decoupling ADR-0002 was protecting. Workflows would be coupled to a concrete provider. The correct design is: a lean `AgentRunner` protocol in `agents/`, one concrete adapter per provider, and a single generic `RunAgentNode` that calls `self.runner.run(ctx)`. Provider choice lives in `dependencies.py` only.

---

## Requirements

- [x] **`agent.md` runtime section updated**: replace per-provider nodes with `AgentRunner` protocol + concrete adapters in `agents/`. `RunAgentNode` is generic and calls the protocol.
- [x] **`webhook-to-agent-flow.md` Job 2 updated**: replaced `LoadIdentityNode`, `LoadSkillsNode` with `LoadContextNode`, `RunAgentNode` (generic), `SaveMessageNode`.
- [x] **`webhook-to-agent-flow.md` `LoadContextNode` description updated**: loads `context/memory/{sender_id}.md` only, no DB.
- [x] **`architecture.md` `agents/` description updated**: `AgentRunner` protocol + concrete adapters. Provider choice injected via `dependencies.py`.
- [x] **`decisions/index.md`**: no changes needed — ADR-0002 remains valid.

---

## The `AgentRunner` protocol

Simple, stable, provider-agnostic:

```python
class AgentRunner(Protocol):
    async def run(self, ctx: Context) -> str: ...
```

`RunAgentNode` calls this. Each provider implements it in `agents/`:

```
agents/
├── __init__.py          # AgentRunner protocol defined here
├── claude.py            # ClaudeAgentRunner — uses claude-agent-sdk
├── openai.py            # OpenAIAgentRunner — future
└── gemini.py            # GeminiAgentRunner — future
```

Each adapter is responsible for its own system prompt assembly, skill injection strategy, and history management. Phase 1 implements `ClaudeAgentRunner` only.

`RunAgentNode` is generic:

```python
class RunAgentNode:
    def __init__(self, runner: AgentRunner):
        self.runner = runner

    async def run(self, ctx: Context) -> Context:
        result = await self.runner.run(ctx)
        return ctx.model_copy(update={"agent_result": result})
```

Provider choice in `dependencies.py`:

```python
runner = ClaudeAgentRunner(model="claude-sonnet-4-6", max_turns=20)
agent_workflow = Workflow(nodes=[
    LoadContextNode(),
    RunAgentNode(runner=runner),
    SaveMessageNode(),
    SendReplyNode(),
])
```

---

## Changes per file

### `specs/features/agents/agent.md`
- Replace "Runtime" section: remove per-provider nodes, add `AgentRunner` protocol + adapters pattern
- `RunAgentNode` is generic — takes a runner via constructor injection
- `ClaudeAgentRunner` is the Phase 1 concrete adapter in `agents/claude.py`
- Update "What lives where" table
- Update acceptance criteria

### `specs/features/workflows/webhook-to-agent-flow.md`
Job 2 node list:
```
Before:
  LoadIdentityNode
  LoadSkillsNode
  LoadContextNode   (DB history)
  RunAgentNode
  SendReplyNode

After:
  LoadContextNode   (context/memory/{sender_id}.md)
  RunAgentNode      (generic, calls AgentRunner protocol)
  SaveMessageNode
  SendReplyNode
```

Update `LoadContextNode` description: loads `context/memory/{sender_id}.md`, not DB.
Update `Context at completion`: remove `identity`, `skills`, `history` fields; add `sender_memory`, `agent_result`.

### `specs/architecture/architecture.md`
Update `agents/` description:
```
agents/  — AgentRunner protocol + concrete adapters per provider
           (ClaudeAgentRunner, OpenAIAgentRunner, etc.)
           Provider choice injected via dependencies.py — never referenced directly from workflows.
```

---

## Acceptance Criteria

```
Given all changes are applied
When reading any spec that references the agent execution flow
Then LoadIdentityNode and LoadSkillsNode do not appear
And RunAgentNode is generic (calls AgentRunner protocol)
And DB-based conversation history does not appear in LoadContextNode descriptions
```

```
Given the agent spec is updated
When reading the runtime section
Then AgentRunner is a Protocol defined in agents/
And ClaudeAgentRunner is the Phase 1 concrete adapter
And RunAgentNode receives the runner via constructor injection
```

```
Given architecture.md is updated
When reading the agents/ module description
Then it reflects AgentRunner protocol + adapters
And provider choice via dependencies.py
```

---

**Status History**: Draft (2026-04-17)
