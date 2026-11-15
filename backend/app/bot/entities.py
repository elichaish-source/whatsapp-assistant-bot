"""לקוחות ופרויקטים דרך הבוט: יצירה, עדכון, וביטול של שניהם (שלב 2ג2ב).

שלושה כללים מחזיקים את הקובץ הזה:

1. השמירה עוברת דרך אותן פונקציות של הדשבורד (save_client, save_project),
   כך שהבוט לא יכול להשאיר לקוח או פרויקט במצב שהדשבורד לא היה מרשה.
2. הבוט לא מוחק טקסט ולא מנקה שדות. הערה חדשה מתווספת לקיימת, ושדה שלא
   הוזכר נשאר כמו שהוא.
3. כל שינוי משאיר אחריו את מה שצריך כדי ש"בטל" יחזיר אותו: מזהה של מה
   שנוצר, או המצב שלפני העדכון. מחיקה של לקוח או פרויקט קיימת כאן רק
   כביטול של יצירה, ורק כל עוד לא שויך אליהם דבר.
"""

from __future__ import annotations

import json
import re
from datetime import date

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import memory
from ..models import (
    BotMessage,
    Client,
    ClientFamily,
    Domain,
    MemoryFact,
    Project,
    Recurrence,
    Task,
)
from ..routers.clients import save_client
from ..routers.projects import save_project
from ..schemas import ClientIn, ProjectIn
from .actions import Outcome, _parse_due
from .intent import Intent

UNDO_HINT = '\nלביטול כתוב "בטל".'


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _append(old: str | None, new: str | None) -> str | None:
    """מוסיף טקסט לקיים, בשורה חדשה. הבוט לא דורס הערות."""
    new = (new or "").strip()
    if not new:
        return old
    if not old:
        return new
    if new in old:
        return old
    return f"{old}\n{new}"


def _new_name(said: str, current: str) -> str:
    """השם החדש, או הנוכחי כשהמודל רק חזר על השם כדי לזהות את הישות.

    ‏⚠️ "הטלפון של דני הוא..." מגיע לפעמים עם name="דני" על לקוח שנקרא
    "דני כהן". בלי הבדיקה הזאת עדכון טלפון היה משנה לו בשקט את השם.
    """
    name = _clean(said)[:200]
    if not name or name_words(name) <= name_words(current):
        return current
    return name


# --- שם דומה ---

# מרכאות וגרשיים נמחקים ("בע"מ" → "בעמ"), ושאר סימני הפיסוק הופכים לרווח
_QUOTES = re.compile("[\"'״׳`]")
_SEPARATORS = re.compile(r"[.,\-–־()/\\]")
# מילים שלא מבדילות בין שני לקוחות
_NOISE = {"בעמ", "ltd", "inc"}


def name_words(name: str) -> frozenset[str]:
    """המילים שמזהות שם, אחרי נרמול. הסדר והפיסוק לא משנים."""
    cleaned = _SEPARATORS.sub(" ", _QUOTES.sub("", name.lower()))
    words = frozenset(cleaned.split())
    return (words - _NOISE) or words


def similar_clients(db: Session, name: str) -> list[Client]:
    """לקוחות קיימים, פעילים או לא, שהשם שלהם מוכל בשם החדש או מכיל אותו.

    ‏⚠️ נעשה כאן ולא במודל. "דני" מול "דני כהן" ו"כהן משה" מול "משה כהן"
    הם כמעט תמיד אותו אדם, ולקוח כפול הוא טעות שמתגלה רק אחרי שהמשימות
    כבר התפזרו בין שניהם.
    """
    target = name_words(name)
    if not target:
        return []
    found = []
    for client in db.scalars(select(Client).order_by(Client.name)).all():
        words = name_words(client.name)
        if words and (words <= target or target <= words):
            found.append(client)
    return found


# --- לקוחות ---


def _client_details(client: Client) -> str:
    parts: list[str] = []
    if client.phone:
        parts.append(f"טלפון {client.phone}")
    if client.email:
        parts.append(f"מייל {client.email}")
    if client.tax_id:
        parts.append(f"ח.פ {client.tax_id}")
    if client.address:
        parts.append(f"כתובת {client.address}")
    if client.families:
        parts.append("משפחה: " + ", ".join(family.name for family in client.families))
    if not client.is_active:
        parts.append("לא פעיל")
    return " · ".join(parts)


def _client_snapshot(client: Client) -> dict:
    return {
        "name": client.name,
        "phone": client.phone,
        "email": client.email,
        "tax_id": client.tax_id,
        "address": client.address,
        "notes": client.notes,
        "is_active": client.is_active,
        "family_ids": sorted(family.id for family in client.families),
    }


def _valid_family(db: Session, family_id: int) -> int:
    return family_id if family_id and db.get(ClientFamily, family_id) else 0


def _create_client(db: Session, data: dict) -> Outcome:
    try:
        body = ClientIn(**data)
        client = save_client(db, Client(), body)
    except ValidationError:
        return Outcome("לא שמרתי: אחד הפרטים ארוך מדי או חסר.")
    except HTTPException as exc:
        return Outcome(f"לא שמרתי: {exc.detail}")

    memory.observe("client_created", "bot", client_id=client.id, detail=client.name)
    details = _client_details(client)
    return Outcome(
        f"נשמר לקוח: {client.name}" + (f"\n{details}" if details else "") + UNDO_HINT,
        undo={"kind": "created_client", "client_id": client.id},
    )


def add_client(db: Session, intent: Intent) -> Outcome:
    name = _clean(intent.name)[:200]
    if not name:
        return Outcome("לא הבנתי מה שם הלקוח. אפשר לנסח שוב?")

    family_id = _valid_family(db, intent.family_id)
    data = {
        "name": name,
        "phone": _clean(intent.phone)[:30],
        "email": _clean(intent.email)[:200],
        "tax_id": _clean(intent.tax_id)[:20],
        "address": _clean(intent.address)[:300],
        "notes": (intent.notes or "").strip(),
        "family_ids": [family_id] if family_id else [],
    }

    similar = similar_clients(db, name)
    if similar:
        names = ", ".join(
            item.name + ("" if item.is_active else " (לא פעיל)") for item in similar[:3]
        )
        return Outcome(
            f'כבר קיים לקוח בשם דומה: {names}.\nליצור בכל זאת את "{name}"?\n'
            'כתוב "כן" ליצירה. כל תשובה אחרת לא יוצרת.',
            pending={"kind": "add_client", "data": data},
        )
    return _create_client(db, data)


def update_client(db: Session, intent: Intent) -> Outcome:
    client = db.get(Client, intent.client_id) if intent.client_id else None
    if client is None:
        return Outcome("לא הבנתי לאיזה לקוח התכוונת. אפשר לכתוב את השם המלא שלו?")

    before = _client_snapshot(client)
    family_id = _valid_family(db, intent.family_id)
    after = {
        "name": _new_name(intent.name, client.name),
        "phone": _clean(intent.phone)[:30] or client.phone,
        "email": _clean(intent.email)[:200] or client.email,
        "tax_id": _clean(intent.tax_id)[:20] or client.tax_id,
        "address": _clean(intent.address)[:300] or client.address,
        "notes": _append(client.notes, intent.notes),
        "is_active": {"yes": True, "no": False}.get(intent.active, client.is_active),
        "family_ids": sorted(set(before["family_ids"]) | ({family_id} if family_id else set())),
    }
    changed = [field for field in before if before[field] != after[field]]
    if not changed:
        return Outcome("לא הבנתי מה לשנות אצל הלקוח.")

    try:
        client = save_client(db, client, ClientIn(**after))
    except ValidationError:
        return Outcome("לא עדכנתי: אחד הפרטים ארוך מדי.")
    except HTTPException as exc:
        return Outcome(f"לא עדכנתי: {exc.detail}")

    labels = {"name": "שם", "phone": "טלפון", "email": "מייל", "tax_id": "ח.פ", "address": "כתובת"}
    parts = [f"{labels[field]}: {after[field]}" for field in labels if field in changed]
    if "notes" in changed:
        parts.append("נוספה הערה")
    if "family_ids" in changed:
        parts.append("משפחה: " + ", ".join(family.name for family in client.families))
    if "is_active" in changed:
        parts.append("סומן כפעיל" if client.is_active else "סומן כלא פעיל")

    reply = f"עודכן לקוח: {client.name}\n" + " · ".join(parts)
    if "is_active" in changed and not client.is_active:
        open_tasks = db.scalar(
            select(func.count()).select_from(Task).where(
                Task.client_id == client.id, Task.status == "open"
            )
        )
        if open_tasks:
            reply += f"\nשים לב: יש לו {open_tasks} משימות פתוחות, והן נשארות."

    memory.observe(
        "client_updated", "bot", client_id=client.id, detail=f"{client.name} · {', '.join(changed)}"
    )
    return Outcome(
        reply + UNDO_HINT,
        undo={"kind": "client", "client_id": client.id, "before": before},
    )


# --- פרויקטים ---


def _project_snapshot(project: Project) -> dict:
    return {
        "name": project.name,
        "domain_id": project.domain_id,
        "client_id": project.client_id,
        "description": project.description,
        "due_date": project.due_date.isoformat() if project.due_date else None,
        "status": project.status,
    }


def _project_details(db: Session, project: Project) -> str:
    parts: list[str] = []
    domain = db.get(Domain, project.domain_id)
    if domain:
        parts.append(f"תחום {domain.name}")
    if project.client_id:
        client = db.get(Client, project.client_id)
        if client:
            parts.append(f"לקוח {client.name}")
    if project.due_date:
        parts.append(f"עד {project.due_date:%d/%m/%Y}")
    if project.status == "done":
        parts.append("הסתיים")
    return " · ".join(parts)


def _create_project(db: Session, data: dict) -> Outcome:
    try:
        body = ProjectIn(**data)
        project = save_project(db, Project(), body)
    except ValidationError:
        return Outcome("לא שמרתי: אחד הפרטים ארוך מדי או חסר.")
    except HTTPException as exc:
        return Outcome(f"לא שמרתי: {exc.detail}")

    memory.observe("project_created", "bot", client_id=project.client_id, detail=project.name)
    details = _project_details(db, project)
    return Outcome(
        f"נשמר פרויקט: {project.name}" + (f"\n{details}" if details else "") + UNDO_HINT,
        undo={"kind": "created_project", "project_id": project.id},
    )


def add_project(db: Session, intent: Intent) -> Outcome:
    name = _clean(intent.name)[:200]
    if not name:
        return Outcome("לא הבנתי מה שם הפרויקט. אפשר לנסח שוב?")

    if intent.client_id and db.get(Client, intent.client_id) is None:
        # מזהה שהמודל המציא. פרויקט בלי הלקוח שהמשתמש ציין הוא טעות שקטה
        return Outcome("לא מצאתי את הלקוח הזה, אז לא פתחתי את הפרויקט.")

    if not intent.domain_id or db.get(Domain, intent.domain_id) is None:
        # פרויקט חייב תחום. המודל בוחר כשאפשר, וכשלא — נשאלת שאלה במקום ניחוש
        domains = db.scalars(select(Domain).order_by(Domain.sort_order, Domain.id)).all()
        names = ", ".join(domain.name for domain in domains)
        return Outcome(f'באיזה תחום הפרויקט "{name}"?\n{names}')

    due = _parse_due(intent.due_date)
    data = {
        "name": name,
        "domain_id": intent.domain_id,
        "client_id": intent.client_id,
        "description": (intent.notes or "").strip(),
        "due_date": due.isoformat() if due else None,
    }

    target = name_words(name)
    twins = [
        project
        for project in db.scalars(select(Project).where(Project.status == "active")).all()
        if name_words(project.name) == target
    ]
    if twins:
        return Outcome(
            f'כבר קיים פרויקט פעיל בשם "{twins[0].name}".\nלפתוח בכל זאת עוד אחד?\n'
            'כתוב "כן" ליצירה. כל תשובה אחרת לא יוצרת.',
            pending={"kind": "add_project", "data": data},
        )
    return _create_project(db, data)


def update_project(db: Session, intent: Intent) -> Outcome:
    project = db.get(Project, intent.project_id) if intent.project_id else None
    if project is None:
        return Outcome("לא הבנתי לאיזה פרויקט התכוונת. אפשר לכתוב את השם המלא שלו?")

    before = _project_snapshot(project)
    due = _parse_due(intent.due_date)
    after = {
        "name": _new_name(intent.name, project.name),
        "domain_id": (
            intent.domain_id
            if intent.domain_id and db.get(Domain, intent.domain_id)
            else project.domain_id
        ),
        "client_id": (
            intent.client_id
            if intent.client_id and db.get(Client, intent.client_id)
            else project.client_id
        ),
        "description": _append(project.description, intent.notes),
        "due_date": due.isoformat() if due else before["due_date"],
        "status": {"yes": "active", "no": "done"}.get(intent.active, project.status),
    }
    changed = [field for field in before if before[field] != after[field]]
    if not changed:
        return Outcome("לא הבנתי מה לשנות בפרויקט.")

    # שינוי לקוח מושך איתו את המשימות של הפרויקט (כלל של הדשבורד). כדי
    # ש"בטל" יחזיר גם אותן, נשמר הלקוח שהיה לכל אחת לפני השינוי
    task_clients: dict[str, int | None] = {}
    if "client_id" in changed and after["client_id"] is not None:
        for task in db.scalars(select(Task).where(Task.project_id == project.id)).all():
            if task.client_id != after["client_id"]:
                task_clients[str(task.id)] = task.client_id

    try:
        project = save_project(db, project, ProjectIn(**after))
    except ValidationError:
        return Outcome("לא עדכנתי: אחד הפרטים ארוך מדי.")
    except HTTPException as exc:
        return Outcome(f"לא עדכנתי: {exc.detail}")

    parts: list[str] = []
    if "name" in changed:
        parts.append(f"שם: {project.name}")
    if "domain_id" in changed:
        domain = db.get(Domain, project.domain_id)
        parts.append(f"תחום: {domain.name if domain else '-'}")
    if "client_id" in changed:
        client = db.get(Client, project.client_id) if project.client_id else None
        parts.append(f"לקוח: {client.name if client else '-'}")
    if "due_date" in changed:
        parts.append(f"עד {project.due_date:%d/%m/%Y}")
    if "description" in changed:
        parts.append("נוסף תיאור")
    if "status" in changed:
        parts.append("נסגר" if project.status == "done" else "נפתח מחדש")

    reply = f"עודכן פרויקט: {project.name}\n" + " · ".join(parts)
    if task_clients:
        reply += f"\n{len(task_clients)} משימות של הפרויקט עברו ללקוח החדש."
    if "status" in changed and project.status == "done":
        open_tasks = db.scalar(
            select(func.count()).select_from(Task).where(
                Task.project_id == project.id, Task.status == "open"
            )
        )
        if open_tasks:
            reply += f"\nשים לב: נשארו בו {open_tasks} משימות פתוחות."

    memory.observe(
        "project_updated",
        "bot",
        client_id=project.client_id,
        detail=f"{project.name} · {', '.join(changed)}",
    )
    return Outcome(
        reply + UNDO_HINT,
        undo={
            "kind": "project",
            "project_id": project.id,
            "before": before,
            "task_clients": task_clients,
        },
    )


# --- אישור של יצירה שנשאלה עליה שאלה ---

CONFIRMABLE = ("add_client", "add_project")


def confirmed(db: Session, pending: dict) -> Outcome:
    """יוצר את מה שנשאל עליו "ליצור בכל זאת?", מתוך הנתונים שנשמרו עם השאלה.

    הנתונים נקראים מהשאלה ולא מהמודל, כמו במחיקת משימה.
    """
    data = pending.get("data") or {}
    if pending.get("kind") == "add_client":
        return _create_client(db, data)
    return _create_project(db, data)


# --- "בטל" ---


def _count(db: Session, model, column, value: int) -> int:
    return db.scalar(select(func.count()).select_from(model).where(column == value)) or 0


def _mark_used(db: Session, row: BotMessage, kind: str) -> None:
    """מסמן שהביטול נעשה, בלי למחוק את הרישום.

    ‏⚠️ לא מרוקנים את undo_json: שורה ריקה הייתה נעלמת מהחיפוש של "הפעולה
    האחרונה", ו"בטל" שני היה ממשיך אחורה ומבטל את הפעולה שלפניה.
    """
    row.undo_json = json.dumps({"kind": kind, "used": True})
    db.commit()


def undo(db: Session, row: BotMessage, data: dict) -> Outcome:
    kind = data.get("kind")
    if data.get("used"):
        return Outcome("זה כבר בוטל.")

    if kind == "created_client":
        client = db.get(Client, data.get("client_id"))
        if client is None:
            return Outcome("הלקוח הזה כבר לא קיים.")
        attached = (
            _count(db, Task, Task.client_id, client.id)
            + _count(db, Project, Project.client_id, client.id)
            + _count(db, Recurrence, Recurrence.client_id, client.id)
            + _count(db, MemoryFact, MemoryFact.client_id, client.id)
        )
        if attached:
            return Outcome(
                f"ללקוח {client.name} כבר משויכים דברים, אז לא אמחק אותו. "
                "אפשר לסמן אותו כלא פעיל."
            )
        name = client.name
        db.delete(client)
        _mark_used(db, row, kind)
        memory.observe("client_removed", "bot", detail=name)
        return Outcome(f"בוטל: הלקוח {name} נמחק.")

    if kind == "created_project":
        project = db.get(Project, data.get("project_id"))
        if project is None:
            return Outcome("הפרויקט הזה כבר לא קיים.")
        attached = (
            _count(db, Task, Task.project_id, project.id)
            + _count(db, Recurrence, Recurrence.project_id, project.id)
            + _count(db, MemoryFact, MemoryFact.project_id, project.id)
        )
        if attached:
            return Outcome(
                f"לפרויקט {project.name} כבר משויכים דברים, אז לא אמחק אותו. "
                "אפשר לסגור אותו."
            )
        name = project.name
        db.delete(project)
        _mark_used(db, row, kind)
        memory.observe("project_removed", "bot", detail=name)
        return Outcome(f"בוטל: הפרויקט {name} נמחק.")

    before = data.get("before") or {}

    if kind == "client":
        client = db.get(Client, data.get("client_id"))
        if client is None:
            return Outcome("הלקוח הזה כבר לא קיים.")
        for field in ("name", "phone", "email", "tax_id", "address", "notes", "is_active"):
            if field in before:
                setattr(client, field, before[field])
        family_ids = before.get("family_ids", [])
        client.families = list(
            db.scalars(select(ClientFamily).where(ClientFamily.id.in_(family_ids))).all()
        )
        _mark_used(db, row, kind)
        db.refresh(client)
        memory.observe("client_update_undone", "bot", client_id=client.id, detail=client.name)
        details = _client_details(client)
        return Outcome(f"בוטל השינוי: {client.name}" + (f"\n{details}" if details else ""))

    if kind == "project":
        project = db.get(Project, data.get("project_id"))
        if project is None:
            return Outcome("הפרויקט הזה כבר לא קיים.")
        for field in ("name", "domain_id", "client_id", "description", "status"):
            if field in before:
                setattr(project, field, before[field])
        if "due_date" in before:
            due = before["due_date"]
            project.due_date = date.fromisoformat(due) if due else None
        # המשימות שעברו ללקוח החדש יחד עם הפרויקט חוזרות ללקוח שהיה להן
        for task_id, client_id in (data.get("task_clients") or {}).items():
            task = db.get(Task, int(task_id))
            if task is not None and task.project_id == project.id:
                task.client_id = client_id
        _mark_used(db, row, kind)
        db.refresh(project)
        memory.observe(
            "project_update_undone", "bot", client_id=project.client_id, detail=project.name
        )
        details = _project_details(db, project)
        return Outcome(f"בוטל השינוי: {project.name}" + (f"\n{details}" if details else ""))

    return Outcome("אין מה לבטל.")
