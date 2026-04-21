import asyncio

from loguru import logger

from bacteria.dependencies import get_worker
from bacteria.observability import setup_observability
from bacteria.settings import get_settings


def main() -> None:
    setup_observability()
    settings = get_settings()
    logger.info(
        "Starting worker",
        concurrency=settings.worker.concurrency,
        poll_interval=settings.worker.poll_interval,
    )
    asyncio.run(get_worker().run())
