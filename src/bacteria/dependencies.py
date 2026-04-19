"""
Composition root for bacteria.

Wires together all concrete implementations and injects them into
components that depend on abstractions (Protocols/ABCs).
"""

from bacteria.agents.claude import ClaudeAgentRunner
from bacteria.settings import get_settings


def get_agent_runner() -> ClaudeAgentRunner:
    settings = get_settings()
    return ClaudeAgentRunner(
        model=settings.agent.model,
        max_turns=settings.agent.max_turns,
        max_cost=settings.agent.max_budget_usd,
    )
