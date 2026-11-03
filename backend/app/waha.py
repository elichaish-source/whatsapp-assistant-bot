"""לקוח קטן ל-WAHA (WhatsApp HTTP API)."""

import logging

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

# נשמר בזיכרון אחרי השליפה הראשונה. לא משתנה כל עוד אותו חשבון מחובר
_own_lid: str | None = None


class WahaError(Exception):
    pass


def own_lid() -> str:
    """ה-LID של החשבון המחובר, בלי הסיומת. מחרוזת ריקה אם לא הצלחנו לקבל אותו.

    וואטסאפ עברה למזהה פרטיות (LID), ומנוע GOWS מזהה חלק מהצ'אטים לפיו ולא
    לפי מספר הטלפון. כישלון לא נשמר במטמון, כדי שננסה שוב בהודעה הבאה.
    """
    global _own_lid
    settings = get_settings()
    if settings.owner_lid:
        return settings.owner_lid.split("@")[0]
    if _own_lid is not None:
        return _own_lid

    headers = {"X-Api-Key": settings.waha_api_key} if settings.waha_api_key else {}
    try:
        resp = httpx.get(
            f"{settings.waha_url}/api/sessions/{settings.waha_session}",
            headers=headers,
            timeout=5,
        )
        resp.raise_for_status()
        me = resp.json().get("me") or {}
    except (httpx.HTTPError, ValueError):
        log.warning("לא הצלחתי לקבל את ה-LID של החשבון מ-WAHA")
        return ""
    _own_lid = str(me.get("lid") or "").split("@")[0]
    return _own_lid


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
