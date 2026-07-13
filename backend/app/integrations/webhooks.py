"""Incoming and outgoing webhook management.

Incoming: signature verification (HMAC-SHA256) and routing to connector webhook handlers.
Outgoing: delivering platform events to external target URLs with retry policy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.integrations.errors import WebhookDeliveryFailed, WebhookSignatureInvalid
from app.integrations.event_bus import event_bus
from app.integrations.models import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verifies HMAC-SHA256 signature over incoming payload."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected, signature)


class WebhookManager:
    def __init__(self, db: Session):
        self.db = db

    def create_endpoint(
        self,
        workspace_id: str,
        owner_id: str,
        name: str,
        direction: str,
        url: str = "",
        event_filter: Optional[List[str]] = None,
        retry_policy: Optional[Dict[str, Any]] = None,
    ) -> WebhookEndpoint:
        # For incoming webhooks, generate a unique random URL suffix
        import uuid
        if direction == "incoming" and not url:
            url = f"/api/v1/integrations/incoming/{uuid.uuid4().hex[:16]}"

        secret = uuid.uuid4().hex  # HMAC token generator

        endpoint = WebhookEndpoint(
            workspace_id=workspace_id,
            owner_id=owner_id,
            name=name,
            direction=direction,
            url=url,
            secret=secret,
            event_filter=event_filter or ["*"],
            retry_policy=retry_policy or {"max_retries": 3, "backoff_factor": 2.0},
        )
        self.db.add(endpoint)
        self.db.commit()
        self.db.refresh(endpoint)
        return endpoint

    def deliver_outgoing(self, endpoint_id: str, event_id: str, payload: Dict[str, Any]) -> WebhookDelivery:
        """Sends an outgoing webhook event synchronously or registers for retry."""
        endpoint = self.db.query(WebhookEndpoint).filter(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.is_active.is_(True),
        ).first()
        if not endpoint:
            raise WebhookDeliveryFailed(detail="Endpoint not found or inactive")

        delivery = WebhookDelivery(
            webhook_id=endpoint_id,
            event_id=event_id,
            request_payload=payload,
            status="pending",
            attempt=1,
        )
        self.db.add(delivery)
        self.db.commit()

        max_retries = endpoint.retry_policy.get("max_retries", 3)
        backoff = endpoint.retry_policy.get("backoff_factor", 2.0)

        for attempt in range(1, max_retries + 2):
            delivery.attempt = attempt
            try:
                # Sign payload using HMAC-SHA256
                payload_bytes = json.dumps(payload).encode("utf-8")
                sig = hmac.new(endpoint.secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

                headers = {
                    "Content-Type": "application/json",
                    "X-LexiMind-Signature": sig,
                    "X-LexiMind-Event-Id": event_id,
                }

                # Trigger HTTP POST request
                with httpx.Client(timeout=10.0) as client:
                    response = client.post(endpoint.url, content=payload_bytes, headers=headers)

                delivery.response_status = response.status_code
                delivery.response_body = response.text[:2000]

                if 200 <= response.status_code < 300:
                    delivery.status = "success"
                    delivery.delivered_at = _now()
                    break
                else:
                    delivery.error = f"HTTP status {response.status_code}"
                    delivery.status = "failed"
            except Exception as e:
                delivery.error = str(e)
                delivery.status = "failed"

            if attempt <= max_retries:
                # Exponential sleep backoff
                import time
                time.sleep(backoff ** attempt)
            else:
                delivery.status = "dead_letter"

        self.db.commit()
        return delivery
