"""הודעות שהמערכת יוזמת: שליחה בוואטסאפ ורישום ביומן ההודעות.

**למה זה קיים.** עד 26.11.2026 תזכורת, סיכום, התראה ותדריך יצאו ישירות
דרך ``waha.send_text`` ולא נרשמו בשום מקום. התוצאה: מסך הוואטסאפ לא
יכול היה להראות אותן, ולא היה שום מקום שאומר "על זה התרעתי ולא טיפלת".
⚠️ זה גם הנימוק היחיד שנשאר לבוט לפי העיקרון המנחה — **הודעה יוזמת
יוצאת בוואטסאפ ומופיעה גם במסך**, כי מסך אינו מגיע למי שאינו מולו.

⚠️ **השליחה קודמת לרישום, במכוון.** המסד מתעד מה באמת יצא; אם
הוואטסאפ נכשל, אין שורה, והסבב הבא ינסה שוב — בדיוק הסדר שכבר נקבע
ב-``event_briefs``.

⚠️⚠️ **הרישום נעשה בעסקה נפרדת משלו.** הקוראים (``reminders``,
``briefs``) מחזיקים שינויים לא שמורים בעסקה שלהם — ``reminder_sent_at``,
‏``EventBrief`` — ו-``rollback`` על מזהה כפול היה מוחק אותם. העסקה
הנפרדת הופכת את הרישום לדבר שאינו יכול להזיק למה שהוא מתעד.

⚠️ **מה נשמר הוא הטקסט שיצא, ולא העתק של מקור חיצוני.** לתדריך יש
``journal`` נפרד בדיוק בשביל זה: הטקסט שיוצא בוואטסאפ פותח בשעה
ובכותרת הפגישה, ו-``frontend/public/privacy.html`` מבטיח שהיומן אינו
משוקף למסד. מה שנרשם הוא מה שנבנה מהנתונים שכבר אצלנו.
"""

import logging

from sqlalchemy.exc import IntegrityError

from .. import waha
from ..db import SessionLocal
from ..models import BotMessage

log = logging.getLogger(__name__)

# הכוונות שמסמנות הודעה יוזמת. ⚠️ לא פעולות שמבקשים, ולכן אינן נוגעות
# בסכימת הכוונות ובמונה 15 מתוך 16
REMINDER = "reminder"
MAIL_DIGEST = "mail_digest"
MAIL_ALERT = "mail_alert"
BRIEF = "brief"
GOOGLE_DISCONNECTED = "google_disconnected"

KINDS = (REMINDER, MAIL_DIGEST, MAIL_ALERT, BRIEF, GOOGLE_DISCONNECTED)


def record(text: str, kind: str, key: str) -> None:
    """רושם הודעה יוזמת ביומן. כישלון כאן אינו מבטל את מה שכבר נשלח."""
    with SessionLocal() as db:
        try:
            db.add(
                BotMessage(
                    # ⚠️ מזהה מלאכותי: אין כאן הודעה של וואטסאפ. התחילית
                    # ``sys:`` מבדילה, והייחודיות היא מה שמונע רישום כפול
                    # של אותה התראה כשהסבב חוזר
                    wa_message_id=f"sys:{kind}:{key}"[:200],
                    channel="whatsapp",
                    initiated=True,
                    intent=kind,
                    reply=text,
                )
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            log.info("הודעה יוזמת כבר רשומה ביומן: %s/%s", kind, key)
        except Exception:  # noqa: BLE001 - רישום לא יפיל שליחה שהצליחה
            db.rollback()
            log.exception("רישום הודעה יוזמת ביומן נכשל")


def send(phone: str, text: str, kind: str, key: str, journal: str | None = None) -> None:
    """שולח בוואטסאפ ואז רושם. ``waha.WahaError`` עולה הלאה כמו קודם.

    ``journal`` הוא מה שנרשם כשהוא שונה ממה שנשלח — היום רק בתדריך.
    """
    waha.send_text(phone, text)
    record(journal if journal is not None else text, kind, key)
