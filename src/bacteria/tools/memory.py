from pathlib import Path

from claude_agent_sdk import ToolAnnotations, tool

_MEMORY_DIR = Path("context/memory")


@tool(
    "read_memory",
    "Read the current memory file for a sender. Use this to check what facts are stored or to verify after a write.",
    {
        "type": "object",
        "properties": {
            "sender_id": {"type": "string", "description": "The sender's unique identifier"},
        },
        "required": ["sender_id"],
    },
    annotations=ToolAnnotations(readOnlyHint=True),
)
async def read_memory(args: dict) -> dict:
    memory_file = _MEMORY_DIR / f"{args['sender_id']}.md"
    if not memory_file.exists():
        return {"content": [{"type": "text", "text": ""}]}
    return {"content": [{"type": "text", "text": memory_file.read_text()}]}


@tool(
    "write_memory",
    "Append a durable fact to the sender's memory file. Use this when the user tells you something they want you to remember long-term.",
    {
        "type": "object",
        "properties": {
            "sender_id": {"type": "string", "description": "The sender's unique identifier"},
            "fact": {"type": "string", "description": "The fact to remember, written as a concise statement"},
        },
        "required": ["sender_id", "fact"],
    },
    annotations=ToolAnnotations(readOnlyHint=False),
)
async def write_memory(args: dict) -> dict:
    sender_id = args["sender_id"]
    fact = args["fact"]

    memory_file = _MEMORY_DIR / f"{sender_id}.md"
    if not memory_file.exists():
        return {
            "content": [{"type": "text", "text": f"Error: memory file for {sender_id} does not exist"}],
            "is_error": True,
        }

    with memory_file.open("a") as f:
        f.write(f"\n- {fact}")

    return {"content": [{"type": "text", "text": "fact saved"}]}
