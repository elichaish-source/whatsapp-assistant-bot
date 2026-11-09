"""פעמון: התראת פוש שמשמיעה צליל, כי וואטסאפ לא מתריע על הודעה לעצמך.

הבוט מחובר כמכשיר מקושר למספר של המשתמש, ולכן כל תזכורת שהוא שולח היא
הודעה ממנו אל עצמו — ועל אלה וואטסאפ לא מתריע בשום הגדרה: אין צליל, אין
באנר, והצ'אט לא נדחף לראש הרשימה. בפועל התזכורות לא נראו. ההודעה עצמה
ממשיכה לצאת בוואטסאפ בדיוק כמו קודם, והמודול הזה רק דואג שהטלפון יצפצף.

‏⚠️ כלל ברזל: הפוש הוא העשרה ולא תלות. כשל שלו נרשם ביומן ואסור לו לגעת
בסימון שהתזכורת נשלחה — אחרת הסבב הבא היה שולח את אותה תזכורת שוב
בוואטסאפ, וכפילות גרועה יותר מהתראה שלא הגיעה. לכן הקורא עוטף ב-try/except.

השליחה היא JSON לשורש הכתובת, ולא כותרות HTTP כמו בדוגמאות הנפוצות של
‏ntfy: כותרות HTTP אינן UTF-8, וכותרת בעברית נשברת עוד לפני שהבקשה יוצאת.
"""

import logging

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

# ‏4 הוא "high" ב-ntfy: צליל ורטט. ‏5 הוא צפירת חירום, ולא כל תזכורת היא כזאת
PRIORITY = 4
TIMEOUT = 10


class NotifyError(Exception):
    pass


def configured() -> bool:
    """בלי נושא מוגדר אין פוש, והמערכת מתנהגת בדיוק כמו לפני השלב הזה."""
    settings = get_settings()
    return bool(settings.ntfy_url and settings.ntfy_topic)


def chat_link() -> str:
    """קישור שפותח את הצ'אט של הבוט, המקום שבו עונים "סיימתי 2".

    ‏⚠️ פתיחת צ'אט עם המספר של עצמך דרך wa.me אינה עובדת בכל גרסה של
    וואטסאפ. זה נבדק מול הטלפון באימות השלב, ואם נכשל — מחליפים כאן
    לכתובת הדשבורד.
    """
    phone = get_settings().owner_phone
    return f"https://wa.me/{phone}" if phone else ""


def send(message: str, title: str, click: str | None = None) -> None:
    """שולח התראה אחת. לא מוגדר — לא עושה כלום. נכשל — מרים NotifyError."""
    settings = get_settings()
    if not configured():
        return

    payload: dict = {
        "topic": settings.ntfy_topic,
        "title": title,
        "message": message,
        "priority": PRIORITY,
        "tags": ["bell"],
    }
    # ‏None פירושו "קח את ברירת המחדל", ומחרוזת ריקה פירושה "בלי לחיצה"
    link = chat_link() if click is None else click
    if link:
        payload["click"] = link

    headers = {"Authorization": f"Bearer {settings.ntfy_token}"} if settings.ntfy_token else {}
    try:
        resp = httpx.post(settings.ntfy_url, json=payload, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise NotifyError(str(exc)) from exc
