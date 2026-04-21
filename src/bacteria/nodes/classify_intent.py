from bacteria.entities.context import Context


class ClassifyIntentNode:
    async def run(self, ctx: Context) -> Context:
        text = ctx.event.message_text if ctx.event else ""

        if text.startswith("/"):
            intent = "command"
        elif ctx.event and ctx.event.media_url:
            intent = "media"
        else:
            intent = "agent"

        return ctx.model_copy(update={"intent": intent})
