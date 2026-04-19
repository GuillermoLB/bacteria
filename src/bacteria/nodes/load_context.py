from pathlib import Path

from bacteria.entities.context import Context

_MEMORY_DIR = Path("context/memory")


class LoadContextNode:
    async def run(self, ctx: Context) -> Context:
        sender_id = ctx.event.sender_id
        memory_file = _MEMORY_DIR / f"{sender_id}.md"
        memory = memory_file.read_text() if memory_file.exists() else None
        return ctx.model_copy(update={"sender_memory": memory})
