# Feature: CLI Agent

**Status**: Draft
**Owner**: GuillermoLB
**Last Updated**: 2026-04-17
**Priority**: High

## Purpose

Validate the core agent loop before building any infrastructure. A CLI entrypoint lets you converse with the agent directly from the terminal — no webhooks, no queue, no worker. Just type a message, get a reply, repeat.

## How it works

```
$ uv run bacteria chat

You: hey, what can you help me with?
Bacteria: I can help you with...

You: remember that I prefer concise answers
Bacteria: Got it, I'll keep things concise.

You: exit
```

Each turn runs the agent workflow directly — no job queue involved:

```
CLI input (sender_id = "cli")
  → LoadContextNode    reads context/memory/cli.md
  → RunAgentNode       calls ClaudeAgentRunner
  → SaveMessageNode    appends turn to context/memory/cli.md
  → print reply
```

Session continues until the user types `exit` or sends an interrupt (`Ctrl+C`).

## Entrypoint

Added to `pyproject.toml` scripts:

```toml
[project.scripts]
bacteria = "bacteria:main"
bacteria-chat = "bacteria.cli:chat"
```

`bacteria-chat` starts the interactive loop. `bacteria` remains the existing entrypoint.

## Implementation shape

```python
# src/bacteria/cli.py

import asyncio
from bacteria.workflows import Workflow
from bacteria.nodes.load_context import LoadContextNode
from bacteria.nodes.run_agent import RunAgentNode
from bacteria.nodes.save_message import SaveMessageNode
from bacteria.agents.claude import ClaudeAgentRunner
from bacteria.entities.context import Context
from bacteria.entities.event import Event
from bacteria.settings import get_settings

SENDER_ID = "cli"

def build_workflow() -> Workflow:
    settings = get_settings()
    runner = ClaudeAgentRunner(
        model=settings.agent.model,
        max_turns=settings.agent.max_turns,
        max_cost=settings.agent.max_cost,
    )
    return Workflow(nodes=[
        LoadContextNode(),
        RunAgentNode(runner=runner),
        SaveMessageNode(),
    ])

async def run_chat() -> None:
    workflow = build_workflow()
    print("Bacteria — type 'exit' to quit\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if user_input.lower() in ("exit", "quit"):
            break

        if not user_input:
            continue

        ctx = Context(
            event=Event(
                sender_id=SENDER_ID,
                message_text=user_input,
                channel="cli",
            )
        )
        ctx = await workflow.run(ctx)
        print(f"\nBacteria: {ctx.agent_result}\n")

def chat() -> None:
    asyncio.run(run_chat())
```

## Settings

Add `AgentSettings` to `settings.py`:

```python
class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT__", env_file=".env", extra="ignore")
    model: str = "claude-sonnet-4-6"
    max_turns: int = 20
    max_cost: float = 1.0
```

Add to `.env.example`:
```
AGENT__MODEL=claude-sonnet-4-6
AGENT__MAX_TURNS=20
AGENT__MAX_COST=1.0
```

## Acceptance Criteria

```
Given the CLI is started with `uv run bacteria-chat`
When the user types a message
Then the agent replies in the terminal
And the turn is appended to context/memory/cli.md
```

```
Given a returning CLI session
When the CLI starts
Then the agent has memory of previous conversations
```

```
Given the user types "exit"
When the loop receives it
Then the CLI exits cleanly
```

```
Given the user types "remember that I prefer concise answers"
When the agent processes it
Then it calls save_to_memory and the fact appears in context/memory/cli.md
```

## Dependencies

- `specs/features/scaffold/project-scaffold.md` — Implemented
- `specs/features/workflows/workflow-engine.md` — Node, Context, Workflow
- `specs/features/memory/memory.md` — LoadContextNode, SaveMessageNode
- `specs/features/agents/agent.md` — AgentRunner, ClaudeAgentRunner, RunAgentNode

---

**Status History**: Draft (2026-04-17)
