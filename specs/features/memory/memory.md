# Feature: Memory

**Status**: Implemented
**Owner**: GuillermoLB
**Last Updated**: 2026-04-20
**Priority**: High

## Purpose

Give agents continuity across conversations. An agent without memory treats every message as if it had never spoken to the user before.

## How it works

Everything lives in files under `context/memory/`:

```
context/memory/
├── MEMORY.md               # index — one line per file, always loaded (tier 0)
└── {sender_id}.md          # per-user: facts, preferences, conversation history
```

Example `{sender_id}.md`:
```markdown
---
name: Guillermo
type: user
last_updated: 2026-04-16
---

Prefers Python. Working on Bacteria. Timezone: Europe/Madrid. Wants concise answers.

## History

user: hey, can you help me with the queue spec?
assistant: sure, here's what I think...
```

`MEMORY.md` is loaded in tier 0 (always in the system prompt). The sender's file is loaded in tier 1 (before each agent run). The full conversation history is appended to the file after each turn — no DB, no sliding window.

## Memory writes: two paths

**Conversation history** — `SaveMessageNode` appends the user message and agent reply to `{sender_id}.md` after each turn.

**Facts** — the agent calls the `save_to_memory` tool during its loop when the user asks it to remember something or when it decides a fact is worth keeping.

## Acceptance Criteria

```
[x] Given a returning user
    When LoadContextNode runs
    Then ctx.sender_memory contains the full content of their memory file
```

```
[x] Given the agent produces a reply
    When SaveMessageNode runs
    Then the user message and agent reply are appended to context/memory/{sender_id}.md
    And the file is created with frontmatter if it doesn't exist yet
    And MEMORY.md index is updated for new users
```

```
[x] Given the agent calls save_to_memory with a fact
    Then the fact is appended to the frontmatter section of {sender_id}.md
    — Implemented via .claude/skills/memory-manager/SKILL.md
    — Agent uses built-in Write tool guided by skill instructions
```

## Dependencies

- `specs/features/scaffold/project-scaffold.md` — Implemented
- `specs/features/workflows/workflow-engine.md` — Node and Context
- `specs/features/agents/agent.md` — LoadContextNode plugs into AgentRequestWorkflow

---

**Status History**: Draft (2026-04-16) → In Progress (2026-04-20) → Implemented (2026-04-20)
