"""Deliver signed event notifications to organizer-configured HTTPS endpoints."""

import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.lifecycle import EventAuditEntry, EventWebhook


async def dispatch_webhooks(event_id: str, event_type: str, data: dict[str, object]) -> None:
    async with AsyncSessionLocal() as session:
        hooks = (await session.scalars(select(EventWebhook).where(
            EventWebhook.event_id == event_id,
            EventWebhook.enabled.is_(True),
        ))).all()
        matching = [hook for hook in hooks if event_type in hook.event_types]
        for hook in matching:
            payload = json.dumps({
                "id": f"{event_id}:{event_type}:{datetime.now(timezone.utc).timestamp()}",
                "type": event_type,
                "eventId": event_id,
                "occurredAt": datetime.now(timezone.utc).isoformat(),
                "data": data,
            }, separators=(",", ":"), sort_keys=True).encode("utf-8")
            signature = hmac.new(hook.signing_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                    response = await client.post(
                        hook.target_url,
                        content=payload,
                        headers={"Content-Type": "application/json", "X-Sparks-Signature": f"sha256={signature}"},
                    )
                detail = {"type": event_type, "webhookId": hook.id, "statusCode": response.status_code}
                action = "webhook.delivered" if response.is_success else "webhook.failed"
            except httpx.HTTPError as error:
                detail = {"type": event_type, "webhookId": hook.id, "error": type(error).__name__}
                action = "webhook.failed"
            session.add(EventAuditEntry(event_id=event_id, actor_id=None, action=action, target_id=str(hook.id), detail=detail))
        if matching:
            await session.commit()