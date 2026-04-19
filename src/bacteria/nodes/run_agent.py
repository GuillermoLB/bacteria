from bacteria.agents import AgentRunner
from bacteria.entities.context import Context


class RunAgentNode:
    def __init__(self, runner: AgentRunner):
        self.runner = runner

    async def run(self, ctx: Context) -> Context:
        result = await self.runner.run(ctx)
        return ctx.model_copy(update={"agent_result": result})
