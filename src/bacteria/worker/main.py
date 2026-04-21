import asyncio
import logging

from bacteria.dependencies import get_worker
from bacteria.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    logger.info("Starting worker (concurrency=%d, poll_interval=%ds)",
                settings.worker.concurrency, settings.worker.poll_interval)
    asyncio.run(get_worker().run())
