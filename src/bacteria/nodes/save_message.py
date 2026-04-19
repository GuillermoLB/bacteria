from datetime import datetime, timezone
from pathlib import Path

from bacteria.entities.context import Context

_MEMORY_DIR = Path("context/memory")


class SaveMessageNode:
    async def run(self, ctx: Context) -> Context:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        sender_id = ctx.event.sender_id
        memory_file = _MEMORY_DIR / f"{sender_id}.md"

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = (
            f"\n## {timestamp}\n"
            f"**User**: {ctx.event.message_text}\n"
            f"**Assistant**: {ctx.agent_result or ''}\n"
        )

        with memory_file.open("a") as f:
            f.write(entry)

        return ctx
