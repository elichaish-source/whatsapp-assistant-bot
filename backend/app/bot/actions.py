"""ביצוע הכוונה שחולצה מההודעה, וניסוח התשובה בעברית.

השכבה הזאת לא מדברת עם Claude ולא עם וואטסאפ. היא מקבלת Intent ומחזירה
טקסט תשובה, כך שאפשר לבדוק את כל ההתנהגות בלי קריאה ל-API חיצוני.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import memory, recurring, timeframe
from ..auth import aware, now
from ..config import get_settings
from ..models import BotMessage, Client, Domain, MemoryFact, Project, Recurrence, Task, TaskType
from ..routers.tasks import resolve_task_fields
from ..schemas import TaskIn
from .intent import Intent

# כמה זמן אחרי השמירה עוד אפשר לכתוב "בטל"
CANCEL_WINDOW = timedelta(hours=2)
LIST_LIMIT = 15

# כמה מההתכתבות הקודמת נשלחת למודל. החלון קצר בכוונה: ארוך מספיק כדי
# שהודעת המשך ("בעצם ביום חמישי") תתחבר לקודמתה, וקצר מכדי שהודעה מלפני
# שעה תבלבל את הפענוח.
HISTORY_WINDOW = timedelta(minutes=15)
HISTORY_EXCHANGES = 6
HISTORY_LINE_CHARS = 200


def local_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def to_local(value: datetime) -> datetime:
    return aware(value).astimezone(local_tz())


def now_local() -> datetime:
    return now().astimezone(local_tz())


# --- בניית ההקשר שנשלח למודל ---


def build_context(db: Session) -> str:
    """מתאר למודל את הרשימות שהמשתמש עובד איתן, עם המזהים."""
    lines: list[str] = []

    domains = db.scalars(select(Domain).order_by(Domain.sort_order, Domain.id)).all()
    lines.append("תחומים (id: שם):")
    for item in domains:
        mark = " [מחייב לקוח]" if item.requires_client else ""
        lines.append(f"  {item.id}: {item.name}{mark}")

    types = db.scalars(select(TaskType).order_by(TaskType.sort_order, TaskType.id)).all()
    lines.append("סוגי משימה (id: שם):")
    lines.extend(f"  {item.id}: {item.name}" for item in types)

    clients = db.scalars(
        select(Client).where(Client.is_active.is_(True)).order_by(Client.name)
    ).all()
    lines.append("לקוחות פעילים (id: שם):")
    if clients:
        lines.extend(f"  {item.id}: {item.name}" for item in clients)
    else:
        lines.append("  (אין)")

    projects = db.scalars(
        select(Project).where(Project.status == "active").order_by(Project.name)
    ).all()
    if projects:
        lines.append("פרויקטים פעילים (id: שם, לקוח):")
        for item in projects:
            lines.append(f"  {item.id}: {item.name}, לקוח {item.client_id or '-'}")

    return "\n".join(lines)


def _one_line(text: str) -> str:
    """מכווץ תשובה רב-שורתית לשורה אחת קצרה, כדי שההיסטוריה תישאר זולה."""
    return " ".join((text or "").split())[:HISTORY_LINE_CHARS]


def build_history(db: Session, before_id: int) -> str:
    """חילופי הדברים האחרונים בצ'אט, מהישן לחדש. מחרוזת ריקה כשאין.

    בלי זה כל הודעה היא שיחה חדשה, ושאלת הבהרה של הבוט לא יכולה לקבל
    תשובה: הוא שואל "לאיזה לקוח?" ואז לא זוכר על מה שאל.
    """
    rows = db.scalars(
        select(BotMessage)
        .where(
            BotMessage.id < before_id,
            BotMessage.reply.is_not(None),
            BotMessage.created_at >= now() - HISTORY_WINDOW,
        )
        .order_by(BotMessage.id.desc())
        .limit(HISTORY_EXCHANGES)
    ).all()
    if not rows:
        return ""

    lines = ["השיחה עד עכשיו (ישן → חדש):"]
    for row in reversed(list(rows)):
        stamp = f"{to_local(row.created_at):%H:%M}"
        lines.append(f"[{stamp}] אני: {_one_line(row.body or '')}")
        lines.append(f"[{stamp}] העוזר: {_one_line(row.reply or '')}")
    return "\n".join(lines)


# --- ניסוח ---


def _client_name(db: Session, client_id: int | None) -> str | None:
    if client_id is None:
        return None
    client = db.get(Client, client_id)
    return client.name if client else None


def describe(db: Session, task: Task) -> str:
    """שורה אחת שמתארת משימה, בלי הכותרת."""
    parts: list[str] = []
    name = _client_name(db, task.client_id)
    if name:
        parts.append(name)
    if task.project_id:
        project = db.get(Project, task.project_id)
        if project:
            parts.append(project.name)
    if task.due_date:
        parts.append(f"עד {task.due_date:%d/%m}")
    if task.reminder_at:
        parts.append(f"תזכורת {to_local(task.reminder_at):%d/%m %H:%M}")
    if task.priority == "today":
        parts.append("היום")
    return " · ".join(parts)


def _format_list(db: Session, tasks: list[Task]) -> str:
    lines = []
    for index, task in enumerate(tasks, start=1):
        detail = describe(db, task)
        lines.append(f"{index}. {task.title}" + (f" — {detail}" if detail else ""))
    return "\n".join(lines)


# --- פעולות ---


class Outcome:
    """התשובה למשתמש, ומה לרשום ביומן."""

    def __init__(
        self,
        reply: str,
        task_id: int | None = None,
        listed_task_ids: list[int] | None = None,
        recurrence_id: int | None = None,
        fact_id: int | None = None,
    ) -> None:
        self.reply = reply
        self.task_id = task_id
        self.listed_task_ids = listed_task_ids or []
        self.fact_id = fact_id
        self.recurrence_id = recurrence_id


def _parse_due(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_reminder(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz())
    return parsed


def _add_task(db: Session, intent: Intent) -> Outcome:
    if not intent.title:
        return Outcome("לא הבנתי מה המשימה. אפשר לנסח שוב?")

    body = TaskIn(
        title=intent.title[:500],
        domain_id=intent.domain_id,
        task_type_id=intent.task_type_id,
        client_id=intent.client_id,
        project_id=intent.project_id,
        due_date=_parse_due(intent.due_date),
        reminder_at=_parse_reminder(intent.reminder_at),
        priority=intent.priority or "week",
        notes=intent.notes,
    )
    try:
        data = resolve_task_fields(db, body)
    except HTTPException as exc:
        # כללי השיוך של הדשבורד נכשלו — למשל תחום שמחייב לקוח בלי לקוח
        return Outcome(f"לא שמרתי: {exc.detail}")

    data.pop("status", None)
    task = Task(**data, status="open", source="whatsapp")
    timeframe.set_priority(task, task.priority)
    db.add(task)
    db.commit()
    db.refresh(task)

    memory.observe(
        "task_created", "bot", task_id=task.id, client_id=task.client_id, detail=task.title
    )

    detail = describe(db, task)
    reply = f"נשמר: {task.title}"
    if detail:
        reply += f"\n{detail}"
    return Outcome(reply + '\nלביטול כתוב "בטל".', task_id=task.id)


def _add_recurring(db: Session, intent: Intent) -> Outcome:
    """רושם התחייבות שחוזרת מעצמה: "כל חודשיים ב-15 דוח מע"מ".

    ההתחייבות עצמה אינה משימה — היא מייצרת משימה בכל מחזור. אם חלון ההתראה
    של המחזור הראשון כבר נפתח, המשימה נוצרת כאן ומיד, ולא בסבב הבא של
    הלולאה, כדי שהתשובה שתקבל תהיה נכונה גם רגע אחרי השמירה.
    """
    if not intent.title:
        return Outcome("לא הבנתי מה ההתחייבות. אפשר לנסח שוב?")
    if intent.repeat_unit not in ("week", "month", "year"):
        return Outcome('לא הבנתי כל כמה זמן זה חוזר. אפשר לכתוב למשל "כל חודשיים"?')

    start = _parse_due(intent.due_date)
    if not start:
        return Outcome('ממתי מתחילים? אפשר לכתוב תאריך, למשל "מה-15 בחודש הבא".')

    body = TaskIn(
        title=intent.title[:500],
        domain_id=intent.domain_id,
        task_type_id=intent.task_type_id,
        client_id=intent.client_id,
        project_id=intent.project_id,
        priority=intent.priority or "week",
        notes=intent.notes,
    )
    try:
        # אותם כללי שיוך של משימה: הסיווג יעבור לכל מחזור, אז עדיף שייפול
        # כאן פעם אחת ולא בכל מחזור מחדש
        data = resolve_task_fields(db, body)
    except HTTPException as exc:
        return Outcome(f"לא שמרתי: {exc.detail}")

    rec = Recurrence(
        title=data["title"],
        interval_unit=intent.repeat_unit,
        interval_count=min(max(intent.repeat_count or 1, 1), 60),
        start_date=start,
        cycle=0,
        lead_days=min(max(intent.lead_days or 0, 0), 365),
        domain_id=data["domain_id"],
        task_type_id=data["task_type_id"],
        client_id=data["client_id"],
        project_id=data["project_id"],
        priority=data["priority"],
        notes=data["notes"],
        from_bot=True,
    )
    # תאריך התחלה שעבר לא מייצר משימה באיחור, אלא מדלג למחזור הבא
    recurring.catch_up(rec, now_local().date())
    db.add(rec)
    db.commit()
    db.refresh(rec)

    every = recurring.describe_interval(rec.interval_unit, rec.interval_count)
    memory.observe(
        "recurrence_created", "bot", client_id=rec.client_id, detail=f"{rec.title} · {every}"
    )

    due = recurring.next_due(rec)
    recurring.materialize(db, now_local())

    parts = [every, f"הפעם הבאה {due:%d/%m/%Y}"]
    if rec.lead_days:
        parts.append(f"התראה {rec.lead_days} ימים לפני")
    reply = f"נשמר כהתחייבות חוזרת: {rec.title}\n" + " · ".join(parts)
    return Outcome(reply + '\nלביטול כתוב "בטל".', recurrence_id=rec.id)


def _resolve_by_number(db: Session, number: int) -> Task | None:
    """מתרגם מספר ששהמשתמש ציטט לרשימה האחרונה שהבוט שלח."""
    row = db.scalars(
        select(BotMessage)
        .where(BotMessage.listed_task_ids.is_not(None))
        .order_by(BotMessage.id.desc())
        .limit(1)
    ).first()
    if not row or not row.listed_task_ids:
        return None
    ids = [int(part) for part in row.listed_task_ids.split(",") if part]
    if not 1 <= number <= len(ids):
        return None
    return db.get(Task, ids[number - 1])


def _complete_task(db: Session, intent: Intent) -> Outcome:
    task: Task | None = None

    if intent.task_number:
        task = _resolve_by_number(db, intent.task_number)
        if task is None:
            return Outcome("לא מצאתי משימה במספר הזה. אפשר לבקש \"רשימה\" ולנסות שוב.")

    if task is None and intent.task_text:
        matches = db.scalars(
            select(Task)
            .where(Task.status == "open", Task.title.ilike(f"%{intent.task_text.strip()}%"))
            .order_by(Task.id.desc())
            .limit(5)
        ).all()
        if not matches:
            return Outcome(f'לא מצאתי משימה פתוחה שמתאימה ל"{intent.task_text}".')
        if len(matches) > 1:
            return Outcome(
                "יש כמה משימות שמתאימות. לאיזו התכוונת?\n" + _format_list(db, list(matches)),
                listed_task_ids=[item.id for item in matches],
            )
        task = matches[0]

    if task is None:
        return Outcome("לא הבנתי איזו משימה סיימת.")
    if task.status == "done":
        return Outcome(f"המשימה הזאת כבר מסומנת כבוצעה: {task.title}")

    task.status = "done"
    task.done_at = now()
    db.commit()
    memory.observe(
        "task_done", "bot", task_id=task.id, client_id=task.client_id, detail=task.title
    )
    return Outcome(f"סומן כבוצע: {task.title}", task_id=task.id)


def _list_tasks(db: Session, intent: Intent) -> Outcome:
    stmt = select(Task).where(Task.status == "open")
    heading = "המשימות הפתוחות"
    today = now_local().date()

    if intent.list_filter == "today":
        stmt = stmt.where(Task.due_date <= today)
        heading = "להיום"
    elif intent.list_filter == "overdue":
        stmt = stmt.where(Task.due_date < today)
        heading = "באיחור"
    if intent.client_id:
        stmt = stmt.where(Task.client_id == intent.client_id)
        name = _client_name(db, intent.client_id)
        if name:
            heading += f" · {name}"
    if intent.project_id:
        stmt = stmt.where(Task.project_id == intent.project_id)

    tasks = db.scalars(
        stmt.order_by(Task.due_date.is_(None), Task.due_date, Task.id).limit(LIST_LIMIT)
    ).all()
    if not tasks:
        return Outcome("אין משימות פתוחות.")

    tasks = list(tasks)
    return Outcome(
        f"{heading} ({len(tasks)}):\n" + _format_list(db, tasks),
        listed_task_ids=[item.id for item in tasks],
    )


def _last_bot_task_row(db: Session) -> BotMessage | None:
    """ההודעה האחרונה שבעקבותיה הבוט יצר או עדכן משימה."""
    return db.scalars(
        select(BotMessage)
        .where(
            BotMessage.intent.in_(("add_task", "update_last")),
            BotMessage.task_id.is_not(None),
        )
        .order_by(BotMessage.id.desc())
        .limit(1)
    ).first()


# מה ש"בטל" יודע לבטל: משימה שנוצרה, תיקון שלה, או עובדה שנרשמה בזיכרון
_UNDOABLE = ("add_task", "add_recurring", "update_last", "remember")


def _last_bot_action_row(db: Session) -> BotMessage | None:
    """ההודעה האחרונה שבעקבותיה הבוט שינה משהו — משימה, עובדה או התחייבות.

    דורשת שמשהו אכן נשמר, כי הודעה שנכשלה ("לא הבנתי מה המשימה") לא אמורה
    לחסום את הביטול של מה שנשמר לפניה.
    """
    return db.scalars(
        select(BotMessage)
        .where(
            BotMessage.intent.in_(_UNDOABLE),
            or_(
                BotMessage.task_id.is_not(None),
                BotMessage.fact_id.is_not(None),
                BotMessage.recurrence_id.is_not(None),
            ),
        )
        .order_by(BotMessage.id.desc())
        .limit(1)
    ).first()


def _cancel_last(db: Session) -> Outcome:
    """מבטל את הדבר האחרון שהבוט עשה: משימה, עובדה או התחייבות חוזרת.

    לא נוגע במשימות מהדשבורד — מה שלא נוצר מהבוט לא נמחק ממנו.
    """
    row = _last_bot_action_row(db)
    if not row:
        return Outcome("אין מה לבטל.")
    if row.created_at and now() - aware(row.created_at) > CANCEL_WINDOW:
        return Outcome("עבר יותר מדי זמן מאז השמירה. אפשר למחוק מהדשבורד.")

    if row.fact_id:
        fact = db.get(MemoryFact, row.fact_id)
        if not fact:
            return Outcome("זה כבר לא רשום בזיכרון.")
        content = fact.content
        db.delete(fact)
        db.commit()
        memory.observe("fact_removed", "bot", detail=content)
        return Outcome(f"נמחק מהזיכרון: {content}")

    if row.recurrence_id:
        rec = db.get(Recurrence, row.recurrence_id)
        if not rec:
            return Outcome("ההתחייבות הזאת כבר לא קיימת.")
        title = rec.title
        # המשימה שההתחייבות הספיקה לייצר נמחקת איתה. בלעדיה היא הייתה
        # נשארת ברשימה בלי שיהיה ברור מאיפה היא באה
        for task in db.scalars(
            select(Task).where(Task.recurrence_id == rec.id, Task.status == "open")
        ).all():
            db.delete(task)
        db.delete(rec)
        db.commit()
        memory.observe("recurrence_cancelled", "bot", detail=title)
        return Outcome(f"בוטלה ההתחייבות החוזרת: {title}")

    task = db.get(Task, row.task_id)
    if not task:
        return Outcome("המשימה כבר לא קיימת.")
    if task.source != "whatsapp":
        return Outcome("המשימה הזאת לא נוצרה מהבוט, אז לא אבטל אותה.")

    title = task.title
    db.delete(task)
    db.commit()
    memory.observe("task_cancelled", "bot", detail=title)
    return Outcome(f"בוטל: {title}")


def _remember(db: Session, intent: Intent) -> Outcome:
    """רושם עובדה לזיכרון ארוך-טווח: "תזכור שדני לא עונה לפני עשר".

    הוראה ישירה ממך היא האישור עצמו, ולכן העובדה נכנסת מיד ולא ממתינה
    לאישור בדשבורד. אין כאן הסקה ואין ניחוש: מה שנרשם הוא מה שאמרת, ואפשר
    לבטל מיד או למחוק אחר כך במסך הזיכרון.
    """
    content = " ".join((intent.fact or "").split())[: memory.MAX_CONTENT_CHARS]
    if not content:
        return Outcome("לא הבנתי מה לזכור. אפשר לנסח שוב?")

    # מזהה מומצא היה מפיל את השמירה על מפתח זר ברקע, בלי שתקבל תשובה
    client_id = intent.client_id if intent.client_id and db.get(Client, intent.client_id) else None
    project_id = (
        intent.project_id if intent.project_id and db.get(Project, intent.project_id) else None
    )

    existing = db.scalars(select(MemoryFact).where(MemoryFact.content == content)).first()
    if existing:
        return Outcome("זה כבר רשום אצלי.", fact_id=existing.id)

    dimension = memory.clean_dimension(intent.dimension)
    fact = MemoryFact(
        dimension=dimension,
        client_id=client_id,
        project_id=project_id,
        content=content,
        source="bot",
    )
    db.add(fact)
    db.commit()
    db.refresh(fact)
    memory.observe("fact_added", "bot", client_id=client_id, detail=content)
    return Outcome(
        f"נרשם בזיכרון: {content}\n[{memory.dimension_name(dimension)}]", fact_id=fact.id
    )


# שדות שהם מזהה לרשומה אחרת. מאמתים שהמזהה קיים לפני שכותבים אותו, כי
# מזהה מומצא היה מפיל את העדכון על מפתח זר ברקע, בלי שהמשתמש יקבל תשובה.
_LOOKUP_FIELDS = {
    "domain_id": Domain,
    "task_type_id": TaskType,
    "client_id": Client,
    "project_id": Project,
}


def _update_last(db: Session, intent: Intent) -> Outcome:
    """מתקן את המשימה האחרונה: "בעצם ביום חמישי", "זה דחוף", "תשייך לדני".

    רק שדות שהמודל מילא משתנים. אי אפשר לנקות שדה בדרך הזאת, כי null
    פירושו "לא הוזכר" ולא "למחוק" — ניקוי נעשה בדשבורד.
    """
    row = _last_bot_task_row(db)
    if not row or not row.task_id:
        return Outcome("אין משימה אחרונה לעדכן.")
    if row.created_at and now() - aware(row.created_at) > CANCEL_WINDOW:
        return Outcome("עבר יותר מדי זמן מאז השמירה. אפשר לערוך בדשבורד.")

    task = db.get(Task, row.task_id)
    if not task:
        return Outcome("המשימה כבר לא קיימת.")
    if task.source != "whatsapp":
        return Outcome("המשימה הזאת לא נוצרה מהבוט, אז לא אעדכן אותה.")

    changed = False
    if intent.title:
        task.title = intent.title[:500]
        changed = True
    for field, model in _LOOKUP_FIELDS.items():
        value = getattr(intent, field)
        if value is not None and db.get(model, value) is not None:
            setattr(task, field, value)
            changed = True
    if intent.priority:
        timeframe.set_priority(task, intent.priority)
        changed = True
    if intent.notes:
        task.notes = intent.notes
        changed = True

    due = _parse_due(intent.due_date)
    if due:
        task.due_date = due
        changed = True
    reminder = _parse_reminder(intent.reminder_at)
    if reminder:
        task.reminder_at = reminder
        # תזכורת חדשה צריכה לצאת גם אם הקודמת כבר נשלחה
        task.reminder_sent_at = None
        changed = True

    if not changed:
        return Outcome("לא הבנתי מה לשנות במשימה.")

    db.commit()
    db.refresh(task)
    detail = describe(db, task)
    memory.observe(
        "task_updated", "bot", task_id=task.id, client_id=task.client_id, detail=task.title
    )
    return Outcome(f"עודכן: {task.title}" + (f"\n{detail}" if detail else ""), task_id=task.id)


def execute(db: Session, intent: Intent) -> Outcome:
    if intent.action == "add_task":
        return _add_task(db, intent)
    if intent.action == "add_recurring":
        return _add_recurring(db, intent)
    if intent.action == "complete_task":
        return _complete_task(db, intent)
    if intent.action == "list_tasks":
        return _list_tasks(db, intent)
    if intent.action == "cancel_last":
        return _cancel_last(db)
    if intent.action == "remember":
        return _remember(db, intent)
    if intent.action == "update_last":
        return _update_last(db, intent)
    if intent.action == "clarify":
        return Outcome(intent.question or "לא הבנתי. אפשר לנסח שוב?")
    return Outcome('לא הבנתי. אפשר לכתוב למשל "תזכיר לי מחר ב-10 להתקשר לדני" או "רשימה".')
