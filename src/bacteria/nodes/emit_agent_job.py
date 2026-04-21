from bacteria.entities.context import Context
from bacteria.queue import JobQueue


class EmitAgentJobNode:
    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue

    async def run(self, ctx: Context) -> Context:
        if ctx.intent != "agent":
            return ctx

        await self._queue.enqueue(
            payload={
                "event_type": "whatsapp.agent_request",
                "sender_id": ctx.event.sender_id,
                "message_text": ctx.event.message_text,
                "channel": ctx.event.channel,
            },
            queue="agents",
        )

        return ctx
