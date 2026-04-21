from bacteria.channels import ChannelClient
from bacteria.entities.context import Context


class SendReplyNode:
    def __init__(self, client: ChannelClient) -> None:
        self._client = client

    async def run(self, ctx: Context) -> Context:
        await self._client.send_reply(
            recipient_id=ctx.event.sender_id,
            text=ctx.agent_result or "",
        )
        return ctx.model_copy(update={"delivered": True})
