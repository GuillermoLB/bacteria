import logging

logger = logging.getLogger(__name__)


class WhatsAppClient:
    """Stub — replace with real WhatsApp Cloud API calls."""

    async def send_reply(self, recipient_id: str, text: str) -> None:
        logger.info("WhatsApp stub → %s: %s", recipient_id, text)
