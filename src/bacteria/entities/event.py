from pydantic import BaseModel


class Event(BaseModel):
    sender_id: str
    message_text: str
    channel: str
    media_url: str | None = None
