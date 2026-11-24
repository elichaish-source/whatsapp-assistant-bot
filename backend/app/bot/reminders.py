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
            # ⚠️ שליפה אחת מגוגל לשניהם: החימום מחזיר את השורות
            # המסווגות, וההכנה רוכבת עליהן. בלי זה ההכנה הייתה שולפת
            # את התיבה בכל טיק, כלומר פעמיים בדקה
            triaged = warm_mail_screen(db)
            if triaged:
                prepare_drafts(db, triaged)
        except Exception:  # noqa: BLE001 - חימום והכנה הם נוחות, לא תלות
            log.exception("חימום המסך או הכנת הטיוטות נכשלו")
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


def warm_mail_screen(db: Session, moment: datetime | None = None) -> list | None:
    """מסווג מראש את הדואר הנכנס, כדי שהמסך ייפתח מהר.

    ‏**למה זה נחוץ:** נמדד מול התיבה האמיתית ב-24.11.2026 — הסיווג הוא
    ‏9 מתוך 10 שניות הטעינה, וההמתנה היא זמן תגובה קבוע של המודל שחלוקה
    למנות מקבילות אינה מקצרת. עם מטמון חם המסך נטען ב-1.5 שניות.

    ⚠️ **זו נוחות ולא תלות.** כל כשל נבלע: המסך פשוט ייטען קר, בדיוק
    כמו קודם. בפרט, כישלון כאן לעולם אינו נוגע בתזכורות.

    ⚠️ **המטמון חי בזיכרון התהליך**, והלולאה הזאת רצה באותו תהליך של
    ה-API (‏uvicorn אחד, בלי ``--workers``). אם מישהו יוסיף תהליכי עבודה,
    החימום יחמם מטמון של תהליך אחד בלבד והמסך יישאר איטי.

    ⚠️ **מחזיר את השורות המסווגות, ולא רק True.** הלולאה מעבירה אותן
    ל-``prepare_drafts``, כדי שהשליפה מגוגל והסיווג יקרו **פעם אחת**
    ויגישו לשניהם. ‏None פירושו "לא רץ הפעם".
    """
    global _warmed_at
    moment = moment or now()
    if _warmed_at is not None and moment - _warmed_at < WARM_EVERY:
        return None

    cred = gauth.get_credential(db)
    if cred is None or cred.status != "connected":
        return None

    # מסומן לפני העבודה ולא אחריה: אם הסיווג ייכשל, אין טעם לנסות שוב
    # בעוד שלושים שניות ולשרוף קריאות
    _warmed_at = moment
    found = gmail.list_screen(db, WARM_SCOPE)
    if not found:
        return []
    triaged = gmail.triage(found, gmail.client_addresses(db))
    log.info("מסך המיילים חומם: %d שורות", len(found))
    return triaged


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


# --- הכנת טיוטות מראש (הוכרע 24.11.2026) ---


def _prepare_hours() -> set[int]:
    """השעות שבהן מוכנות טיוטות מענה, מתוך ההגדרות."""
    found = set()
    for part in get_settings().reply_prepare_hours.split(","):
        part = part.strip()
        if part.isdigit() and 0 <= int(part) <= 23:
            found.add(int(part))
    return found


def _newer_than(rows, since: datetime | None):
    """המיילים שהגיעו אחרי החותמת. ⚠️ זה מה שמונע הכנה מחדש."""
    if since is None:
        return list(rows)
    return [item for item in rows if item.received_at > aware(since)]


def prepare_drafts(
    db: Session, triaged: list | None = None, moment: datetime | None = None
) -> tuple[int, int]:
    """מכין מראש טיוטת משימה לכל מייל חדש, וטיוטות מענה בשעות שנקבעו.

    ⚠️⚠️ **"טיוטה אחת לכל מייל, אי פעם" — זה מה שמגביל את העלות.**
    מוכנות טיוטות רק למיילים שהגיעו אחרי החותמת שבמסד, והחותמת מתקדמת
    בסוף כל סבב. הפעלה מחדש מוחקת את המטמון שבזיכרון אך לא את החותמת,
    ולכן **אינה גוררת הכנה מחדש** — מייל ישן חוזר ללחיצה ידנית.

    ⚠️ **המענה יקר בהרבה מהמשימה** (‏Opus עם גוף המייל מול Haiku, פי
    חמישים), ולכן הוא מוכן רק בשעות שנקבעו ורק למה שסומן ``needs_reply``.

    ⚠️ **זו נוחות ולא תלות:** כשאין טיוטה מוכנה, הלחיצה מכינה אותה בזמן
    אמת בדיוק כמו קודם.

    מחזיר (טיוטות משימה שהוכנו, טיוטות מענה שהוכנו).
    """
    moment = moment or now()
    cred = gauth.get_credential(db)
    if cred is None or cred.status != "connected":
        return 0, 0

    # ⚠️ השורות מגיעות מהחימום ולא נשלפות שוב. בגרסה הראשונה ההכנה
    # שלפה מגוגל בעצמה, ומכיוון שהיא רצה בכל טיק (כל 30 שניות) זו
    # הייתה שליפה מלאה מהתיבה פעמיים בדקה
    if triaged is None:
        rows = gmail.list_screen(db, WARM_SCOPE)
        if not rows:
            return 0, 0
        triaged = gmail.triage(rows, gmail.client_addresses(db))
    if not triaged:
        return 0, 0

    tasks_made = 0
    for item in _newer_than([t.email for t in triaged if t.relevant], cred.last_prepared_at):
        if gmail.prepared_for(item.id) and gmail.prepared_for(item.id).task:
            continue
        try:
            mail = gmail.fetch_full(db, item.id)
            gmail.remember_prepared(item.id, moment, task=gmail.task_draft(mail))
            tasks_made += 1
        except Exception:  # noqa: BLE001 - הכנה היא נוחות
            log.warning("הכנת טיוטת משימה ל-%s נכשלה", item.id)
    cred.last_prepared_at = moment

    replies_made = 0
    if moment.astimezone(gmail.local_tz()).hour in _prepare_hours():
        wanted = [t.email for t in triaged if t.needs_reply]
        block = memory.build_block(db)
        for item in _newer_than(wanted, cred.last_reply_prepared_at):
            ready = gmail.prepared_for(item.id)
            if ready and ready.replies:
                continue
            try:
                mail = gmail.fetch_full(db, item.id)
                options = gmail.reply_suggestions(mail, block)
                if options:
                    gmail.remember_prepared(item.id, moment, replies=options)
                    replies_made += 1
            except Exception:  # noqa: BLE001 - הכנה היא נוחות
                log.warning("הכנת טיוטת מענה ל-%s נכשלה", item.id)
        cred.last_reply_prepared_at = moment

    db.commit()
    if tasks_made or replies_made:
        log.info("הוכנו מראש: %d משימות, %d מענים", tasks_made, replies_made)
    return tasks_made, replies_made
