from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from bacteria.entities.context import Context
from bacteria.observability.agent_tracer import AgentTracer

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
        tracer: AgentTracer | None = None,
    ):
        self.model = model
        self.max_turns = max_turns
        self.max_cost = max_cost
        self.tool_server = tool_server
        self.allowed_tools = allowed_tools or []
        self.tracer = tracer

    async def run(self, ctx: Context) -> tuple[str, str | None]:
        sender_id = ctx.event.sender_id if ctx.event else "unknown"
        job_id = str(ctx.job.id) if ctx.job else "cli"
        prompt_text = ctx.event.message_text if ctx.event else ""

        span = None
        if self.tracer:
            try:
                span = self.tracer.start(
                    name="agent_run",
                    input=prompt_text,
                    metadata={"job_id": job_id, "model": self.model, "sender_id": sender_id},
                )
            except Exception:
                span = None

        subprocess_env = {}
        if self.tracer:
            try:
                subprocess_env = self.tracer.get_subprocess_env()
            except Exception:
                subprocess_env = {}

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
            env=subprocess_env,
            **{"resume": ctx.session_id} if ctx.session_id else {},
        )

        result = ""
        result_session_id: str | None = ctx.session_id
        result_message: ResultMessage | None = None

        try:
            async for message in query(prompt=prompt_text, options=options):
                if isinstance(message, AssistantMessage):
                    text = _extract_text(message)
                    if text:
                        result = text
                if isinstance(message, ResultMessage):
                    result_session_id = message.session_id
                    result_message = message
        finally:
            if span is not None:
                usage = result_message.usage or {} if result_message else {}
                metadata = {
                    "total_cost_usd": result_message.total_cost_usd if result_message else None,
                    "num_turns": result_message.num_turns if result_message else None,
                    "stop_reason": result_message.stop_reason if result_message else None,
                    "claude_session_id": result_message.session_id if result_message else None,
                }
                try:
                    span.finish(output=result, usage=usage, metadata=metadata)
                except Exception:
                    pass

        return result, result_session_id
