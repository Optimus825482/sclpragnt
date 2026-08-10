"""Small, paper-only A2A webhook relay for the Scalper server.

The relay is deliberately transport-only: it never executes a tool or a trade.
It signs outbound JSON and leaves delivery/retry state to the database caller.
"""

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from urllib.request import Request, urlopen


PROTOCOL_VERSION = "1.0"


def make_message(*, sender, recipient, message_type, payload, correlation_id=None,
                 requires_user_approval=False):
    return {
        "protocol": "a2a",
        "version": PROTOCOL_VERSION,
        "message_id": str(uuid.uuid4()),
        "correlation_id": correlation_id,
        "from": sender,
        "to": recipient,
        "type": message_type,
        "created_at": time.time(),
        "requires_user_approval": bool(requires_user_approval),
        "paper_only": True,
        "payload": payload if isinstance(payload, dict) else {"value": payload},
    }


def signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def deliver(message: dict) -> dict:
    """POST one signed event to the configured relay, without blocking the loop."""
    url = os.getenv("A2A_RELAY_URL", "").strip()
    secret = os.getenv("A2A_SHARED_SECRET", "").strip()
    if not url:
        return {"delivered": False, "queued": True, "reason": "A2A_RELAY_URL yapılandırılmamış"}
    if not secret:
        return {"delivered": False, "queued": True, "reason": "A2A_SHARED_SECRET yapılandırılmamış"}
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()

    def send():
        request = Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "User-Agent": "scalper-a2a/1.0",
            "X-A2A-Signature": signature(body, secret),
            "X-A2A-Message-Id": message["message_id"],
        })
        with urlopen(request, timeout=10) as response:
            return int(response.status)

    try:
        status = await asyncio.to_thread(send)
        delivered = 200 <= status < 300
        return {"delivered": delivered, "status_code": status, "queued": not delivered}
    except Exception as exc:
        return {"delivered": False, "queued": True, "error": f"{type(exc).__name__}: {exc}"}
