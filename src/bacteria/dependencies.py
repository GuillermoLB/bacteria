"""
Composition root for bacteria.

This module wires together all concrete implementations and injects them into
the components that depend on abstractions (Protocols/ABCs). Nothing should
import concrete implementations directly — they get them from here.

Populated incrementally as features are built:
  - queue/worker spec  → PostgresJobQueue, Worker, WorkflowRegistry
  - agent spec         → AgentRunner implementations
  - api spec           → FastAPI app and routers
"""
