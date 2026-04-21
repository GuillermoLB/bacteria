---
name: memory-manager
description: Save facts, preferences, and important information about the user to long-term memory.
---

## When to use this skill

Use this skill when:
- The user explicitly asks you to remember something ("remember that...", "keep in mind...")
- You learn a durable fact worth keeping (name, timezone, preferences, ongoing projects)
- The user corrects a previous assumption — update memory to reflect the truth

## How to save a fact

Append to the frontmatter section of `context/memory/{sender_id}.md`, above the `## History` heading.

Example — adding a preference:
```
Prefers concise answers. Working on Bacteria. Timezone: Europe/Madrid.
```

Do not duplicate facts already present. Update in place if correcting existing information.

## What NOT to save

- Transient requests ("remind me tomorrow") — these are tasks, not memory
- Raw conversation turns — `SaveMessageNode` handles history automatically
- Sensitive credentials or secrets
