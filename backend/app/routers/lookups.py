"""הרשימות שניתנות לעריכה: משפחות לקוחות, תחומים וסוגי משימה."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import ClientFamily, Domain, Project, Task, TaskType, client_family_links
from ..schemas import DomainIn, DomainOut, LookupIn, LookupOut

router = APIRouter(prefix="/api", tags=["lookups"], dependencies=[Depends(require_user)])


def _list(db: Session, model):
    return db.scalars(select(model).order_by(model.sort_order, model.id)).all()


def _save(db: Session, obj, data: dict):
    for key, value in data.items():
        setattr(obj, key, value)
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "כבר קיים פריט בשם הזה")
    db.refresh(obj)
    return obj


def _get(db: Session, model, item_id: int):
    obj = db.get(model, item_id)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "לא נמצא")
    return obj


def _delete(db: Session, obj, in_use: int):
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT, f"לא ניתן למחוק: בשימוש ב-{in_use} פריטים")
    db.delete(obj)
    db.commit()
    return {"ok": True}


def _count(db: Session, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


# --- משפחות לקוחות ---


@router.get("/client-families", response_model=list[LookupOut])
def list_families(db: Session = Depends(get_db)):
    return _list(db, ClientFamily)


@router.post("/client-families", response_model=LookupOut, status_code=201)
def create_family(body: LookupIn, db: Session = Depends(get_db)):
    return _save(db, ClientFamily(), body.model_dump())


@router.put("/client-families/{item_id}", response_model=LookupOut)
def update_family(item_id: int, body: LookupIn, db: Session = Depends(get_db)):
    return _save(db, _get(db, ClientFamily, item_id), body.model_dump())


@router.delete("/client-families/{item_id}")
def delete_family(item_id: int, db: Session = Depends(get_db)):
    obj = _get(db, ClientFamily, item_id)
    used = _count(db, select(client_family_links).where(client_family_links.c.family_id == item_id))
    return _delete(db, obj, used)


# --- תחומים ---


@router.get("/domains", response_model=list[DomainOut])
def list_domains(db: Session = Depends(get_db)):
    return _list(db, Domain)


@router.post("/domains", response_model=DomainOut, status_code=201)
def create_domain(body: DomainIn, db: Session = Depends(get_db)):
    return _save(db, Domain(), body.model_dump())


@router.put("/domains/{item_id}", response_model=DomainOut)
def update_domain(item_id: int, body: DomainIn, db: Session = Depends(get_db)):
    return _save(db, _get(db, Domain, item_id), body.model_dump())


@router.delete("/domains/{item_id}")
def delete_domain(item_id: int, db: Session = Depends(get_db)):
    obj = _get(db, Domain, item_id)
    used = _count(db, select(Task.id).where(Task.domain_id == item_id)) + _count(
        db, select(Project.id).where(Project.domain_id == item_id)
    )
    return _delete(db, obj, used)


# --- סוגי משימה ---


@router.get("/task-types", response_model=list[LookupOut])
def list_task_types(db: Session = Depends(get_db)):
    return _list(db, TaskType)


@router.post("/task-types", response_model=LookupOut, status_code=201)
def create_task_type(body: LookupIn, db: Session = Depends(get_db)):
    return _save(db, TaskType(), body.model_dump())


@router.put("/task-types/{item_id}", response_model=LookupOut)
def update_task_type(item_id: int, body: LookupIn, db: Session = Depends(get_db)):
    return _save(db, _get(db, TaskType, item_id), body.model_dump())


@router.delete("/task-types/{item_id}")
def delete_task_type(item_id: int, db: Session = Depends(get_db)):
    obj = _get(db, TaskType, item_id)
    used = _count(db, select(Task.id).where(Task.task_type_id == item_id))
    return _delete(db, obj, used)
