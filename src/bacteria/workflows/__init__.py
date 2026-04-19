from bacteria.entities.context import Context
from bacteria.nodes import Node


class Workflow:
    def __init__(self, nodes: list[Node]):
        self.nodes = nodes

    async def run(self, ctx: Context) -> Context:
        for node in self.nodes:
            ctx = await node.run(ctx)
        return ctx
