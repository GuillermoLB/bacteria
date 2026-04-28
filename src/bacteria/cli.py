import asyncio

from bacteria.observability import setup_observability
from bacteria.dependencies import get_agent_runner
from bacteria.entities.context import Context
from bacteria.entities.event import Event
from bacteria.workflows.agent import build_agent_workflow

_SENDER_ID = "cli"
_CHANNEL = "cli"


async def _chat_loop() -> None:
    runner = get_agent_runner()
    workflow = build_agent_workflow(runner)

    print("Bacteria — type 'exit' to quit\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Goodbye.")
            break

        ctx = Context(
            event=Event(
                sender_id=_SENDER_ID,
                message_text=user_input,
                channel=_CHANNEL,
            )
        )
        ctx = await workflow.run(ctx)
        print(f"\nBacteria: {ctx.agent_result}\n")


def chat() -> None:
    setup_observability()
    asyncio.run(_chat_loop())


if __name__ == "__main__":
    chat()
