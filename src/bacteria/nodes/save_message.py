import re
from datetime import datetime, timezone
from pathlib import Path

from bacteria.entities.context import Context

_MEMORY_DIR = Path("context/memory")
_MEMORY_INDEX = _MEMORY_DIR / "MEMORY.md"

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_SESSION_LINE_RE = re.compile(r"^session_id:.*$", re.MULTILINE)


def _upsert_session_id(content: str, session_id: str) -> str:
    """Insert or update session_id in the YAML frontmatter block."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return content

    frontmatter = match.group(1)
    if _SESSION_LINE_RE.search(frontmatter):
        updated_frontmatter = _SESSION_LINE_RE.sub(f"session_id: {session_id}", frontmatter)
    else:
        updated_frontmatter = frontmatter + f"\nsession_id: {session_id}"

    return content[: match.start(1)] + updated_frontmatter + content[match.end(1) :]


class SaveMessageNode:
    async def run(self, ctx: Context) -> Context:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        sender_id = ctx.event.sender_id
        memory_file = _MEMORY_DIR / f"{sender_id}.md"
        is_new = not memory_file.exists()

        if is_new:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            session_line = f"\nsession_id: {ctx.session_id}" if ctx.session_id else ""
            memory_file.write_text(
                f"---\nname: {sender_id}\ntype: user\nlast_updated: {today}{session_line}\n---\n\n"
                f"## History\n"
            )
            _update_memory_index(sender_id)
        elif ctx.session_id:
            content = memory_file.read_text()
            updated = _upsert_session_id(content, ctx.session_id)
            if updated != content:
                memory_file.write_text(updated)

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
