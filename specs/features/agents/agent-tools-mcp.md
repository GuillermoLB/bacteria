# Feature: Agent Tools (Middle Path)

**Status**: Implemented
**Owner**: GuillermoLB
**Last Updated**: 2026-04-27

## Purpose

Expand `ClaudeAgentRunner` so the agent can take autonomous actions inside `RunAgentNode` and maintain conversational continuity across messages — without giving the agent control over infrastructure concerns (auth, routing, delivery, queue). The pipeline remains the orchestrator; the agent gains reasoning capability via in-process tools and session continuity via the SDK's built-in session system.

This is the "middle path": the DAG is unchanged, the agent step becomes autonomous within it.

---

## Background

The current agent is conversational-only. It receives a message, reasons over a system prompt, and returns a text reply. Each job starts a fresh session — no memory of prior turns. All I/O (memory reads, message saving) happens as hard-wired nodes around it.

The middle path gives the agent two things:

1. **Session continuity** — the SDK persists conversation transcripts per sender. Each new message resumes the right session automatically, giving the agent memory of the conversation thread with no extra work.
2. **Tools** — in-process Python functions the agent can call during its reasoning loop for actions that require code: reading durable facts, writing to memory, emitting jobs.

See `references/agentic-pipeline-patterns.md` for validation of this pattern across Dify, Google ADK, Temporal, Haystack, and others.

---

## Two memory layers

The SDK has its own session/memory system. It is important to understand what it covers and what it does not, so we don't build things the SDK already provides.

| Layer | What it stores | Managed by | Scope |
|---|---|---|---|
| **SDK sessions** | Full conversation transcript (every turn) | SDK automatically, JSONL under `~/.claude/projects/` | One conversation thread per `session_id` |
| **Bacteria memory files** | Discrete facts the agent decides to retain (name, preferences, ongoing tasks) | `write_memory` tool + `SaveMessageNode` | Cross-conversation, durable, human-readable |

**SDK sessions** handle conversation continuity — the agent remembers what was said in prior messages from the same sender. This replaces the need to inject raw conversation history into the system prompt.

**Bacteria memory files** (`context/memory/{sender_id}.md`) handle durable facts — things the agent explicitly decides to remember long-term. These are injected into the system prompt via `LoadContextNode` so they are available from turn one without a tool call.

`SaveMessageNode` currently appends raw turns to the memory file. With SDK sessions in place, this is redundant for conversation history. `SaveMessageNode` should be repurposed to append only facts the agent explicitly signals — or removed in favour of `write_memory` tool calls. This is a decision for the memory spec; for now `SaveMessageNode` stays.

---

## What changes

### What stays the same

- `Workflow` DAG structure — same nodes, same order
- `RunAgentNode` — same interface, same place in the pipeline
- `AgentRunner` protocol — unchanged
- Infrastructure nodes (`VerifySignatureNode`, `ParsePayloadNode`, `EmitAgentJobNode`, `LoadContextNode`, `SaveMessageNode`, `SendReplyNode`) — untouched
- `max_turns` and `max_budget_usd` safety caps — still mandatory

### What changes

- `ClaudeAgentRunner` gains `session_id` support — passed per-sender to resume SDK sessions
- `ClaudeAgentRunner` accepts a tool server at construction time
- Tool functions live in `src/bacteria/tools/` as plain Python async functions
- The SDK wraps them in-process via `create_sdk_mcp_server` — no HTTP server, no sidecar
- `ClaudeAgentRunner.run()` captures the `session_id` from `ResultMessage` and returns it alongside the text result, so the caller can persist it per sender
- `dependencies.py` wires the tools into the runner at startup

---

## Architecture

```
AgentRequestWorkflow (pipeline — unchanged)
  LoadContextNode         → ctx.sender_memory (durable facts)
  RunAgentNode            → ctx.agent_result
    │
    └── ClaudeAgentRunner.run(ctx)
          system_prompt:  soul.md + ctx.sender_memory
          session_id:     ctx.event.sender_id session UUID  ← resumes conversation
          tools:          [write_memory, emit_job, ...]     ← in-process Python functions
          │
          └── SDK agent loop (autonomous, bounded by max_turns / max_budget_usd)
                SDK replays prior turns from session transcript
                reasons → calls tools → reasons → ... → final reply
                ResultMessage.session_id returned for persistence
  SaveMessageNode         → persists durable facts (scope TBD in memory spec)
  SendReplyNode           → delivers reply
```

---

## Session continuity

### How it works

The SDK stores conversation transcripts as JSONL files under `~/.claude/projects/`. Passing `session_id` to `ClaudeAgentOptions` resumes a prior session — the full prior conversation is replayed as context before the new prompt.

After each run, `ResultMessage.session_id` contains the session UUID (new or resumed). This must be stored per sender so the next message can resume it.

### Session storage

Session UUIDs are stored in the Bacteria memory file for each sender (`context/memory/{sender_id}.md`), in a structured header section:

```markdown
---
session_id: 550e8400-e29b-41d4-a716-446655440000
---

## Facts
- Name: Guillermo
- Timezone: Europe/Madrid
```

`LoadContextNode` reads the file and extracts `session_id` for the runner. `SaveMessageNode` (or a new `SaveSessionNode`) writes the updated `session_id` back after each run.

Alternatively: store session UUIDs in the DB (a `sender_sessions` table). Simpler to query, but adds a schema dependency. Decision deferred — start with the memory file.

### `ClaudeAgentRunner` changes

```python
async def run(self, ctx: Context) -> tuple[str, str]:
    # returns (reply_text, session_id)
    ...
    session_id = ctx.session_id  # loaded from memory file by LoadContextNode

    options = ClaudeAgentOptions(
        model=self.model,
        system_prompt=system_prompt,
        session_id=session_id,           # None = new session
        max_turns=self.max_turns,
        max_budget_usd=self.max_cost,
        setting_sources=["user", "project"],
        mcp_servers={"bacteria": self.tool_server} if self.tool_server else {},
        allowed_tools=self.allowed_tools,
    )

    result_text = ""
    result_session_id = session_id
    async for message in query(prompt=ctx.event.message_text, options=options):
        if isinstance(message, AssistantMessage):
            text = _extract_text(message)
            if text:
                result_text = text
        if isinstance(message, ResultMessage):
            result_session_id = message.session_id

    return result_text, result_session_id
```

`RunAgentNode` receives the `(text, session_id)` tuple and sets both on context:

```python
result, session_id = await self.runner.run(ctx)
return ctx.model_copy(update={"agent_result": result, "session_id": session_id})
```

`Context` gains a `session_id: str | None = None` field.

---

## How tools work

The SDK provides `tool()` decorator and `create_sdk_mcp_server()` to wrap Python functions as in-process tools. No network, no HTTP — the server object is passed directly to `ClaudeAgentOptions.mcp_servers`.

```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ToolAnnotations

@tool("write_memory", "Append a durable fact to the sender's memory file",
      {"sender_id": str, "fact": str})
async def write_memory(args: dict) -> dict:
    path = Path(f"context/memory/{args['sender_id']}.md")
    with path.open("a") as f:
        f.write(f"\n- {args['fact']}")
    return {"content": [{"type": "text", "text": "fact saved"}]}

bacteria_server = create_sdk_mcp_server(
    name="bacteria", version="1.0.0", tools=[write_memory, emit_job]
)

options = ClaudeAgentOptions(
    mcp_servers={"bacteria": bacteria_server},
    allowed_tools=["mcp__bacteria__write_memory", "mcp__bacteria__emit_job"],
    ...
)
```

Tools in `allowed_tools` are auto-approved — no permission prompt needed.

---

## Tool catalogue

### Phase 1 — Memory tools

SDK sessions handle conversation history. The memory file handles durable facts. The agent needs symmetric read/write access to that facts layer — `LoadContextNode` provides a snapshot at job start, but that snapshot is stale after a `write_memory` call.

| Tool | Description | Scope |
|---|---|---|
| `read_memory` | Read the current memory file for a sender | `context/memory/{sender_id}.md`, read-only |
| `write_memory` | Append a durable fact to the sender's memory file | `context/memory/{sender_id}.md`, append-only |

### Phase 2 — Context Hub tools

| Tool | Description | Scope |
|---|---|---|
| `read_context_file` | Read a file under `context/` by relative path | `context/` subtree only — rejects path traversal |
| `list_context_files` | List files under a `context/` path | `context/` subtree only |

### Phase 3 — Action tools

| Tool | Description | Scope |
|---|---|---|
| `emit_job` | Enqueue a new job into the Bacteria queue | Allowlisted `event_type` values only |
| `send_message` | Send a message to a channel proactively | Injected channel client, sender scoped |

---

## Tool safety model

1. **Scope strictly** — each tool enforces its own boundaries in code. `read_context_file` rejects paths outside `context/`. `emit_job` rejects unknown `event_type` values.
2. **Read tools are pure** — mark with `readOnlyHint=True` for parallel execution.
3. **Write tools are explicit** — listed individually in `allowed_tools` in `dependencies.py`. Reviewable at a glance.
4. **No queue bypass** — the agent cannot claim, complete, or fail jobs. Queue state is infrastructure-only.
5. **No raw filesystem access** — do not add `Read`, `Write`, `Edit`, or `Bash` to `allowed_tools`. Custom scoped tools only.

---

## File layout

```
bacteria/
└── tools/
    ├── __init__.py         # exports: bacteria_tool_server
    ├── memory.py           # write_memory (Phase 1), read_memory (Phase 2 if needed)
    ├── context_hub.py      # read_context_file, list_context_files
    └── actions.py          # emit_job, send_message
```

`__init__.py` assembles all tools into a single `create_sdk_mcp_server` call and exports the server object.

---

## Wiring in `dependencies.py`

```python
from bacteria.tools import bacteria_tool_server

runner = ClaudeAgentRunner(
    model="claude-sonnet-4-6",
    max_turns=20,
    max_cost=1.0,
    tool_server=bacteria_tool_server,
    allowed_tools=["mcp__bacteria__read_memory", "mcp__bacteria__write_memory"],
)
```

Adding a new tool = implement in `tools/`, register in the server, add to `allowed_tools`. That's the full change surface.

---

## Implementation plan

### Step 1 — Add session continuity to `ClaudeAgentRunner`

- Add `session_id` param to `ClaudeAgentOptions` call
- Return `(text, session_id)` from `run()`
- Update `RunAgentNode` to set `ctx.session_id`
- Add `session_id: str | None` to `Context`
- Update `LoadContextNode` to extract `session_id` from memory file header
- Update `SaveMessageNode` to write back updated `session_id`

No tools yet. Test: send two sequential WhatsApp messages from the same sender, verify the agent recalls the first in the second.

### Step 2 — Extend `ClaudeAgentRunner` with tool server

Add `tool_server` and `allowed_tools` params. Backward-compatible: both default to empty/None.

### Step 3 — Implement `read_memory` and `write_memory` (`tools/memory.py`)

Assemble `bacteria_tool_server` in `tools/__init__.py`. Wire into `dependencies.py`.

### Step 4 — Test end-to-end

Send a message asking the agent to remember a preference. Verify:
- Agent calls `write_memory` during its loop
- Fact is appended to `context/memory/{sender_id}.md`
- Agent calls `read_memory` to confirm the write
- Next message confirms the agent recalls it (via system prompt injection)
- `max_turns` and `max_budget_usd` are enforced

### Step 5 — Expand incrementally (Phase 2, Phase 3)

One tool at a time. Each addition: implement → register → add to `allowed_tools` → test.

---

## What the agent does NOT get

| Capability | Why it stays in the pipeline |
|---|---|
| Webhook signature verification | Security — must run before any processing |
| Payload parsing | Anti-corruption — agent works with `Event`, not raw JSON |
| Job claiming / completing | Queue integrity — agent cannot manipulate its own job |
| Reply delivery | Delivery is observable infrastructure, not reasoning |
| Retry logic | Belongs to the worker, not the agent |
| Raw filesystem access (`Read`, `Bash`) | Replaced by scoped custom tools |

---

## Acceptance Criteria

### Session continuity

```
Given two sequential WhatsApp messages from the same sender
When the second message arrives
Then ClaudeAgentRunner resumes the SDK session from the first message
And the agent recalls context from the first turn without it being re-injected
And a new session_id is NOT created (the existing one is reused)
```

```
Given a sender with no prior session
When their first message arrives
Then ClaudeAgentRunner starts a new session (session_id=None)
And ResultMessage.session_id is persisted to context/memory/{sender_id}.md
```

### Phase 1 — write_memory tool

```
Given the agent decides to remember a fact about the sender
When the agent calls write_memory with a fact string
Then the fact is appended to context/memory/{sender_id}.md
And existing content is not overwritten
```

```
Given tool_server=None
When ClaudeAgentRunner runs
Then it behaves identically to the current implementation
```

### Phase 2 — Context Hub tools

```
Given read_context_file is in allowed_tools
When the agent calls read_context_file with a path outside context/
Then the tool returns an error
And the agent loop continues without crashing the job
```

### Phase 3 — Action tools

```
Given emit_job is in allowed_tools
When the agent calls emit_job with an unknown event_type
Then the tool returns a validation error
And no job is enqueued
```

---

## Decisions deferred

- **Session storage location** — memory file header vs DB `sender_sessions` table. Start with memory file (no schema change). Migrate to DB if querying sessions becomes needed.
- **`SaveMessageNode` scope** — with SDK sessions handling transcript, does `SaveMessageNode` still append raw turns? Probably not. Repurpose to write `session_id` only, or rename to `SaveSessionNode`. Formalise in `specs/features/memory/`.
- **`write_memory` vs `SaveMessageNode` conflict** — both write to the same file. Convention: `SaveMessageNode` writes structured metadata (session_id, timestamps); `write_memory` appends free-form facts. Formalise in memory spec.

---

## Dependencies

- `specs/features/agents/agent.md` — AgentRunner protocol, ClaudeAgentRunner
- `specs/features/workflows/webhook-to-agent-flow.md` — pipeline this sits inside
- `specs/features/memory/memory.md` — memory file format and conventions
- `references/agentic-pipeline-patterns.md` — pattern validation and rationale
- `references/claude-agent-sdk.md` — `tool()`, `create_sdk_mcp_server()`, `ClaudeAgentOptions`, `ResultMessage`

---

**Status History**: Draft (2026-04-24) → revised: MCP replaced with in-process SDK tools (2026-04-27) → revised: SDK session continuity added, tool catalogue narrowed (2026-04-27) → Implemented (2026-04-27)
