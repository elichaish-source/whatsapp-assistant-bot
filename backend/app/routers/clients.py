from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import Client, ClientFamily, Project, Task, client_family_links
from ..schemas import ClientIn, ClientOut

router = APIRouter(prefix="/api/clients", tags=["clients"], dependencies=[Depends(require_user)])


def _open_tasks(db: Session, client_ids: list[int]) -> dict[int, int]:
    if not client_ids:
        return {}
    rows = db.execute(
        select(Task.client_id, func.count())
        .where(Task.client_id.in_(client_ids), Task.status == "open")
        .group_by(Task.client_id)
    ).all()
    return dict(rows)


def _out(client: Client, open_tasks: int) -> ClientOut:
    out = ClientOut.model_validate(client)
    out.open_tasks = open_tasks
    return out


def _get(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "לקוח לא נמצא")
    return client


def _apply(db: Session, client: Client, body: ClientIn) -> Client:
    data = body.model_dump(exclude={"family_ids"})
    for key, value in data.items():
        setattr(client, key, value)
    family_ids = set(body.family_ids)
    families = db.scalars(select(ClientFamily).where(ClientFamily.id.in_(family_ids))).all()
    if len(families) != len(family_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "משפחת לקוחות לא קיימת")
    client.families = list(families)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("", response_model=list[ClientOut])
def list_clients(
    family_id: int | None = None,
    is_active: bool | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Client).order_by(Client.name)
    if family_id is not None:
        stmt = stmt.where(
            Client.id.in_(select(client_family_links.c.client_id).where(client_family_links.c.family_id == family_id))
        )
    if is_active is not None:
        stmt = stmt.where(Client.is_active == is_active)
    if q:
        stmt = stmt.where(Client.name.ilike(f"%{q}%"))
    clients = db.scalars(stmt).all()
    counts = _open_tasks(db, [c.id for c in clients])
    return [_out(c, counts.get(c.id, 0)) for c in clients]


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db)):
    client = _get(db, client_id)
    return _out(client, _open_tasks(db, [client.id]).get(client.id, 0))


@router.post("", response_model=ClientOut, status_code=201)
def create_client(body: ClientIn, db: Session = Depends(get_db)):
    return _out(_apply(db, Client(), body), 0)


@router.put("/{client_id}", response_model=ClientOut)
def update_client(client_id: int, body: ClientIn, db: Session = Depends(get_db)):
    client = _apply(db, _get(db, client_id), body)
    return _out(client, _open_tasks(db, [client.id]).get(client.id, 0))


@router.delete("/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db)):
    client = _get(db, client_id)
    tasks = db.scalar(select(func.count()).select_from(Task).where(Task.client_id == client_id))
    projects = db.scalar(select(func.count()).select_from(Project).where(Project.client_id == client_id))
    if tasks or projects:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"ללקוח יש {projects} פרויקטים ו-{tasks} משימות. אפשר לסמן אותו כלא פעיל במקום למחוק.",
        )
    db.delete(client)
    db.commit()
    return {"ok": True}
