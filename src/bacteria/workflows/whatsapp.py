from bacteria.channels.whatsapp import WhatsAppClient
from bacteria.nodes.classify_intent import ClassifyIntentNode
from bacteria.nodes.emit_agent_job import EmitAgentJobNode
from bacteria.nodes.load_context import LoadContextNode
from bacteria.nodes.parse_whatsapp_payload import ParseWhatsAppPayloadNode
from bacteria.nodes.run_agent import RunAgentNode
from bacteria.nodes.save_message import SaveMessageNode
from bacteria.nodes.send_reply import SendReplyNode
from bacteria.nodes.verify_signature import VerifySignatureNode
from bacteria.queue import JobQueue
from bacteria.workflows import Workflow


def build_whatsapp_webhook_workflow(secret: str, queue: JobQueue) -> Workflow:
    return Workflow(nodes=[
        VerifySignatureNode(secret=secret),
        ParseWhatsAppPayloadNode(),
        ClassifyIntentNode(),
        EmitAgentJobNode(queue=queue),
    ])


def build_whatsapp_agent_workflow(runner, channel_client: WhatsAppClient) -> Workflow:
    return Workflow(nodes=[
        LoadContextNode(),
        RunAgentNode(runner=runner),
        SaveMessageNode(),
        SendReplyNode(client=channel_client),
    ])
