"""לקוח קטן ל-WAHA (WhatsApp HTTP API)."""

import httpx

from .config import get_settings


class WahaError(Exception):
    pass


def phone_to_chat_id(phone: str) -> str:
    return f"{phone}@c.us"


def send_text(phone: str, text: str) -> None:
    settings = get_settings()
    headers = {"X-Api-Key": settings.waha_api_key} if settings.waha_api_key else {}
    try:
        resp = httpx.post(
            f"{settings.waha_url}/api/sendText",
            json={"session": settings.waha_session, "chatId": phone_to_chat_id(phone), "text": text},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise WahaError(str(exc)) from exc
