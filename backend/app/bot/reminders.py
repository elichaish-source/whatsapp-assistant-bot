"""שליחת תזכורות בזמן שנקבע למשימה.

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

from .. import memory, waha
from ..auth import aware, now
from ..config import get_settings
from ..db import SessionLocal
from ..models import Task
from .actions import describe

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


def reminder_text(db: Session, task: Task) -> str:
    detail = describe(db, task)
    text = f"תזכורת: {task.title}"
    return f"{text}\n{detail}" if detail else text


def send_due_reminders(db: Session, moment: datetime | None = None) -> int:
    """שולח את כל התזכורות שהגיע זמנן ומחזיר כמה נשלחו."""
    moment = moment or now()
    phone = get_settings().owner_phone
    sent = 0

    for task in due_reminders(db, moment):
        stale = aware(task.reminder_at) < moment - STALE_AFTER
        if not stale and phone:
            try:
                waha.send_text(phone, reminder_text(db, task))
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
        send_due_reminders(db)
    finally:
        db.close()
