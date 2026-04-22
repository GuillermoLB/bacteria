from loguru import logger


class WhatsAppClient:
    """Stub — replace with real WhatsApp Cloud API calls."""

    async def send_reply(self, recipient_id: str, text: str) -> None:
        logger.info("WhatsApp stub → {}: {}", recipient_id, text)
