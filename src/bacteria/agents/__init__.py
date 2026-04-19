from typing import Protocol

from bacteria.entities.context import Context


class AgentRunner(Protocol):
    async def run(self, ctx: Context) -> str: ...
