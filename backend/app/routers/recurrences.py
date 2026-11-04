"""מסך ההתחייבויות החוזרות בדשבורד: קריאה, הוספה, תיקון ומחיקה.

התאריך הבא ותיאור התדירות מחושבים ואינם עמודות, ולכן הם מתווספים לכל
תשובה כאן. ``open_task_id`` נשלח כדי שהמסך יוכל לומר "המחזור הנוכחי עוד
פתוח" במקום להראות תאריך עתידי ולהשתיק את מה שבאמת מחכה.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import memory, recurring
from ..auth import require_user
from ..db import get_db
from ..models import Client, Domain, Project, Recurrence, Task, TaskType
from ..schemas import RecurrenceIn, RecurrenceOut

router = APIRouter(
    prefix="/api/recurrences", tags=["recurrences"], dependencies=[Depends(require_user)]
)


def _invalid(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


def _check_fields(db: Session, body: RecurrenceIn) -> None:
    """אותם כללי שיוך של משימה — הסיווג כאן עובר לכל מחזור שייווצר."""
    if body.project_id is not None and not db.get(Project, body.project_id):
        raise _invalid("פרויקט לא קיים")
    if body.client_id is not None and not db.get(Client, body.client_id):
        raise _invalid("לקוח לא קיים")
    if body.task_type_id is not None and not db.get(TaskType, body.task_type_id):
        raise _invalid("סוג משימה לא קיים")
    if body.domain_id is not None:
        domain = db.get(Domain, body.domain_id)
        if not domain:
            raise _invalid("תחום לא קיים")
        if domain.requires_client and body.client_id is None:
            raise _invalid(f'בתחום "{domain.name}" חובה לבחור לקוח')


def _out(db: Session, rec: Recurrence) -> RecurrenceOut:
    row = RecurrenceOut.model_validate(rec)
    row.next_due = recurring.next_due(rec)
    row.every = recurring.describe_interval(rec.interval_unit, rec.interval_count)
    row.open_task_id = db.scalars(
        select(Task.id).where(Task.recurrence_id == rec.id, Task.status == "open").limit(1)
    ).first()
    return row


def _get(db: Session, recurrence_id: int) -> Recurrence:
    rec = db.get(Recurrence, recurrence_id)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ההתחייבות לא נמצאה")
    return rec


@router.get("", response_model=list[RecurrenceOut])
def list_recurrences(db: Session = Depends(get_db)) -> list[RecurrenceOut]:
    rows = db.scalars(
        select(Recurrence).order_by(Recurrence.active.desc(), Recurrence.id.desc())
    ).all()
    return [_out(db, rec) for rec in rows]


@router.post("", response_model=RecurrenceOut, status_code=status.HTTP_201_CREATED)
def create_recurrence(body: RecurrenceIn, db: Session = Depends(get_db)) -> RecurrenceOut:
    _check_fields(db, body)
    rec = Recurrence(**body.model_dump(), cycle=0)
    # תאריך התחלה שעבר מדלג למחזור הבא, ולא מייצר משימה באיחור
    recurring.catch_up(rec, recurring.today_local())
    db.add(rec)
    db.commit()
    db.refresh(rec)

    row = _out(db, rec)
    memory.observe(
        "recurrence_created",
        "dashboard",
        client_id=rec.client_id,
        detail=f"{rec.title} · {row.every}",
    )
    return row


@router.put("/{recurrence_id}", response_model=RecurrenceOut)
def update_recurrence(
    recurrence_id: int, body: RecurrenceIn, db: Session = Depends(get_db)
) -> RecurrenceOut:
    rec = _get(db, recurrence_id)
    _check_fields(db, body)

    # מניין המחזורים נמדד מתאריך ההתחלה ומהתדירות. אם אחד מהם השתנה, המניין
    # הישן מצביע על תאריך שרירותי, ולכן הוא מתחיל מחדש מהמחזור הקרוב
    anchor_changed = (
        rec.start_date != body.start_date
        or rec.interval_unit != body.interval_unit
        or rec.interval_count != body.interval_count
    )
    before = f"{rec.title} · {recurring.next_due(rec)}"
    for field, value in body.model_dump().items():
        setattr(rec, field, value)
    if anchor_changed:
        rec.cycle = 0
        recurring.catch_up(rec, recurring.today_local())
    db.commit()
    db.refresh(rec)

    row = _out(db, rec)
    memory.observe(
        "recurrence_updated",
        "dashboard",
        client_id=rec.client_id,
        detail=f"{before} → {rec.title} · {row.next_due}",
    )
    return row


@router.delete("/{recurrence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurrence(recurrence_id: int, db: Session = Depends(get_db)) -> None:
    """מוחק את ההתחייבות. המשימות שהיא יצרה נשארות, כמשימות רגילות.

    זאת הסיבה שיש גם ``active``: כיבוי עוצר את המחזורים הבאים בלי למחוק
    כלום, ומחיקה מוחקת רק את ההתחייבות עצמה ולא את ההיסטוריה שלה.
    """
    rec = _get(db, recurrence_id)
    title, client_id = rec.title, rec.client_id
    db.delete(rec)
    db.commit()
    memory.observe("recurrence_removed", "dashboard", client_id=client_id, detail=title)
