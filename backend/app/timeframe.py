"""מסגרת הזמן של משימה, וההתגלגלות של "מחר" ל"היום".

מסגרת הזמן היא תג ולא תאריך, ובדיוק בגלל זה "מחר" חייב להתגלגל: בלי זה
משימה שתויגה "מחר" לפני שבוע תמשיך להציג "מחר" לנצח. priority_set_on
שומרת את היום שבו התיוג נקבע, ולכן אפשר להבדיל בין "מחר" שנקבע היום ובין
כזה שנקבע אתמול — והלולאה מזיזה רק את השני.

היום מחושב כאן לפי שעון ישראל ולא ב-UTC, אחרת כל תיוג בין חצות לשתיים
בלילה היה נחשב ליום הקודם.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import memory
from .auth import now
from .config import get_settings
from .models import Task


def local_today() -> date:
    return now().astimezone(ZoneInfo(get_settings().timezone)).date()


def set_priority(task: Task, priority: str, today: date | None = None) -> None:
    """קובע את מסגרת הזמן וחותם את היום שבו זה נעשה.

    כל מי שמשנה priority חייב לעבור כאן, אחרת ההתגלגלות תעבוד על חותמת
    ישנה ותזיז "מחר" שנקבע רק עכשיו.
    """
    task.priority = priority
    task.priority_set_on = local_today() if today is None else today


def roll_tomorrow(db: Session, today: date) -> int:
    """מעביר ל"היום" כל משימה פתוחה שתויגה "מחר" ביום קודם.

    משימה בלי חותמת נחשבת גם היא לישנה: "מחר" שאין לו יום הוא חסר משמעות,
    ועדיף שיעלה לראש הרשימה מלהיעלם בה.
    """
    rows = db.scalars(
        select(Task).where(
            Task.status == "open",
            Task.priority == "tomorrow",
            or_(Task.priority_set_on.is_(None), Task.priority_set_on < today),
        )
    ).all()
    if not rows:
        return 0

    for task in rows:
        set_priority(task, "today", today)
    db.commit()

    # הרישום אחרי ה-commit ובמקור "system": משימה שזזה בלי שאף אחד נגע בה
    # צריכה להשאיר עקבות, אחרת היא נראית כאילו קפצה לבד. אם השמירה נכשלה
    # שום דבר לא זז, ולכן גם אין מה לרשום. אותו מבנה detail כמו בדשבורד,
    # כדי שמסך היסטוריה עתידי יפרש פורמט אחד
    for task in rows:
        memory.observe(
            "task_reprioritized",
            "system",
            task_id=task.id,
            client_id=task.client_id,
            detail=f"{task.title} · priority: tomorrow → today (התגלגלות אוטומטית)",
        )

    return len(rows)
