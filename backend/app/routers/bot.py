"""נקודת הקליטה של הודעות מוואטסאפ, דרך webhook של WAHA.

הנתיב הזה לא חשוף לאינטרנט: ‏WAHA פונה ל-backend ברשת הפנימית של Docker,
ו-Caddy מחזיר 404 על ‎/api/bot/*‎. מעל זה יש חתימת HMAC, כך שגם אם הנתיב
ייחשף בטעות, בקשה בלי חתימה נדחית.
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, waha
from ..bot import actions
from ..bot.intent import IntentError, extract
from ..config import get_settings
from ..db import SessionLocal
from ..models import BotMessage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bot", tags=["bot"])

ACCEPTED_EVENTS = {"message", "message.any"}
MAX_BODY_CHARS = 1000


def _verify_hmac(raw: bytes, signature: str | None) -> None:
    key = get_settings().waha_webhook_hmac_key
    if not key:
        # הבוט לא מוגדר. עדיף לדחות מלקבל הודעות בלי אימות
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "הבוט לא מוגדר")
    expected = hmac.new(key.encode(), raw, hashlib.sha512).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature.strip().lower()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "חתימה לא תקינה")


def _chat_phone(chat_id: str | None) -> str:
    """‎972501234567@c.us → 972501234567"""
    return auth.normalize_phone((chat_id or "").split("@")[0])


def _is_owner_lid(chat_id: str | None) -> bool:
    """האם מזהה הצ'אט הוא ה-LID של החשבון שלנו."""
    if not chat_id or not chat_id.endswith("@lid"):
        return False
    own = waha.own_lid()
    return bool(own) and chat_id.split("@")[0] == own


def is_owner_self_chat(payload: dict) -> bool:
    """האם זו הודעה שהמשתמש שלח לעצמו, ולא תשובה של הבוט עצמו.

    ‏source == "api" הוא מה שהבוט שלח דרך WAHA. בלי הסינון הזה כל תשובה
    שלו הייתה חוזרת אליו כהודעה חדשה, בלופ אין־סופי.

    שני מבנים אפשריים, תלוי במנוע. ‏WEBJS ממלא גם ``from`` וגם ``to``, ובצ'אט
    עם עצמו שניהם הבעלים. ‏GOWS לא ממלא ``to`` כלל, ושם ``from`` הוא הצ'אט
    עצמו — ולפעמים ב-LID ולא במספר. לכן אם יש ``to`` דורשים ששניהם יהיו
    הבעלים, ואם אין — ``from`` לבדו הוא הצ'אט שצריך להשוות.
    """
    owner = get_settings().owner_phone
    if not owner or not payload.get("fromMe"):
        return False
    if payload.get("source") == "api":
        return False
    chat_id = payload.get("from")
    if payload.get("to"):
        return _chat_phone(chat_id) == owner == _chat_phone(payload.get("to"))
    return _chat_phone(chat_id) == owner or _is_owner_lid(chat_id)


def handle_message(wa_message_id: str, body: str) -> None:
    """מפענח, מבצע, עונה — ורושם ביומן. רץ ברקע, אחרי שהוחזר 200 ל-WAHA."""
    db: Session = SessionLocal()
    try:
        row = db.scalars(
            select(BotMessage).where(BotMessage.wa_message_id == wa_message_id)
        ).one()
        settings = get_settings()
        try:
            result = extract(
                body,
                actions.build_context(db),
                actions.now_local(),
                actions.build_history(db, row.id),
            )
        except IntentError as exc:
            log.warning("פענוח ההודעה נכשל: %s", exc)
            row.error = str(exc)
            row.reply = "לא הצלחתי לפענח את ההודעה. אפשר לנסות שוב בעוד רגע."
            db.commit()
            _reply(settings.owner_phone, row.reply)
            return

        row.intent = result.intent.action
        row.input_tokens = result.input_tokens
        row.output_tokens = result.output_tokens
        row.cached_tokens = result.cached_tokens
        db.commit()

        outcome = actions.execute(db, result.intent)
        row.reply = outcome.reply
        row.task_id = outcome.task_id
        row.listed_task_ids = (
            ",".join(str(item) for item in outcome.listed_task_ids)
            if outcome.listed_task_ids
            else None
        )
        db.commit()
        _reply(settings.owner_phone, outcome.reply)
    except Exception:  # noqa: BLE001 - רץ ברקע, אין למי לזרוק
        log.exception("טיפול בהודעת וואטסאפ נכשל")
    finally:
        db.close()


def _reply(phone: str, text: str) -> None:
    try:
        waha.send_text(phone, text)
    except waha.WahaError:
        log.exception("שליחת תשובה בוואטסאפ נכשלה")


@router.post("/webhook")
async def webhook(
    request: Request,
    background: BackgroundTasks,
    x_webhook_hmac: str | None = Header(default=None),
) -> dict:
    raw = await request.body()
    _verify_hmac(raw, x_webhook_hmac)

    try:
        event = await request.json()
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "גוף הבקשה אינו JSON")

    if event.get("event") not in ACCEPTED_EVENTS:
        return {"ok": True, "skipped": "event"}

    payload = event.get("payload") or {}
    if not is_owner_self_chat(payload):
        return {"ok": True, "skipped": "chat"}

    body = (payload.get("body") or "").strip()
    wa_message_id = payload.get("id")
    if not body or not wa_message_id:
        return {"ok": True, "skipped": "empty"}

    # הרישום הוא גם מנגנון מניעת כפילות: ‏WAHA שולח את ה-webhook שוב כשאינו
    # מקבל 200, ואותה הודעה מגיעה גם ב-message וגם ב-message.any
    db = SessionLocal()
    try:
        db.add(BotMessage(wa_message_id=wa_message_id, body=body[:MAX_BODY_CHARS]))
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"ok": True, "skipped": "duplicate"}
    finally:
        db.close()

    # עונים ל-WAHA מיד, כדי שלא ינסה שוב בזמן שהמודל חושב
    background.add_task(handle_message, wa_message_id, body[:MAX_BODY_CHARS])
    return {"ok": True}
