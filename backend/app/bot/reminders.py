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

from .. import memory, recurring, waha
from ..auth import aware, now
from ..config import get_settings
from ..db import SessionLocal
from ..models import Task
from .actions import describe, now_local, to_local

log = logging.getLogger(__name__)

# תזכורת שזמנה עבר מזמן (למשל השרת היה כבוי) לא נשלחת, רק מסומנת כטופלה,
# כדי שהפעלה מחדש לא תציף את המשתמש בהודעות מהעבר
STALE_AFTER = timedelta(hours=12)


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
    text = f"תזכורת: {task.title}"
    if task.recurrence_id and task.due_date and task.due_date < to_local(moment or now()).date():
        # בנדנוד אותה הודעה חוזרת כל יום. בלי הסימון הזה היא לא מסבירה למה
        text += " — עבר התאריך"
    return f"{text}\n{detail}" if detail else text


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
            try:
                waha.send_text(phone, reminder_text(db, task, moment))
                sent += 1
                # מתי יצאה תזכורת, כדי שאפשר יהיה ללמוד מתי היא עובדת
                memory.observe(
                    "reminder_sent",
                    "bot",
                    task_id=task.id,
                    client_id=task.client_id,
                    detail=task.title,
                )
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
            recurring.materialize(db, now_local())
        except Exception:  # noqa: BLE001 - תקלה בחוזרות לא עוצרת תזכורות
            log.exception("יצירת משימות מהתחייבויות חוזרות נכשלה")
            db.rollback()
        send_due_reminders(db)
    finally:
        db.close()
