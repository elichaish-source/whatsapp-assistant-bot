from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from ..auth import now, require_user
from ..db import get_db
from ..models import Client, Domain, Project, Task, TaskType
from ..schemas import Priority, TaskIn, TaskOut, TaskStatus, TaskStatusIn

router = APIRouter(prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(require_user)])


def _invalid(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


def resolve_task_fields(db: Session, body: TaskIn) -> dict:
    """מחיל את כללי השיוך של משימה ומחזיר את השדות לשמירה.

    - משימה בפרויקט מקבלת את התחום של הפרויקט אם לא נבחר תחום אחר.
    - משימה בפרויקט של לקוח משויכת תמיד לאותו לקוח.
    - תחום שמחייב לקוח (למשל "לקוחות") לא נשמר בלי לקוח.
    """
    data = body.model_dump()

    if body.project_id is not None:
        project = db.get(Project, body.project_id)
        if not project:
            raise _invalid("פרויקט לא קיים")
        if data["domain_id"] is None:
            data["domain_id"] = project.domain_id
        if project.client_id is not None:
            if data["client_id"] not in (None, project.client_id):
                raise _invalid("הפרויקט שייך ללקוח אחר")
            data["client_id"] = project.client_id

    if data["domain_id"] is None:
        raise _invalid("חובה לבחור תחום")
    domain = db.get(Domain, data["domain_id"])
    if not domain:
        raise _invalid("תחום לא קיים")
    if data["client_id"] is not None and not db.get(Client, data["client_id"]):
        raise _invalid("לקוח לא קיים")
    if domain.requires_client and data["client_id"] is None:
        raise _invalid(f"בתחום \"{domain.name}\" חובה לבחור לקוח")
    if data["task_type_id"] is not None and not db.get(TaskType, data["task_type_id"]):
        raise _invalid("סוג משימה לא קיים")
    return data


def _set_status(task: Task, new_status: str) -> None:
    if new_status == "done" and task.status != "done":
        task.done_at = now()
    elif new_status == "open":
        task.done_at = None
    task.status = new_status


def _get(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "משימה לא נמצאה")
    return task


@router.get("", response_model=list[TaskOut])
def list_tasks(
    status_: TaskStatus | None = Query(default=None, alias="status"),
    domain_id: int | None = None,
    client_id: int | None = None,
    project_id: int | None = None,
    task_type_id: int | None = None,
    priority: Priority | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    priority_rank = case({"high": 0, "normal": 1, "low": 2}, value=Task.priority)
    stmt = select(Task).order_by(
        Task.status.desc(),  # open לפני done
        Task.due_date.is_(None),
        Task.due_date,
        priority_rank,
        Task.id.desc(),
    )
    filters = {
        Task.status: status_,
        Task.domain_id: domain_id,
        Task.client_id: client_id,
        Task.project_id: project_id,
        Task.task_type_id: task_type_id,
        Task.priority: priority,
    }
    for column, value in filters.items():
        if value is not None:
            stmt = stmt.where(column == value)
    if q:
        stmt = stmt.where(Task.title.ilike(f"%{q}%"))
    return db.scalars(stmt).all()


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    return _get(db, task_id)


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskIn, db: Session = Depends(get_db)):
    data = resolve_task_fields(db, body)
    new_status = data.pop("status")
    task = Task(**data, status="open")
    _set_status(task, new_status)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.put("/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskIn, db: Session = Depends(get_db)):
    task = _get(db, task_id)
    data = resolve_task_fields(db, body)
    _set_status(task, data.pop("status"))
    for key, value in data.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/{task_id}/status", response_model=TaskOut)
def set_task_status(task_id: int, body: TaskStatusIn, db: Session = Depends(get_db)):
    task = _get(db, task_id)
    _set_status(task, body.status)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, task_id))
    db.commit()
    return {"ok": True}
