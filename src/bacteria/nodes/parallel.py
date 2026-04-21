import asyncio

from bacteria.entities.context import Context
from bacteria.nodes import Node


class ParallelNode:
    def __init__(self, nodes: list[Node]) -> None:
        self.nodes = nodes

    async def run(self, ctx: Context) -> Context:
        results = await asyncio.gather(*[node.run(ctx) for node in self.nodes])
        merged = {}
        for result_ctx in results:
            merged.update(result_ctx.model_dump(exclude_unset=True))
        return ctx.model_copy(update=merged)
