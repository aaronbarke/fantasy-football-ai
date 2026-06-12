"""Email delivery via Resend's HTTP API. No-ops (with a log line) when
RESEND_API_KEY is unset, so the alert pipeline is safe to run unconfigured."""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


async def send_email(to: str, subject: str, html: str) -> bool:
    settings = get_settings()
    if not settings.resend_api_key:
        logger.info("RESEND_API_KEY not set — skipping email to %s (%s)", to, subject)
        return False
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.email_from,
                "to": [to],
                "subject": subject,
                "html": html,
            },
        )
    if resp.status_code >= 400:
        logger.warning("Email send failed (%d): %s", resp.status_code, resp.text[:200])
        return False
    return True
