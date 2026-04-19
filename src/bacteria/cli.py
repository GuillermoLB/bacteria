import asyncio

from bacteria.dependencies import get_agent_runner
from bacteria.entities.context import Context
from bacteria.entities.event import Event
from bacteria.workflows.agent import build_agent_workflow

_CLI_SENDER = "cli_user"
_CLI_CHANNEL = "cli"


async def _chat_loop() -> None:
    runner = get_agent_runner()
    workflow = build_agent_workflow(runner)

    print("Bacteria CLI — type 'exit' to quit\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("Goodbye.")
            break

        event = Event(
            sender_id=_CLI_SENDER,
            message_text=user_input,
            channel=_CLI_CHANNEL,
        )
        ctx = Context(event=event)
        ctx = await workflow.run(ctx)

        print(f"Assistant: {ctx.agent_result}\n")


def main() -> None:
    asyncio.run(_chat_loop())


if __name__ == "__main__":
    main()
