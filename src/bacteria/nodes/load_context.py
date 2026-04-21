from pathlib import Path

from bacteria.entities.context import Context
from bacteria.entities.event import Event

_MEMORY_DIR = Path("context/memory")


class LoadContextNode:
    async def run(self, ctx: Context) -> Context:
        if ctx.event is None:
            payload = ctx.job.payload if ctx.job else {}
            event = Event(
                sender_id=payload.get("sender_id", "unknown"),
                message_text=payload.get("message_text", ""),
                channel=payload.get("channel", "whatsapp"),
                media_url=payload.get("media_url"),
            )
            ctx = ctx.model_copy(update={"event": event})

        sender_id = ctx.event.sender_id
        memory_file = _MEMORY_DIR / f"{sender_id}.md"
        memory = memory_file.read_text() if memory_file.exists() else None
        return ctx.model_copy(update={"sender_memory": memory})
