from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from bacteria.entities.context import Context

_SOUL_PATH = Path("context/identity/soul.md")


def _read_soul() -> str:
    if _SOUL_PATH.exists():
        return _SOUL_PATH.read_text()
    return ""


def _extract_text(message: AssistantMessage) -> str:
    return "\n".join(
        block.text for block in message.content if isinstance(block, TextBlock)
    )


class ClaudeAgentRunner:
    def __init__(self, model: str, max_turns: int = 20, max_cost: float = 1.0):
        self.model = model
        self.max_turns = max_turns
        self.max_cost = max_cost

    async def run(self, ctx: Context) -> str:
        soul = _read_soul()
        memory = ctx.sender_memory or ""
        system_prompt = "\n\n".join(part for part in [soul, memory] if part)

        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=system_prompt,
            max_turns=self.max_turns,
            max_budget_usd=self.max_cost,
            setting_sources=["user", "project"],
        )

        result = ""
        async for message in query(
            prompt=ctx.event.message_text,
            options=options,
        ):
            if isinstance(message, AssistantMessage):
                text = _extract_text(message)
                if text:
                    result = text

        return result
