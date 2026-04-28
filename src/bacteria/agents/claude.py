from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from bacteria.entities.context import Context
from bacteria.observability.tracing import get_tracer

_SOUL_PATH = Path("context/identity/soul.md")


def _read_soul() -> str:
    if _SOUL_PATH.exists():
        return _SOUL_PATH.read_text()
    return ""


def _extract_text(message: AssistantMessage) -> str:
    return "\n".join(
        block.text for block in message.content if isinstance(block, TextBlock)
    )


def _build_subprocess_env() -> dict[str, str]:
    from bacteria.settings import get_settings
    obs = get_settings().observability
    if not obs.otel_endpoint:
        return {}
    return {"OTEL_EXPORTER_OTLP_ENDPOINT": obs.otel_endpoint}


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
        tracer = get_tracer()
        with tracer.start_as_current_span("agent_run") as span:
            span.set_attribute("sender_id", ctx.event.sender_id if ctx.event else "unknown")
            span.set_attribute("model", self.model)
            span.set_attribute("job_id", str(ctx.job.id) if ctx.job else "cli")
            if ctx.session_id:
                span.set_attribute("session_id", ctx.session_id)

            soul = _read_soul()
            memory = ctx.sender_memory or ""
            system_prompt = "\n\n".join(part for part in [soul, memory] if part)

            mcp_servers = {"bacteria": self.tool_server} if self.tool_server else {}
            subprocess_env = _build_subprocess_env()

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

            async for message in query(prompt=ctx.event.message_text, options=options):
                if isinstance(message, AssistantMessage):
                    text = _extract_text(message)
                    if text:
                        result = text
                if isinstance(message, ResultMessage):
                    result_session_id = message.session_id
                    result_message = message

            if result_message is not None:
                usage = result_message.usage or {}
                span.add_event("agent_result", attributes={
                    "total_cost_usd": str(result_message.total_cost_usd),
                    "num_turns": result_message.num_turns,
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "stop_reason": result_message.stop_reason or "",
                })

            return result, result_session_id
