from typing import Protocol


class ChannelClient(Protocol):
    async def send_reply(self, recipient_id: str, text: str) -> None: ...
