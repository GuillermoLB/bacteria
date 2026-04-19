from typing import Protocol

from bacteria.entities.context import Context


class Node(Protocol):
    async def run(self, ctx: Context) -> Context: ...
