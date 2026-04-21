from bacteria.entities.context import Context
from bacteria.workflows import Workflow


class RouteByIntentNode:
    def __init__(self, routes: dict[str, Workflow]) -> None:
        self.routes = routes

    async def run(self, ctx: Context) -> Context:
        if ctx.intent is None:
            raise ValueError("RouteByIntentNode requires ctx.intent to be set")
        workflow = self.routes.get(ctx.intent)
        if workflow is None:
            raise ValueError(f"No route registered for intent: {ctx.intent!r}")
        return await workflow.run(ctx)
