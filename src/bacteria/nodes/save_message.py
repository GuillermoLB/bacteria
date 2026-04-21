from datetime import datetime, timezone
from pathlib import Path

from bacteria.entities.context import Context

_MEMORY_DIR = Path("context/memory")
_MEMORY_INDEX = _MEMORY_DIR / "MEMORY.md"


class SaveMessageNode:
    async def run(self, ctx: Context) -> Context:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        sender_id = ctx.event.sender_id
        memory_file = _MEMORY_DIR / f"{sender_id}.md"
        is_new = not memory_file.exists()

        if is_new:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            memory_file.write_text(
                f"---\nname: {sender_id}\ntype: user\nlast_updated: {today}\n---\n\n"
                f"## History\n"
            )
            _update_memory_index(sender_id)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = (
            f"\n### {timestamp}\n"
            f"**User**: {ctx.event.message_text}\n"
            f"**Assistant**: {ctx.agent_result or ''}\n"
        )

        with memory_file.open("a") as f:
            f.write(entry)

        return ctx


def _update_memory_index(sender_id: str) -> None:
    line = f"- [{sender_id}]({sender_id}.md) — user memory\n"
    with _MEMORY_INDEX.open("a") as f:
        f.write(line)
