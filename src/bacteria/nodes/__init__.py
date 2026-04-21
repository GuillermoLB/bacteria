import time
from typing import Protocol

from loguru import logger

from bacteria.entities.context import Context


class Node(Protocol):
    async def run(self, ctx: Context) -> Context: ...


class InstrumentedNode:
    """Wraps any Node to add debug logging and timing."""

    def __init__(self, node: Node) -> None:
        self._node = node
        self._name = type(node).__name__

    async def run(self, ctx: Context) -> Context:
        logger.debug("Node started", node=self._name)
        start = time.monotonic()
        try:
            result = await self._node.run(ctx)
            logger.debug("Node completed", node=self._name, duration_ms=round((time.monotonic() - start) * 1000))
            return result
        except Exception as e:
            logger.error("Node failed", node=self._name, error=str(e))
            raise
