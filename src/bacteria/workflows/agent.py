from bacteria.nodes.load_context import LoadContextNode
from bacteria.nodes.run_agent import RunAgentNode
from bacteria.nodes.save_message import SaveMessageNode
from bacteria.workflows import Workflow


def build_agent_workflow(runner) -> Workflow:
    return Workflow(
        nodes=[
            LoadContextNode(),
            RunAgentNode(runner=runner),
            SaveMessageNode(),
        ]
    )
