from pydantic import BaseModel, ConfigDict

from bacteria.entities.event import Event


class Context(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_payload: dict = {}

    # Set by ParsePayloadNode (webhook flows)
    event: Event | None = None

    # Set by LoadContextNode
    sender_memory: str | None = None

    # Set by RunAgentNode
    agent_result: str | None = None

    # Set by SendReplyNode
    delivered: bool = False

    # Set by queue-backed workflows only
    job: object | None = None
