"""מסך המיילים בדשבורד — קריאה בלבד (שלב 4-3).

**למה מסך ולא בוט.** הוכרע 23.11.2026, מתוך השימוש האמיתי ב-4-2: רשימה
של 25 מיילים בוואטסאפ נגללת, וארכוב מייל אחד היה הודעה שלישית בשרשור.
הטריאז' עבר לכאן, והבוט נשאר להתראות, סיכומי מספרים ושאלות.

**השלב הזה הוא קריאה בלבד, בכוונה.** אין ארכוב, אין מענה ואין "הפוך
למשימה" — הם 4-4 ו-4-5. המשתמש ביקש לראות את המסך מול התיבה האמיתית
ולדייק אותו לפני שמוסיפים פעולות.

⚠️ **שום תוכן מייל אינו נשמר.** אין כאן טבלה, אין מיגרציה ואין כתיבה
למסד: המייל נקרא מגוגל ברגע הבקשה, מוצג, ונזרק. זאת ההבטחה
ב-``frontend/public/privacy.html``, ויש עליה בדיקה.

⚠️ **הנתיבים אינם מכירים את Gmail.** כל הקריאות לגוגל, הסיווג וניקוי
הציטוטים יושבים ב-``app/gmail.py``, בדיוק כמו אצל הבוט — זאת הסיבה
שהשכבה נבנתה בלי לדעת שיש בוט.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import gauth, gmail
from ..auth import require_user
from ..db import get_db
from ..models import Client
from ..schemas import (
    EmailBodyOut,
    EmailIdsIn,
    EmailIdsOut,
    EmailItemOut,
    EmailListOut,
    TaskDraftOut,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/emails", tags=["emails"], dependencies=[Depends(require_user)])

# מה שאומרים למשתמש כשאין חיבור. ⚠️ הכפתור עצמו יושב במסך ההגדרות ולא
# כאן: החיבור הוא הגדרה של המערכת, והמסך הזה הוא מקום העבודה
NOT_CONFIGURED = "חיבור גוגל לא מוגדר בשרת. חסרים מפתחות ב-.env"
NOT_CONNECTED = "חשבון הגוגל לא מחובר. אפשר לחבר אותו במסך ההגדרות."
DISCONNECTED = "החיבור לגוגל נפסל וצריך לחבר מחדש, במסך ההגדרות."
UNAVAILABLE = "לא הצלחתי להגיע לתיבת הדואר כרגע. אפשר לנסות שוב בעוד רגע."


def _require_connection(db: Session) -> None:
    """עוצר לפני הפנייה לגוגל, כדי להחזיר משפט מובן ולא שגיאת רשת.

    ‏503 ולא 502: "צריך לחבר בהגדרות" הוא מצב שהמשתמש יכול לתקן, ואילו
    ‏502 אומר "נסה שוב" — והמסך מבדיל בין השניים בטקסט שהוא מציג.
    """
    if not gauth.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED)
    cred = gauth.get_credential(db)
    if cred is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONNECTED)
    if cred.status != "connected":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DISCONNECTED)


@router.get("", response_model=EmailListOut)
def list_emails(
    db: Session = Depends(get_db),
    scope: str = Query("week", pattern="^(today|week|month)$"),
) -> EmailListOut:
    """הדואר הנכנס בטווח הזמן, מסווג לחשוב ולא חשוב.

    ⚠️ **שתי הקבוצות חוזרות באותה תשובה**, והלשוניות במסך מסננות אותה
    בצד הלקוח. הסיווג הוא מה שמסדר את המסך ולא מה שמסתיר ממנו, ומעבר
    בין לשוניות לא אמור לפנות לגוגל מחדש.
    """
    _require_connection(db)
    try:
        found = gmail.list_screen(db, scope)
        triaged = gmail.triage(found, gmail.client_addresses(db))
    except gauth.GoogleDisconnected as exc:
        log.warning("החיבור לגוגל נפסל באמצע בקשה למסך: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DISCONNECTED) from exc
    except (gmail.GmailError, gauth.GoogleError) as exc:
        log.warning("שליפת הרשימה למסך נכשלה: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, UNAVAILABLE) from exc

    items = [
        EmailItemOut(
            id=item.email.id,
            thread_id=item.email.thread_id,
            sender=item.email.sender(),
            sender_email=item.email.sender_email,
            subject=item.email.subject,
            line=item.line,
            received_at=item.email.received_at,
            important=item.relevant,
            is_client=item.forced,
            unread=item.email.unread,
            has_attachments=item.email.has_attachments,
            thread_count=item.email.thread_count,
            thread_ids=item.email.thread_ids or [item.email.id],
        )
        for item in triaged
    ]
    important = sum(1 for item in items if item.important)
    return EmailListOut(
        scope=scope,
        items=items,
        important=important,
        other=len(items) - important,
        # נגענו בתקרה, ולכן ייתכן שיש עוד מיילים בטווח שלא נשלפו.
        # ⚠️ נספרות **הודעות ולא שורות**: הרשימה מכווצת לשרשורים, ולכן
        # ‏100 הודעות עשויות לחזור כ-80 שורות, ו-``len(found)`` היה
        # אומר "לא נגענו בתקרה" בדיוק כשנגענו בה
        truncated=sum(item.thread_count for item in found) >= gmail.SCREEN_LIMIT,
    )


@router.post("/archive", response_model=EmailIdsOut)
def archive_emails(payload: EmailIdsIn, db: Session = Depends(get_db)) -> EmailIdsOut:
    """מוציא מיילים מהדואר הנכנס (שלב 4-4).

    ⚠️ **אינו מוחק דבר**, ולכן אינו דורש אישור בשרת: המיילים נשארים
    בתיבה, נמצאים בחיפוש, ו-``/unarchive`` מחזיר אותם. זאת הסיבה
    שהארכוב פועל מיד, ושהביטול הוא כפתור ולא תקווה.

    ⚠️⚠️ **רשימה ולא מזהה אחד.** שורה במסך היא שרשור, וארכוב ההודעה
    האחרונה בלבד השאיר את הישנה בדואר הנכנס — והשורה חזרה ברענון הבא.
    אותו נתיב משרת גם ארכוב של שרשור אחד וגם של כל הלא-חשובים יחד.

    **מחזיר את מה שהוצא בפועל**, והמסך שולח בדיוק אותו ל-``/unarchive``.
    """
    return EmailIdsOut(ids=_write(db, gmail.archive, payload.ids))


@router.post("/unarchive", response_model=EmailIdsOut)
def unarchive_emails(payload: EmailIdsIn, db: Session = Depends(get_db)) -> EmailIdsOut:
    """מחזיר מיילים לדואר הנכנס. הביטול של הארכוב.

    ⚠️ **מקבל בדיוק את מה שהארכוב החזיר**, ולא את כל השרשור: אחרת
    הביטול היה מחזיר הודעה שהייתה מארוכבת עוד קודם.
    """
    return EmailIdsOut(ids=_write(db, gmail.unarchive, payload.ids))


def _write(db: Session, action, ids: list[str]) -> list[str]:
    """הכתיבות אל התיבה חולקות את אותו טיפול בשגיאות כמו הקריאות."""
    _require_connection(db)
    try:
        return action(db, ids)
    except gauth.GoogleDisconnected as exc:
        log.warning("החיבור לגוגל נפסל באמצע שינוי תוויות: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DISCONNECTED) from exc
    except (gmail.GmailError, gauth.GoogleError) as exc:
        log.warning("שינוי תוויות נכשל: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, UNAVAILABLE) from exc


@router.get("/{message_id}/task-draft", response_model=TaskDraftOut)
def task_draft(message_id: str, db: Session = Depends(get_db)) -> TaskDraftOut:
    """הצעה למשימה מתוך המייל (שלב 4-5).

    ⚠️ **אינה שומרת כלום.** הטופס נפתח מלא מראש, והמשימה נוצרת רק
    בלחיצה על "שמור" — זה היתרון המרכזי של המסך על הבוט, כי הפיכת מייל
    למשימה כמעט תמיד דורשת עריכה.

    ⚠️ **הלקוח נקבע בקוד ולא במודל**, לפי כתובת השולח מול כרטיסי
    הלקוחות: שיוך הוא עובדה שיש עליה נתונים, לא שיקול דעת.
    """
    _require_connection(db)
    try:
        mail = gmail.fetch_full(db, message_id)
    except gauth.GoogleDisconnected as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DISCONNECTED) from exc
    except (gmail.GmailError, gauth.GoogleError) as exc:
        log.warning("שליפת מייל לטיוטת משימה נכשלה: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, UNAVAILABLE) from exc

    draft = gmail.task_draft(mail)
    sender = mail.sender_email.strip().lower()
    client_id = None
    if sender:
        client_id = db.scalars(
            select(Client.id).where(func.lower(Client.email) == sender).limit(1)
        ).first()

    link = gmail.gmail_link(mail.id)
    notes = "\n".join(part for part in (draft.summary, f"מהמייל של {mail.sender()}", link) if part)
    return TaskDraftOut(
        title=draft.title,
        due_date=draft.due_date or None,
        client_id=client_id,
        notes=notes,
        email_message_id=mail.id,
    )


@router.get("/{message_id}", response_model=EmailBodyOut)
def read_email(message_id: str, db: Session = Depends(get_db)) -> EmailBodyOut:
    """המייל המלא לקריאה, בלי ההיסטוריה המצוטטת.

    ⚠️ **``triage`` אינו נקרא כאן.** הסיווג הוא של הרשימה, וקריאה למודל
    על מייל בודד הייתה עלות נוספת בכל פתיחה בלי שום תוספת מידע.

    ⚠️ **``body`` הוא טקסט, לא HTML.** ‏``gmail._html_to_text`` ממיר
    לטקסט בשכבת השירות, והמסך מציג אותו כטקסט — מייל הוא מה שאדם אחר
    כתב, ו-HTML שלו לא מוזרק לדף.
    """
    _require_connection(db)
    try:
        mail = gmail.fetch_full(db, message_id)
    except gauth.GoogleDisconnected as exc:
        log.warning("החיבור לגוגל נפסל באמצע פתיחת מייל: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DISCONNECTED) from exc
    except (gmail.GmailError, gauth.GoogleError) as exc:
        log.warning("פתיחת מייל נכשלה: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, UNAVAILABLE) from exc

    return EmailBodyOut(
        id=mail.id,
        thread_id=mail.thread_id,
        sender=mail.sender(),
        sender_email=mail.sender_email,
        to=mail.to,
        subject=mail.subject,
        received_at=mail.received_at,
        body=mail.body,
        attachments=mail.attachments,
        quoted_removed=mail.quoted_removed,
    )
