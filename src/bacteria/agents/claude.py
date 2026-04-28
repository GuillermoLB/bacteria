from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

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
    def __init__(
        self,
        model: str,
        max_turns: int = 20,
        max_cost: float = 1.0,
        tool_server: Any | None = None,
        allowed_tools: list[str] | None = None,
    ):
        self.model = model
        self.max_turns = max_turns
        self.max_cost = max_cost
        self.tool_server = tool_server
        self.allowed_tools = allowed_tools or []

    async def run(self, ctx: Context) -> tuple[str, str | None]:
        soul = _read_soul()
        memory = ctx.sender_memory or ""
        system_prompt = "\n\n".join(part for part in [soul, memory] if part)

        mcp_servers = {"bacteria": self.tool_server} if self.tool_server else {}

        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=system_prompt,
            max_turns=self.max_turns,
            max_budget_usd=self.max_cost,
            setting_sources=["user", "project"],
            mcp_servers=mcp_servers,
            allowed_tools=self.allowed_tools,
            **{"resume": ctx.session_id} if ctx.session_id else {},
        )

        result = ""
        result_session_id: str | None = ctx.session_id
        async for message in query(
            prompt=ctx.event.message_text,
            options=options,
        ):
            if isinstance(message, AssistantMessage):
                text = _extract_text(message)
                if text:
                    result = text
            if isinstance(message, ResultMessage):
                result_session_id = message.session_id

        return result, result_session_id
