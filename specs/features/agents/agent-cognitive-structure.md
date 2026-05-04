# Feature: Agent Cognitive Structure

**Status**: Draft
**Owner**: GuillermoLB
**Last Updated**: 2026-04-29

## Purpose

Give `ClaudeAgentRunner` a coherent cognitive architecture. Right now the agent has all the right components — identity, memory, skills, tools — but they are wired together poorly: memory mixes facts with raw history, the soul gives identity but no cognitive guidance, skills are opaque at runtime, and tool call intermediaries are invisible to observability.

This spec restructures those components so each layer does one job and they compose cleanly.

---

## Background

The current agent is assembled as:

```
system_prompt = soul.md + entire {sender_id}.md (facts + history mixed)
```

This has three problems:

1. **The system prompt grows unboundedly.** Every conversation turn is appended to `{sender_id}.md` and re-injected whole. The SDK session already carries conversation history — this is double-loading and adds noise that degrades reasoning quality.

2. **Facts are buried in history.** The agent has to read past its own conversation to find durable facts (name, preferences, ongoing projects). As the file grows, facts become harder to locate and easy to miss.

3. **The agent has no cognitive guide.** `soul.md` defines who the agent is but not how to operate. The agent has memory tools, SDK-loaded skills, and session continuity — but no explicit orientation on when to reach for each. Skills are surfaced by the SDK from `.claude/skills/` frontmatter, so they are discoverable — but the soul gives no guidance on when skills apply vs. tools vs. direct reasoning.

---

## Cognitive model

An agent run is structured in five layers, each with a single responsibility:

```
┌───────────────────────────────────────────────────────────────┐
│                         SYSTEM PROMPT                         │
│                                                               │
│  1. IDENTITY     soul.md                                      │
│     Who I am. Character, values, principles.                  │
│                                                               │
│  2. CAPABILITIES skills.md                                    │
│     What I know how to do. Skill catalog with invocation      │
│     guidance. One entry per skill file in .claude/skills/.    │
│                                                               │
│  3. FACTS        context/memory/{sender_id}.md ## Facts       │
│     What I know about this user. Durable, low-volume.         │
│     Always relevant.                                          │
│                                                               │
│  4. TOOLS        injected prose                               │
│     What actions I can take. One line per tool explaining     │
│     when to call it. Complements the SDK tool definitions.    │
│                                                               │
└───────────────────────────────────────────────────────────────┘

  5. SESSION        SDK session_id  (not in system prompt)
     What was said. Conversation history managed by the SDK.
     Replayed automatically on session resume. Never re-injected.
```

Each layer is independently readable, independently updatable, and independently cacheable.

---

## Layer definitions

### 1. Identity — `soul.md`

**Location**: `context/identity/soul.md`  
**Injected by**: `ClaudeAgentRunner` (already implemented)  
**Changes**: Extend with a **cognitive guide** section that tells the agent how to use the other layers. Not more rules — orientation.

```markdown
# Identity

You are Bacteria — a capable, direct AI assistant embedded in a self-hosted automation system.

## Principles

- Be concise and clear. Avoid unnecessary preamble.
- Prefer concrete answers over hedged non-answers.
- When asked to do something, do it — then explain if needed.
- Acknowledge uncertainty rather than hallucinating.

## How to use your capabilities

**Memory**: User facts are in your system prompt under `## Facts`. Use `write_memory` to
save new facts. Use `read_memory` only when you need to verify current state mid-turn.

**Skills**: Your skill catalog is listed below. Read it before acting on a new type of request.
If a skill applies, follow its instructions.

**Tools**: Listed in your system prompt under `## Tools`. Use them when reasoning alone is not
enough — prefer the minimal tool that accomplishes the goal.

**Conversation history**: The SDK replays your prior conversation automatically. You do not
need to ask the user to repeat themselves.
```

The cognitive guide is a fixed section — it doesn't change per user or per run. It belongs in `soul.md` because it's part of how the agent operates, not what it knows.

---

### 2. Capabilities — cognitive guide in `soul.md`

The SDK loads skills from `.claude/skills/` automatically when `setting_sources=["project"]` is set. Each skill's `name` and `description` frontmatter are surfaced to the model — skills are not opaque. No separate catalog file is needed.

What is missing is guidance on *when* to reach for skills vs. tools vs. direct reasoning. This belongs in `soul.md` as part of the cognitive guide — not as a separate file.

No new file. No new injection step. The SDK handles skill discovery; `soul.md` handles orientation.

---

### 3. Facts — `## Facts` section of `{sender_id}.md`

**Location**: `context/memory/{sender_id}.md`  
**Injected by**: `LoadContextNode` (changed: extract Facts section only)  
**Written by**: `write_memory` tool (changed: insert before `## History`) and `SaveMessageNode` for frontmatter fields

Memory file structure:

```markdown
---
name: Guillermo
type: user
last_updated: 2026-04-29
session_id: 550e8400-e29b-41d4-a716-446655440000
---

## Facts

Prefers Python. Working on Bacteria. Timezone: Europe/Madrid. Wants concise answers.

## History

### 2026-04-29 10:00 UTC
**User**: ...
**Assistant**: ...
```

**`LoadContextNode`** reads only from the start of the file to the `## History` heading (exclusive). This is the durable facts section — small, always relevant, never growing.

**`SaveMessageNode`** appends turns under `## History` as before. This section is NOT injected into the system prompt. It exists for human inspection and potential future summarization.

**`write_memory` tool** inserts new fact lines before the `## History` heading, not at end-of-file.

This is the only change to the memory file format — adding the explicit `## Facts` / `## History` split. Existing files without `## Facts` degrade gracefully: `LoadContextNode` falls back to everything before `## History`.

---

### 4. Tools — prose description injected into system prompt

**Location**: assembled in `ClaudeAgentRunner` from the `allowed_tools` list  
**Injected by**: `ClaudeAgentRunner` (new)

When tools are configured, a brief prose block is appended to the system prompt:

```
## Tools

- `read_memory(sender_id)` — read the current facts file for a sender. Use to verify state mid-turn.
- `write_memory(sender_id, fact)` — save a durable fact. Use when the user asks you to remember something or when you learn something worth keeping.
```

This is generated from a description dict on each tool, not hardcoded. Each tool registered in `bacteria_tool_server` carries a one-line `usage_hint` that appears here.

**Why?** The SDK provides tool definitions (name, parameters, description) but the agent sometimes needs guidance on *when* to reach for a tool, not just what it does. The system prompt hint complements the tool definition without duplicating it.

---

### 5. Session — SDK session continuity

**Managed by**: SDK (already implemented in `agent-tools-mcp.md`)  
**Not in system prompt**: conversation history is replayed by the SDK automatically.

No change to this layer. It is documented here for completeness so the full cognitive model is readable in one place.

---

## What changes

### `ClaudeAgentRunner` — system prompt assembly

```python
def _build_system_prompt(self, ctx: Context) -> str:
    parts = []

    soul = _read_file(_SOUL_PATH)
    if soul:
        parts.append(soul)

    facts = ctx.sender_memory or ""
    if facts:
        parts.append(facts)

    tools_hint = self._build_tools_hint()
    if tools_hint:
        parts.append(tools_hint)

    return "\n\n".join(parts)
```

`ctx.sender_memory` is now the facts section only (changed in `LoadContextNode`), not the full file.

### `LoadContextNode` — extract Facts section only

```python
def _extract_facts(content: str) -> str:
    """Return everything before ## History, after the frontmatter block."""
    # Strip frontmatter
    if content.startswith("---"):
        end = content.find("\n---\n", 3)
        if end != -1:
            content = content[end + 5:]

    # Take everything before ## History
    history_idx = content.find("\n## History")
    if history_idx != -1:
        return content[:history_idx].strip()

    return content.strip()
```

`ctx.sender_memory` becomes the facts section. `LoadContextNode` still extracts `session_id` from frontmatter as before.

### `write_memory` tool — insert before `## History`

```python
async def write_memory(args: dict) -> dict:
    path = Path(f"context/memory/{args['sender_id']}.md")
    content = path.read_text()

    fact_line = f"\n{args['fact']}"
    history_marker = "\n## History"

    if history_marker in content:
        insert_at = content.index(history_marker)
        updated = content[:insert_at] + fact_line + content[insert_at:]
    else:
        updated = content + fact_line

    path.write_text(updated)
    return {"content": [{"type": "text", "text": "fact saved"}]}
```

### `context/identity/skills.md` — new file

Created and maintained alongside skill files. Initial content: one row per skill in `.claude/skills/`.

### Intermediate tool call logging

`ClaudeAgentRunner` already iterates over all SDK messages. It should log non-text, non-result messages at debug level:

```python
async for message in query(prompt=prompt_text, options=options):
    if isinstance(message, AssistantMessage):
        ...
    elif isinstance(message, ResultMessage):
        ...
    else:
        logger.debug("agent_event", type=type(message).__name__, message=str(message))
```

This costs nothing and makes the agent's reasoning visible in logs.

---

## System prompt assembly order

```
soul.md           ← identity + cognitive guide (stable, cache-friendly)
## Facts          ← user facts (changes per sender)
## Tools          ← tool usage hints (changes when tools change)
```

Skills are surfaced by the SDK from `.claude/skills/` frontmatter — not injected here.

This order is intentional: stable content first, variable content last. The SDK's prompt caching (5-min TTL) benefits from stable prefixes.

---

## File layout

No new Python modules. Changes are contained in:

```
context/identity/
└── soul.md              # updated: add cognitive guide section

src/bacteria/
├── agents/
│   └── claude.py        # updated: _build_system_prompt(), tool hint injection, debug logging
├── nodes/
│   └── load_context.py  # updated: _extract_facts() — inject facts section only
└── tools/
    └── memory.py        # updated: write_memory inserts before ## History
```

---

## Acceptance Criteria

### Memory split

```
Given a sender with an existing memory file containing ## Facts and ## History sections
When LoadContextNode runs
Then ctx.sender_memory contains only the content before ## History
And the raw conversation history is NOT in the system prompt
```

```
Given a sender with a legacy memory file (no ## Facts heading)
When LoadContextNode runs
Then ctx.sender_memory contains everything after frontmatter (graceful fallback)
And the node does not raise an exception
```

```
Given the agent calls write_memory with a fact
When the tool runs
Then the fact is inserted before ## History in the memory file
And existing history entries are not affected
And the fact appears in ctx.sender_memory on the next turn (via LoadContextNode)
```

### Tool hints

```
Given ClaudeAgentRunner is configured with a tool_server
When the system prompt is assembled
Then a ## Tools section appears listing each tool with its usage hint
```

### Cognitive guide

```
Given a new soul.md with the cognitive guide section
When the agent receives a message asking it to remember something
Then the agent calls write_memory (guided by the cognitive guide)
And does NOT manually edit the memory file with Write tool
```

### Debug logging

```
Given the agent makes a tool call during its loop
When the SDK yields the tool call message
Then it is logged at debug level with type and content
And the job does not fail because of the log
```

---

## What does NOT change

- `AgentRunner` protocol — unchanged
- `RunAgentNode` — unchanged
- `SaveMessageNode` — unchanged (still appends turns under `## History`)
- `Context` model — unchanged
- Workflow structure — unchanged
- Tool catalogue (`tools/memory.py`) — only `write_memory` insert logic changes
- SDK session continuity — unchanged

---

## Decisions

**Memory file format**: explicit `## Facts` / `## History` split. The frontmatter carries metadata (`session_id`, `name`, `type`). Facts are prose/bullets above `## History`. History is timestamped turns below. The split is by heading, not by file.

**Skills**: the SDK surfaces skill name and description from `.claude/skills/` frontmatter automatically. No catalog file needed. Orientation on when to use skills lives in `soul.md`.

**Tool hints in system prompt**: brief prose per tool, not a full schema dump. The SDK provides schema to the model; the system prompt adds when-to-use guidance. Keep it to one line per tool.

**History not injected**: SDK sessions carry conversation history. Injecting it into the system prompt as well is redundant and harmful — it grows unboundedly and degrades reasoning by burying facts in noise. Raw history in the file is for human inspection only.

---

## Dependencies

- `specs/features/agents/agent.md` — AgentRunner protocol, ClaudeAgentRunner baseline
- `specs/features/agents/agent-tools-mcp.md` — session continuity, tool server wiring
- `specs/features/memory/memory.md` — memory file format and conventions

---

**Status History**: Draft (2026-04-29)
