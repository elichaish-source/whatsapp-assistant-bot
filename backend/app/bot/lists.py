"""תחומים, סוגי משימה, והשהיה של התחייבות חוזרת דרך הבוט (שלב 2ג2ג).

אותם עקרונות של entities.py:

1. שם דומה לקיים לא נוצר בלי "כן", ומה שנוצר נקרא מהשאלה ולא מהמודל.
2. "בטל" אחרי יצירה מוחק רק כל עוד לא שויך דבר, ואחרי השהיה או הפעלה
   מחזיר את המצב הקודם.
3. התחייבות חוזרת לא בוחרת לבד מבין כמה שמתאימות.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import memory, recurring
from ..models import BotMessage, Domain, Project, Recurrence, Task, TaskType
from .actions import Outcome, _like, _words
from .entities import UNDO_HINT, _clean, name_words

_LABELS = {Domain: ("תחום", "התחום"), TaskType: ("סוג משימה", "סוג המשימה")}
_KINDS = {"add_domain": Domain, "add_task_type": TaskType}


# --- תחומים וסוגי משימה ---


def _similar(db: Session, model, name: str) -> list:
    """פריטים שהמילים של אחד מהם מוכלות בשני: "שיווק" מול "שיווק ומכירות"."""
    target = name_words(name)
    found = []
    for item in db.scalars(select(model).order_by(model.sort_order, model.id)).all():
        words = name_words(item.name)
        if words and (words <= target or target <= words):
            found.append(item)
    return found


def _create(db: Session, model, data: dict) -> Outcome:
    name = data.get("name", "")
    if db.scalars(select(model).where(func.lower(model.name) == name.lower())).first():
        # הגנה למקרה שבין השאלה ל"כן" נוצר אותו שם בדשבורד
        return Outcome(f"כבר קיים {_LABELS[model][0]} בשם {name}.")

    item = model(name=name)
    item.sort_order = (db.scalar(select(func.max(model.sort_order))) or 0) + 1
    if model is Domain:
        item.requires_client = bool(data.get("requires_client"))
    db.add(item)
    db.commit()
    db.refresh(item)

    kind = "domain" if model is Domain else "task_type"
    memory.observe(f"{kind}_created", "bot", detail=name)
    reply = f"נשמר {_LABELS[model][0]}: {name}"
    if model is Domain and item.requires_client:
        reply += "\nמשימה בתחום הזה תחייב לקוח."
    return Outcome(reply + UNDO_HINT, undo={"kind": f"created_{kind}", "id": item.id})


def _add(db: Session, intent, model) -> Outcome:
    name = _clean(intent.name)[:100]
    label = _LABELS[model][0]
    if not name:
        return Outcome(f"לא הבנתי מה שם ה{label}. אפשר לנסח שוב?")

    similar = _similar(db, model, name)
    if any(item.name.lower() == name.lower() for item in similar):
        return Outcome(f"כבר קיים {label} בשם {name}.")

    data = {"name": name}
    if model is Domain:
        data["requires_client"] = bool(intent.requires_client)
    if similar:
        names = ", ".join(item.name for item in similar[:3])
        kind = "add_domain" if model is Domain else "add_task_type"
        return Outcome(
            f'כבר קיים {label} בשם דומה: {names}.\nליצור בכל זאת את "{name}"?\n'
            'כתוב "כן" ליצירה. כל תשובה אחרת לא יוצרת.',
            pending={"kind": kind, "data": data},
        )
    return _create(db, model, data)


def add_domain(db: Session, intent) -> Outcome:
    return _add(db, intent, Domain)


def add_task_type(db: Session, intent) -> Outcome:
    return _add(db, intent, TaskType)


# --- התחייבות חוזרת: השהיה והפעלה ---


def _find(db: Session, text: str, active: bool) -> list[Recurrence]:
    """התחייבויות במצב המבוקש שכל מילות החיפוש מופיעות בכותרת שלהן.

    אותו חיפוש של משימות: מילה-מילה, ואם אין התאמה — ניסיון שני בלי אות
    השימוש שבראש כל מילה.
    """
    for strip in (False, True):
        words = _words(text, strip)
        if not words:
            return []
        stmt = select(Recurrence).where(Recurrence.active.is_(active))
        for word in words:
            stmt = stmt.where(Recurrence.title.ilike(_like(word), escape="\\"))
        found = db.scalars(stmt.order_by(Recurrence.id.desc()).limit(5)).all()
        if found:
            return list(found)
    return []


def _describe(rec: Recurrence) -> str:
    return f"{rec.title} ({recurring.describe_interval(rec.interval_unit, rec.interval_count)})"


def _set_active(db: Session, intent, active: bool) -> Outcome:
    text = (intent.task_text or intent.title or "").strip()
    if not text:
        return Outcome("לא הבנתי לאיזו התחייבות חוזרת התכוונת.")

    matches = _find(db, text, not active)
    if not matches:
        if _find(db, text, active):
            state = "פעילה" if active else "מושהית"
            return Outcome(f'ההתחייבות "{text}" כבר {state}.')
        return Outcome(f'לא מצאתי התחייבות חוזרת שמתאימה ל"{text}".')
    if len(matches) > 1:
        lines = "\n".join(f"- {_describe(rec)}" for rec in matches)
        return Outcome(f"יש כמה התחייבויות שמתאימות. לאיזו התכוונת?\n{lines}")

    rec = matches[0]
    before = {"active": rec.active, "cycle": rec.cycle}
    rec.active = active
    if active:
        # ‏⚠️ הוכרע על ידי המשתמש: מחזורים שעברו בזמן ההשהיה מדלגים עליהם.
        # בלי זה ההפעלה הייתה מייצרת מיד משימה על מחזור ישן, ואחרי שהיא
        # מסומנת — עוד אחת על כל מחזור שהוחמץ
        recurring.catch_up(rec, recurring.today_local())
    db.commit()
    db.refresh(rec)

    if active:
        memory.observe("recurrence_resumed", "bot", client_id=rec.client_id, detail=rec.title)
        reply = f"הופעלה מחדש: {_describe(rec)}\nהמחזור הבא: {recurring.next_due(rec):%d/%m/%Y}"
    else:
        memory.observe("recurrence_paused", "bot", client_id=rec.client_id, detail=rec.title)
        reply = f"הושהתה: {_describe(rec)}\nלא ייווצרו מחזורים חדשים עד שתחזיר אותה."
        if recurring.has_open_task(db, rec.id):
            reply += "\nהמשימה של המחזור הנוכחי כבר נוצרה, והיא נשארת ברשימה."
    return Outcome(
        reply + UNDO_HINT,
        undo={"kind": "recurrence", "id": rec.id, "before": before},
    )


def pause_recurrence(db: Session, intent) -> Outcome:
    return _set_active(db, intent, False)


def resume_recurrence(db: Session, intent) -> Outcome:
    return _set_active(db, intent, True)


# --- אישור ו"בטל" ---

CONFIRMABLE = tuple(_KINDS)
UNDO_KINDS = ("created_domain", "created_task_type", "recurrence")


def confirmed(db: Session, pending: dict) -> Outcome:
    return _create(db, _KINDS[pending["kind"]], pending.get("data") or {})


def _count(db: Session, column, value: int) -> int:
    return db.scalar(select(func.count()).select_from(column.table).where(column == value)) or 0


def _mark_used(db: Session, row: BotMessage, kind: str) -> None:
    """כמו ב-entities: מסמנים ולא מרוקנים, כדי ש"בטל" שני לא ימשיך אחורה."""
    row.undo_json = json.dumps({"kind": kind, "used": True})
    db.commit()


def undo(db: Session, row: BotMessage, data: dict) -> Outcome:
    kind = data.get("kind")
    if data.get("used"):
        return Outcome("זה כבר בוטל.")

    if kind in ("created_domain", "created_task_type"):
        model = Domain if kind == "created_domain" else TaskType
        label, the = _LABELS[model]
        item = db.get(model, data.get("id"))
        if item is None:
            return Outcome(f"{the} הזה כבר לא קיים.")
        if model is Domain:
            attached = (
                _count(db, Task.domain_id, item.id)
                + _count(db, Project.domain_id, item.id)
                + _count(db, Recurrence.domain_id, item.id)
            )
        else:
            attached = _count(db, Task.task_type_id, item.id) + _count(
                db, Recurrence.task_type_id, item.id
            )
        if attached:
            return Outcome(f"ל{label} {item.name} כבר משויכים דברים, אז לא אמחק אותו.")
        name = item.name
        db.delete(item)
        _mark_used(db, row, kind)
        memory.observe(f"{kind.removeprefix('created_')}_removed", "bot", detail=name)
        return Outcome(f"בוטל: {the} {name} נמחק.")

    if kind == "recurrence":
        rec = db.get(Recurrence, data.get("id"))
        if rec is None:
            return Outcome("ההתחייבות הזאת כבר לא קיימת.")
        before = data.get("before") or {}
        rec.active = before.get("active", rec.active)
        rec.cycle = before.get("cycle", rec.cycle)
        _mark_used(db, row, kind)
        db.refresh(rec)
        state = "פעילה" if rec.active else "מושהית"
        memory.observe("recurrence_toggle_undone", "bot", client_id=rec.client_id, detail=rec.title)
        return Outcome(f"בוטל השינוי: {_describe(rec)} — שוב {state}.")

    return Outcome("אין מה לבטל.")
