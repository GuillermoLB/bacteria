# Feature: Agent

**Status**: Implemented
**Owner**: GuillermoLB
**Last Updated**: 2026-04-20

## Purpose

Define what an agent is in Bacteria and how it executes. An agent runs inside `RunAgentNode` as part of `AgentRequestWorkflow`. It receives a fully assembled context, runs an agentic loop using tools, and returns a final text reply.

---

## Runtime

`RunAgentNode` is a generic node that calls an `AgentRunner` protocol. The concrete runner is injected at startup via `dependencies.py` — workflows never reference a specific provider.

```python
class AgentRunner(Protocol):
    async def run(self, ctx: Context) -> str: ...
```

```
agents/
├── __init__.py     # AgentRunner protocol
├── claude.py       # ClaudeAgentRunner  ← Phase 1
├── openai.py       # OpenAIAgentRunner  ← future
└── gemini.py       # GeminiAgentRunner  ← future
```

Provider choice in `dependencies.py`:
```python
runner = ClaudeAgentRunner(model="claude-sonnet-4-6", max_turns=20)
```

**Phase 1: `ClaudeAgentRunner`** uses the Claude Agent SDK (`claude-agent-sdk`):

| Capability | How |
|---|---|
| System prompt | `ClaudeAgentOptions(system_prompt=soul.md + sender_memory)` |
| Skills | Auto-loaded from `.claude/skills/*/SKILL.md` via `setting_sources=["project"]` |
| Session history | Managed by SDK, resumable via `session_id` |
| Built-in tools | Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch |
| Custom tools | Via MCP servers in `.claude/settings.json` |
| Safety caps | `max_turns`, `max_cost` on `ClaudeAgentOptions` |

Future runners (OpenAI, Gemini) implement the same protocol. Each adapter handles its own system prompt assembly, skill injection strategy, and history format.

---

## What an agent is

An agent is the combination of:

1. **Identity** — who it is (`soul.md` injected as system prompt)
2. **Skills** — what capabilities it has (skill files in `.claude/skills/`)
3. **Memory** — what it knows about the user (`context/memory/{sender_id}.md`)
4. **Tools** — what actions it can take (built-in SDK tools + custom MCP tools)
5. **Model** — which LLM runs the loop (configured per workflow)
6. **Safety constraints** — `max_turns` and `max_cost`

---

## Elements

### 1. Soul (`soul.md`)

Injected as the `system_prompt`. Describes who the agent is — identity, values, mission. Not a config file. A well-written `soul.md` produces qualitatively different behavior than a bare system prompt.

**Source**: `context/identity/soul.md`

System prompt assembly:
```
soul.md
  + sender memory (context/memory/{sender_id}.md)
  + current message
```

---

### 2. Skills

Markdown files at `.claude/skills/<name>/SKILL.md`. Loaded automatically by the SDK when `setting_sources=["project"]` is set. One coherent capability per file.

Each skill has YAML frontmatter:

```markdown
---
name: linkedin-writer
description: Write LinkedIn posts with strong hooks, structured body, and clear CTA.
---

## How to write a LinkedIn post
...
```

The agent reads the skill catalog from the SDK and invokes skills by name during its loop. No `LoadSkillsNode` needed — the SDK handles this natively.

**Granularity rule**: one skill = one capability that passes the single-sentence test. "How to write LinkedIn posts" — yes. "How to be a personal assistant" — no.

---

### 3. Memory

Per-user facts, preferences, and conversation history from `context/memory/{sender_id}.md`. Loaded by `LoadContextNode` and appended to the system prompt before the agent runs.

Session-to-session conversation history is managed by the SDK via `session_id`. The memory file carries durable facts the agent has decided to keep — not raw message history.

See `specs/features/memory/memory.md`.

---

### 4. Tools

The SDK provides built-in tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch. Custom tools are added via MCP servers defined in `.claude/settings.json`.

The agent navigates the Context Hub as a filesystem using the built-in Read/Glob tools — no custom navigation tools needed.

**Budget note**: `max_turns` and `max_cost` are mandatory. Uncapped agent runs can reach $50+ per invocation.

---

### 5. Model

Configured per workflow via `ClaudeAgentOptions(model=...)`. The same `RunAgentNode` works with any model — workflows choose the right cost/capability tradeoff:

| Use case | Model |
|---|---|
| Quick replies, simple tool use | Haiku |
| Research, multi-step reasoning | Sonnet |
| Deep research, delegation | Opus |

---

## Execution flow

```
AgentRequestWorkflow
  LoadContextNode   → reads context/memory/{sender_id}.md → ctx.sender_memory
  RunAgentNode      → ctx.agent_result
    │
    └── calls AgentRunner.run(ctx)
        [ClaudeAgentRunner]: builds system_prompt: soul.md + ctx.sender_memory
                             calls claude-agent-sdk query()
                             SDK loop: reasons → invokes skills → calls tools → iterates
                             terminates: final reply OR max_turns reached
  SaveMessageNode   → appends turn to context/memory/{sender_id}.md
  SendReplyNode     → delivers ctx.agent_result to sender
```

No `LoadIdentityNode` or `LoadSkillsNode` — soul.md is assembled inside the runner, skills are loaded natively by the Claude SDK.

---

## Implementation shapes

### `RunAgentNode` (generic, in `nodes/`)

```python
class RunAgentNode:
    def __init__(self, runner: AgentRunner):
        self.runner = runner

    async def run(self, ctx: Context) -> Context:
        result = await self.runner.run(ctx)
        return ctx.model_copy(update={"agent_result": result})
```

### `ClaudeAgentRunner` (Phase 1, in `agents/claude.py`)

```python
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage

class ClaudeAgentRunner:
    def __init__(self, model: str, max_turns: int = 20, max_cost: float = 1.0):
        self.model = model
        self.max_turns = max_turns
        self.max_cost = max_cost

    async def run(self, ctx: Context) -> str:
        system_prompt = f"{read_file('context/identity/soul.md')}\n\n{ctx.sender_memory or ''}"

        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=system_prompt,
            max_turns=self.max_turns,
            max_cost=self.max_cost,
            setting_sources=["project"],  # loads skills from .claude/skills/
        )

        result = ""
        async for message in query(prompt=ctx.event.message_text, options=options):
            if isinstance(message, AssistantMessage):
                result = extract_text(message)

        return result
```

---

## What lives where

| Element | Location |
|---|---|
| `AgentRunner` protocol | `agents/__init__.py` |
| `ClaudeAgentRunner` (Phase 1) | `agents/claude.py` |
| `RunAgentNode` (generic) | `nodes/run_agent.py` |
| `LoadContextNode`, `SaveMessageNode` | `nodes/` |
| Skill files | `.claude/skills/<name>/SKILL.md` |
| Soul | `context/identity/soul.md` |
| User memory | `context/memory/{sender_id}.md` |
| Context Hub | `context/` |
| `AgentRequestWorkflow` | `workflows/agent.py` |

---

## Acceptance Criteria

- [x] `AgentRunner` protocol defined in `agents/__init__.py`
- [x] `ClaudeAgentRunner` implemented in `agents/claude.py` using `claude-agent-sdk`
- [x] `RunAgentNode` is generic — receives runner via constructor, calls `runner.run(ctx)`
- [x] `soul.md` + sender memory assembled into system prompt inside `ClaudeAgentRunner`
- [x] Skills loaded automatically by SDK from `.claude/skills/`
- [x] Each skill file has `name` and `description` frontmatter
- [x] `max_turns` and `max_cost` set on `ClaudeAgentRunner`
- [x] `RunAgentNode` sets `ctx.agent_result` on success
- [x] On error: job marked FAILED and retried by the worker
- [x] Workflows reference `AgentRunner` protocol only — never a concrete runner class

---

## Dependencies

- `specs/features/scaffold/project-scaffold.md` — Implemented
- `specs/features/workflows/workflow-engine.md` — Node, Context, Workflow
- `specs/features/memory/memory.md` — sender memory file
- `specs/features/workflows/webhook-to-agent-flow.md` — full flow

---

**Status History**: Draft (2026-04-15) → updated for Claude Agent SDK (2026-04-17) → restored AgentRunner protocol + adapters pattern (2026-04-17) → Implemented (2026-04-20)
