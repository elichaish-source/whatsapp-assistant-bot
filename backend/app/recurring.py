"""התחייבויות חוזרות: מתי המחזור הבא, ומתי הוא הופך למשימה.

שלוש החלטות מעצבות את המודול הזה (אושרו 4.11.2026):

1. **ישות נפרדת שמייצרת משימות**, ולא שדה חזרה על המשימה. כל מחזור הוא
   שורה אמיתית שנסגרת, ולכן ההיסטוריה נשמרת.
2. **מחזור אחד פתוח בכל פעם.** המחזור הבא נוצר רק כשהקודם נסגר והגיע זמנו.
3. **התראה מראש לכל התחייבות** (``lead_days``), כי ביום חידוש הביטוח כבר
   אין מה לעשות.

התאריך הבא מחושב ולא נשמר — ראה את ההסבר במודל ``Recurrence``.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import memory
from .models import Recurrence, Task

log = logging.getLogger(__name__)

# השעה שבה יוצאת תזכורת על התחייבות חוזרת, בשעון המקומי
REMINDER_HOUR = 9
# עד כמה ימים אחרי התאריך ממשיכים להזכיר, כל עוד לא סומן "בוצע"
NAG_DAYS = 7

_SINGULAR = {"week": "שבוע", "month": "חודש", "year": "שנה"}
_DUAL = {"week": "שבועיים", "month": "חודשיים", "year": "שנתיים"}
_PLURAL = {"week": "שבועות", "month": "חודשים", "year": "שנים"}


def shift(day: date, unit: str, count: int) -> date:
    """מזיז תאריך בכמה יחידות חזרה."""
    if count == 0:
        return day
    if unit == "week":
        return day + timedelta(weeks=count)
    months = count * (12 if unit == "year" else 1)
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    # ‏31 בחודש שאין בו 31 נדחף ליום האחרון. המחזור שאחריו מחושב שוב מהעוגן
    # ולכן חוזר ל-31, במקום להישאר על 28 לנצח
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def next_due(rec: Recurrence) -> date:
    """תאריך המחזור הבא שעדיין לא הפך למשימה."""
    return shift(rec.start_date, rec.interval_unit, rec.interval_count * rec.cycle)


def describe_interval(unit: str, count: int) -> str:
    """"כל חודשיים", "כל 3 שבועות" — לתשובות הבוט ולמסך בדשבורד."""
    if count == 1:
        return f"כל {_SINGULAR[unit]}"
    if count == 2:
        return f"כל {_DUAL[unit]}"
    return f"כל {count} {_PLURAL[unit]}"


def catch_up(rec: Recurrence, today: date) -> None:
    """מדלג על מחזורים שתאריכם עבר, כך שהמחזור הראשון יהיה מהיום והלאה.

    התחייבות שנרשמת עם תאריך התחלה מלפני שנה לא אמורה לייצר משימה שהתאריך
    שלה עבר מזמן, ובטח לא שרשרת של מחזורים שלא היינו שם כדי לפספס.
    """
    # הגנה: ``interval_count`` תמיד לפחות 1, אז הלולאה מתקדמת — אבל אם אי
    # פעם ייכנס 0 דרך בסיס הנתונים, עדיף לצאת מלולאה אין-סופית
    for _ in range(2000):
        if next_due(rec) >= today:
            return
        rec.cycle += 1


def has_open_task(db: Session, recurrence_id: int) -> bool:
    row = db.scalars(
        select(Task.id)
        .where(Task.recurrence_id == recurrence_id, Task.status == "open")
        .limit(1)
    ).first()
    return row is not None


def first_reminder(due: date, lead_days: int, moment: datetime) -> datetime:
    """מתי תצא התזכורת הראשונה על המחזור הזה.

    בשעה הקבועה ביום ההתראה המוקדמת — ואם אותו רגע כבר עבר (ההתחייבות
    נרשמה אחרי תשע, או עם תאריך קרוב), מיד. תזכורת שנקבעת לאחור הייתה
    נחשבת מיושנת ונזרקת בלי להישלח.
    """
    day = max(due - timedelta(days=lead_days), moment.date())
    planned = datetime.combine(day, time(REMINDER_HOUR), tzinfo=moment.tzinfo)
    return planned if planned > moment else moment


def materialize(db: Session, moment: datetime) -> int:
    """יוצר משימה לכל התחייבות שהגיע זמנה, ומחזיר כמה נוצרו.

    מחזור אחד פתוח בכל פעם: אם המשימה מהמחזור הקודם עוד לא סומנה כבוצעה,
    לא נוצרת חדשה. זה מה שמשאיר את רשימת המשימות אמיתית — מה שפתוח בה הוא
    מה שצריך לעשות, ולא שלושה מחזורים של אותה התחייבות.
    """
    today = moment.date()
    created = 0

    rows = db.scalars(
        select(Recurrence).where(Recurrence.active.is_(True)).order_by(Recurrence.id)
    ).all()
    for rec in rows:
        due = next_due(rec)
        if due - timedelta(days=rec.lead_days) > today:
            continue
        if has_open_task(db, rec.id):
            continue

        task = Task(
            title=rec.title,
            status="open",
            domain_id=rec.domain_id,
            task_type_id=rec.task_type_id,
            client_id=rec.client_id,
            project_id=rec.project_id,
            due_date=due,
            reminder_at=first_reminder(due, rec.lead_days, moment),
            priority=rec.priority,
            notes=rec.notes,
            # המקור של המשימה הוא הערוץ שבו נרשמה ההתחייבות. העובדה שהיא
            # חוזרת מסומנת בנפרד ב-recurrence_id
            source="whatsapp" if rec.from_bot else "dashboard",
            priority_set_on=today,
            recurrence_id=rec.id,
        )
        db.add(task)
        rec.cycle += 1
        db.commit()
        db.refresh(task)
        created += 1

        memory.observe(
            "recurrence_due",
            "bot",
            task_id=task.id,
            client_id=task.client_id,
            detail=f"{rec.title} · {describe_interval(rec.interval_unit, rec.interval_count)}",
        )

    return created


def today_local() -> date:
    """התאריך בשעון המקומי. הלולאה מקבלת את הרגע מבחוץ, אבל ה-API לא."""
    from zoneinfo import ZoneInfo

    from .config import get_settings

    return datetime.now(ZoneInfo(get_settings().timezone)).date()
