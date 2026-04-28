import re
from pathlib import Path

from bacteria.entities.context import Context
from bacteria.entities.event import Event

_MEMORY_DIR = Path("context/memory")
_SESSION_RE = re.compile(r"^session_id:\s*(\S+)", re.MULTILINE)


def _extract_session_id(content: str) -> str | None:
    match = _SESSION_RE.search(content)
    return match.group(1) if match else None


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

        if memory_file.exists():
            content = memory_file.read_text()
            session_id = _extract_session_id(content)
            return ctx.model_copy(update={"sender_memory": content, "session_id": session_id})

        return ctx.model_copy(update={"sender_memory": None, "session_id": None})
