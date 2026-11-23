"""שליחת תזכורות בזמן שנקבע למשימה, ויצירת המשימות של התחייבויות חוזרות.

לולאה אחת שרצה בתוך תהליך ה-backend ובודקת כל כמה שניות אם הגיע זמנה של
תזכורת. אין כאן תלות ברכיב חיצוני, והשרת מריץ תהליך uvicorn אחד, כך שאין
סיכון שתי לולאות ישלחו את אותה תזכורת.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import gauth, gmail, memory, notify, recurring, timeframe, waha
from ..auth import aware, now
from ..config import get_settings
from ..db import SessionLocal
from ..models import Task
from .actions import describe, now_local, to_local

log = logging.getLogger(__name__)

# תזכורת שזמנה עבר מזמן (למשל השרת היה כבוי) לא נשלחת, רק מסומנת כטופלה,
# כדי שהפעלה מחדש לא תציף את המשתמש בהודעות מהעבר
STALE_AFTER = timedelta(hours=12)

# פותח את הודעת הוואטסאפ, וגם הכותרת של התראת הפוש. קבוע ולא מחרוזת
# כתובה פעמיים, כי הפוש גוזר אותו מהטקסט כדי לא לומר "תזכורת" פעמיים
PREFIX = "תזכורת"


def due_reminders(db: Session, moment: datetime) -> list[Task]:
    return list(
        db.scalars(
            select(Task)
            .where(
                Task.status == "open",
                Task.reminder_at.is_not(None),
                Task.reminder_at <= moment,
                Task.reminder_sent_at.is_(None),
            )
            .order_by(Task.reminder_at)
        ).all()
    )


def reminder_text(db: Session, task: Task, moment: datetime | None = None) -> str:
    detail = describe(db, task)
    text = f"{PREFIX}: {task.title}"
    if task.recurrence_id and task.due_date and task.due_date < to_local(moment or now()).date():
        # בנדנוד אותה הודעה חוזרת כל יום. בלי הסימון הזה היא לא מסבירה למה
        text += " — עבר התאריך"
    return f"{text}\n{detail}" if detail else text


def ring(text: str) -> None:
    """הפעמון, אחרי שהודעת הוואטסאפ עצמה כבר יצאה.

    ‏⚠️ הכשל נבלע כאן בכוונה. אם הוא היה עולה למעלה, הסבב הבא היה שולח
    את אותה תזכורת שוב בוואטסאפ — וכפילות גרועה יותר מהתראה שלא הגיעה.
    """
    try:
        notify.send(text.removeprefix(f"{PREFIX}: "), title=PREFIX)
    except notify.NotifyError:
        log.exception("שליחת התראת פוש נכשלה")


def nags_again(task: Task, moment: datetime) -> bool:
    """האם לשלוח תזכורת נוספת מחר.

    רק להתחייבות חוזרת, וכל עוד לא עברו שבעה ימים מהתאריך. תזכורת אחת
    שנבלעה בין הודעות היא בדיוק איך מפספסים דוח שעולה כסף.
    """
    if task.recurrence_id is None or task.due_date is None:
        return False
    return to_local(moment).date() < task.due_date + timedelta(days=recurring.NAG_DAYS)


def send_due_reminders(db: Session, moment: datetime | None = None) -> int:
    """שולח את כל התזכורות שהגיע זמנן ומחזיר כמה נשלחו."""
    moment = moment or now()
    phone = get_settings().owner_phone
    sent = 0

    for task in due_reminders(db, moment):
        # תזכורת של התחייבות חוזרת לא מתיישנת: חידוש ביטוח רלוונטי גם אם
        # השרת היה כבוי אתמול, בעוד "תזכיר לי בעוד עשר דקות" לא
        stale = task.recurrence_id is None and aware(task.reminder_at) < moment - STALE_AFTER
        if not stale and phone:
            text = reminder_text(db, task, moment)
            try:
                waha.send_text(phone, text)
                sent += 1
                # מתי יצאה תזכורת, כדי שאפשר יהיה ללמוד מתי היא עובדת
                memory.observe(
                    "reminder_sent",
                    "bot",
                    task_id=task.id,
                    client_id=task.client_id,
                    detail=task.title,
                )
                # אחרי הספירה והיומן: הפוש לא משנה אם התזכורת נשלחה
                ring(text)
            except waha.WahaError:
                # לא מסמנים כנשלח, כדי שהסבב הבא ינסה שוב
                log.exception("שליחת תזכורת למשימה %s נכשלה", task.id)
                continue
        task.reminder_sent_at = moment
        if not stale and nags_again(task, moment):
            # הנדנוד: עוד תזכורת מחר, עד שתסמן בוצע או עד שייגמר החלון
            task.reminder_at = moment + timedelta(days=1)
            task.reminder_sent_at = None
        db.commit()

    return sent


async def reminder_loop() -> None:
    interval = get_settings().reminder_poll_seconds
    while True:
        try:
            await asyncio.to_thread(_tick)
        except Exception:  # noqa: BLE001 - הלולאה חייבת לשרוד כל תקלה
            log.exception("סבב תזכורות נכשל")
        await asyncio.sleep(interval)


def _tick() -> None:
    db = SessionLocal()
    try:
        try:
            # "מחר" שנקבע ביום קודם הוא "היום" מעכשיו. לפני התזכורות, כדי
            # שהמשימה תופיע בתיוג הנכון באותו סבב
            timeframe.roll_tomorrow(db, now_local().date())
            # ואחריו לפי תאריך היעד: מה שהתקרב עולה מסגרת
            timeframe.roll_due(db, now_local().date())
        except Exception:  # noqa: BLE001 - תקלה בהתגלגלות לא עוצרת תזכורות
            log.exception("התגלגלות מסגרת הזמן נכשלה")
            db.rollback()
        try:
            recurring.materialize(db, now_local())
        except Exception:  # noqa: BLE001 - תקלה בחוזרות לא עוצרת תזכורות
            log.exception("יצירת משימות מהתחייבויות חוזרות נכשלה")
            db.rollback()
        send_due_reminders(db)
        try:
            watch_google(db)
        except Exception:  # noqa: BLE001 - תקלה בבדיקת גוגל לא עוצרת כלום
            log.exception("בדיקת החיבור לגוגל נכשלה")
            db.rollback()
        try:
            warm_mail_screen(db)
        except Exception:  # noqa: BLE001 - חימום הוא נוחות, לא תלות
            log.exception("חימום מסך המיילים נכשל")
            db.rollback()
    finally:
        db.close()


# --- חימום מסך המיילים ---

# כל כמה זמן מסווגים את התיבה מראש. ⚠️ **קצר מ-``gmail.TRIAGE_TTL``
# (חצי שעה) בכוונה**, אחרת היה נפתח חלון שבו המטמון פג והחימום עוד לא
# רץ — בדיוק המצב שהחימום נועד למנוע.
WARM_EVERY = timedelta(minutes=20)
# איזה חלון זמן מחממים: זה שהמסך נפתח עליו כברירת מחדל. "היום" מוכל בו
# ונהנה מאותו מטמון, ו"החודש" נשאר קר — הוא גם נפתח לעתים רחוקות
WARM_SCOPE = "week"

_warmed_at: datetime | None = None


def warm_mail_screen(db: Session, moment: datetime | None = None) -> bool:
    """מסווג מראש את הדואר הנכנס, כדי שהמסך ייפתח מהר.

    ‏**למה זה נחוץ:** נמדד מול התיבה האמיתית ב-24.11.2026 — הסיווג הוא
    ‏9 מתוך 10 שניות הטעינה, וההמתנה היא זמן תגובה קבוע של המודל שחלוקה
    למנות מקבילות אינה מקצרת. עם מטמון חם המסך נטען ב-1.5 שניות.

    ⚠️ **זו נוחות ולא תלות.** כל כשל נבלע: המסך פשוט ייטען קר, בדיוק
    כמו קודם. בפרט, כישלון כאן לעולם אינו נוגע בתזכורות.

    ⚠️ **המטמון חי בזיכרון התהליך**, והלולאה הזאת רצה באותו תהליך של
    ה-API (‏uvicorn אחד, בלי ``--workers``). אם מישהו יוסיף תהליכי עבודה,
    החימום יחמם מטמון של תהליך אחד בלבד והמסך יישאר איטי.

    מחזיר True אם הסבב הזה באמת חימם.
    """
    global _warmed_at
    moment = moment or now()
    if _warmed_at is not None and moment - _warmed_at < WARM_EVERY:
        return False

    cred = gauth.get_credential(db)
    if cred is None or cred.status != "connected":
        return False

    # מסומן לפני העבודה ולא אחריה: אם הסיווג ייכשל, אין טעם לנסות שוב
    # בעוד שלושים שניות ולשרוף קריאות
    _warmed_at = moment
    found = gmail.list_screen(db, WARM_SCOPE)
    if not found:
        return False
    gmail.triage(found, gmail.client_addresses(db))
    log.info("מסך המיילים חומם: %d שורות", len(found))
    return True


def reset_warm_clock() -> None:
    """לבדיקות: מאפס את השעון כדי שהחימום הבא ירוץ."""
    global _warmed_at
    _warmed_at = None


def watch_google(db: Session, moment: datetime | None = None) -> bool:
    """הבדיקה התקופתית של החיבור לגוגל. מחזיר True אם יצאה הודעת ניתוק.

    יושב בלולאה הזאת ולא בלולאה משלו כי היא כבר רצה, והבדיקה עצמה היא
    קריאת רשת אחת ביממה. ‏``gauth.check`` מחליט לבד אם הגיע הזמן.
    """
    cred = gauth.check(db, moment or now())
    return bool(cred) and gauth.announce_disconnect(db, cred)
