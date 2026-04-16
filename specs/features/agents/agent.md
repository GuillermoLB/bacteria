# Feature: Agent

**Status**: Draft
**Owner**: GuillermoLB
**Last Updated**: 2026-04-15

## Purpose

Define what an agent is in Bacteria, what it is made of, and how it executes. An agent is not a standalone process — it is the AI runtime that runs inside `RunAgentNode` as part of `AgentRequestWorkflow`. Its job: receive a fully assembled prompt, run an agentic loop using tools, and return a final text reply.

---

## What an agent is

An agent is the combination of:

1. **An identity** (who it is)
2. **Task instructions** (what it must do now)
3. **A model** (which LLM runs the loop)
4. **Tools** (what actions it can take)
5. **Skills** (what capabilities it has)
6. **Context** (what it knows: history + file system)
7. **Safety constraints** (how far it can go)

All of these are assembled by the nodes that precede `RunAgentNode` in `AgentRequestWorkflow`. The agent itself receives a fully formed prompt — it does not load its own dependencies.

---

## Elements

### 1. Soul (`soul.md`)

The first thing injected into the system prompt, before any task instruction.

A deep markdown file describing:
- Who the agent is at the core
- Values, mission, goals
- How it wants to show up and why it does things

This is not a config file. It is identity. A heavy model like Opus reading a well-written `soul.md` produces qualitatively different interactions than a bare system prompt.

**Loaded by**: `LoadIdentityNode`
**Source**: `context/identity/soul.md`
**Set on**: `ctx.identity`

System prompt assembly order:
```
soul.md content
  → task instructions
  → skills
  → conversation history
  → current message
```

---

### 2. Task instructions

What the agent must do in this specific invocation. Injected after the soul in the system prompt. These can be static (hardcoded per workflow) or dynamic (derived from the incoming message or job payload).

---

### 3. Model (pluggable, per use case)

The agent is not tied to a single model. The model choice is a deliberate cost/capability tradeoff made per workflow:

| Agent type | Model | Use case |
|---|---|---|
| Light | Fast/cheap (e.g. Haiku) | Quick replies, simple tool use |
| Moderate | Mid-tier (e.g. Sonnet) | Research, multi-step reasoning |
| Heavy | Opus + Claude Code subprocess | Deep research, delegation, computer use |

The model is configured at the `AgentRunner` level — workflows choose which runner to wire in.

---

### 4. Tools

The action surface of the agent. Tools are Python-defined and injected into the agent loop. The agent calls them during its reasoning turns.

Examples:
- **Web search** — query the internet for current information
- **Save to file system** — write a note or idea to the context hub
- **Delegate task** — spawn a full Claude Code subprocess in the cloud; the most powerful, most expensive option

Defined in `tools/`. Passed to the `AgentRunner` at construction time.

**Budget note**: the delegate-task tool can spawn a full Claude Code agent. `max_turns` and `max_cost` caps are mandatory — uncapped runs have reached $50+ in a single invocation.

---

### 5. Skills

Markdown files that describe capabilities. Loaded from `skills/` and injected into the system prompt as text. They are not Python code — they are prompt content.

Examples: `linkedin-writer.md`, `youtube-packager.md`, `research-scanner.md`, `slide-creator.md`.

A skill file tells the agent: here is how to do X. The agent reads it as context and applies it.

**Loaded by**: `LoadSkillsNode`
**Source**: `skills/*.md` (filtered by channel/context relevance)
**Set on**: `ctx.skills`

---

### 6. Context

Two sources of context, loaded before the agent runs:

**Short-term memory** — conversation history for this `sender_id`, loaded from DB. Ordered list of prior messages in this conversation thread.

**Long-term memory — the Context Hub** — a structured file system the agent can navigate:

```
context/
├── identity/     # soul.md and related identity files
├── inbox/        # temporary: ideas, TODOs (always processed, never accumulates)
├── areas/        # ongoing domains: content, clients, products, health...
├── projects/     # active time-bounded work
├── knowledge/    # SOPs, research, reference docs
└── archive/      # completed/inactive — agents skip by default
```

Navigation uses a **three-tier loading system** to keep the context window lean:

```
Level 0 — abstract.md   (1 line per folder, whole hub ~2000 tokens)
  Level 1 — overview.md  (short description: what's here, relationships, which workflows use it)
    Level 2 — full file  (only loaded when the agent determines it is needed)
```

The agent never blindly crawls. It reads abstracts first, then overviews, then decides which full files it needs. This prevents context bloat.

**Loaded by**: `LoadContextNode`
**Set on**: `ctx.history` (short-term), accessed via tools or context loader (long-term)

---

### 7. Safety constraints

Applied at the `AgentRunner` level:

| Constraint | Purpose |
|---|---|
| `max_turns` | Caps the number of reasoning/tool-call iterations |
| `max_cost` | Caps total API spend for a single agent run |

These are mandatory for heavy agents (Claude Code subprocess). For light agents they are optional but recommended.

---

## The agent spectrum

`BaseAgentRunner` is a Protocol. The same workflow wires in different runners depending on the use case:

```
Simple LLM call + tools
  → Pydantic AI / raw API loop
    → LangGraph
      → Full Claude Code subprocess
(cheap, fast)                         (most powerful, most expensive)
```

This is why the abstraction exists. The infrastructure (workflow, nodes, queue) is identical for all three. Only the runner changes.

```python
class AgentRunner(Protocol):
    async def run(self, ctx: Context) -> str: ...
```

Concrete implementations live in `agents/`. Workflows reference the protocol, never the concrete class.

---

## Execution flow

```
AgentRequestWorkflow
  LoadIdentityNode    → ctx.identity   (soul.md)
  LoadSkillsNode      → ctx.skills     (markdown skill files)
  LoadContextNode     → ctx.history    (DB conversation history)
  RunAgentNode        → ctx.agent_result
    │
    └── assembles prompt: identity + skills + history + message
        calls AgentRunner.run(ctx)
        agentic loop: model reasons → calls tools → observes results → iterates
        terminates: final reply OR max_turns reached
  SendReplyNode       → delivers ctx.agent_result to sender
```

---

## What lives where

| Element | Location |
|---|---|
| `AgentRunner` protocol | `agents/__init__.py` |
| Concrete runners | `agents/<provider>.py` |
| Tool definitions | `tools/<name>.py` |
| Skill files | `skills/<name>.md` |
| Soul and identity | `context/identity/soul.md` |
| Context Hub | `context/` |
| `LoadIdentityNode`, `LoadSkillsNode`, `LoadContextNode`, `RunAgentNode` | `nodes/` |
| `AgentRequestWorkflow` | `workflows/agent.py` |

---

## Acceptance Criteria

- [ ] `AgentRunner` protocol defined in `agents/`
- [ ] At least one concrete runner implemented (e.g. Pydantic AI or raw API)
- [ ] `soul.md` loaded and injected as the first section of the system prompt
- [ ] Skills loaded from `skills/` and injected after identity
- [ ] Conversation history loaded from DB by `sender_id`
- [ ] Context Hub navigation respects the three-tier system (abstract → overview → full)
- [ ] `max_turns` and `max_cost` enforced on heavy runners
- [ ] Agent runner is swappable — workflow references the protocol, not the concrete class
- [ ] `RunAgentNode` sets `ctx.agent_result` on success
- [ ] On runner timeout or provider error: job marked FAILED and retried

---

## Dependencies

- `specs/features/scaffold/project-scaffold.md` — module structure
- `specs/features/workflows/workflow-engine.md` — Node, Context, Workflow
- `specs/features/workflows/webhook-to-agent-flow.md` — the full flow this node lives inside

---

**Status History**: Draft (2026-04-15)
