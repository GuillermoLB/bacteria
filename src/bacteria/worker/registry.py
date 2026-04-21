from bacteria.workflows import Workflow


class UnregisteredEventType(Exception):
    pass


class WorkflowRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, Workflow] = {}

    def register(self, event_type: str, workflow: Workflow) -> None:
        self._registry[event_type] = workflow

    def get(self, event_type: str) -> Workflow:
        workflow = self._registry.get(event_type)
        if workflow is None:
            raise UnregisteredEventType(f"No workflow registered for event type: {event_type!r}")
        return workflow
