from bacteria.entities.context import Context
from bacteria.entities.event import Event


class ParseWhatsAppPayloadNode:
    """Stub parser — extracts sender_id and message_text from a simplified payload."""

    async def run(self, ctx: Context) -> Context:
        payload = ctx.job.payload if ctx.job else {}

        event = Event(
            sender_id=payload.get("sender_id", "unknown"),
            message_text=payload.get("message_text", ""),
            channel="whatsapp",
            media_url=payload.get("media_url"),
        )

        return ctx.model_copy(update={"event": event})
