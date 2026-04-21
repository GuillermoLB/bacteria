"""
Composition root for bacteria.

Wires together all concrete implementations and injects them into
components that depend on abstractions (Protocols/ABCs).
"""

from functools import lru_cache

from bacteria.agents.claude import ClaudeAgentRunner
from bacteria.channels.whatsapp import WhatsAppClient
from bacteria.db import get_engine
from bacteria.queue.postgres import PostgresJobQueue
from bacteria.settings import get_settings
from bacteria.worker import Worker
from bacteria.worker.registry import WorkflowRegistry
from bacteria.workflows.whatsapp import (
    build_whatsapp_agent_workflow,
    build_whatsapp_webhook_workflow,
)


def get_agent_runner() -> ClaudeAgentRunner:
    settings = get_settings()
    return ClaudeAgentRunner(
        model=settings.agent.model,
        max_turns=settings.agent.max_turns,
        max_cost=settings.agent.max_cost,
    )


@lru_cache(maxsize=1)
def get_job_queue() -> PostgresJobQueue:
    return PostgresJobQueue(engine=get_engine())


@lru_cache(maxsize=1)
def get_registry() -> WorkflowRegistry:
    settings = get_settings()
    queue = get_job_queue()
    runner = get_agent_runner()
    channel_client = WhatsAppClient()

    registry = WorkflowRegistry()
    registry.register(
        "whatsapp.webhook",
        build_whatsapp_webhook_workflow(
            secret=settings.whatsapp.webhook_secret,
            queue=queue,
        ),
    )
    registry.register(
        "whatsapp.agent_request",
        build_whatsapp_agent_workflow(
            runner=runner,
            channel_client=channel_client,
        ),
    )
    return registry


def get_worker() -> Worker:
    settings = get_settings()
    return Worker(
        queue=get_job_queue(),
        registry=get_registry(),
        concurrency=settings.worker.concurrency,
    )
