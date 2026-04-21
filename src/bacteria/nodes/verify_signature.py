import hashlib
import hmac

from bacteria.entities.context import Context
from bacteria.worker.exceptions import PermanentFailure


class VerifySignatureNode:
    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    async def run(self, ctx: Context) -> Context:
        payload = ctx.job.payload if ctx.job else {}
        signature = payload.get("signature", "")
        body = payload.get("raw_body", "")

        expected = "sha256=" + hmac.new(
            self._secret,
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            raise PermanentFailure("Invalid webhook signature")

        return ctx
