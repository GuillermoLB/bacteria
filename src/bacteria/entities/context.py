from pydantic import BaseModel, ConfigDict

from bacteria.entities.event import Event
from bacteria.entities.job import Job


class Context(BaseModel):
    model_config = ConfigDict(frozen=True) # TODO: not sure should be more mutable
    
    # TODO: don't want this model to be a god object so having a more flexible context model
    # Set by ParsePayloadNode (webhook flows)
    event: Event | None = None
    
    # Set by LoadContextNode
    sender_memory: str | None = None

    # Set by ParsePayloadNode — used by RouteByIntentNode
    intent: str | None = None

    # Set by RunAgentNode
    agent_result: str | None = None

    # Set by SendReplyNode
    delivered: bool = False

    # Set by queue-backed workflows only
    job: Job | None = None
