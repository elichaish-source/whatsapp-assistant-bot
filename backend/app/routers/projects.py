from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import Client, Domain, Project, Task
from ..schemas import ProjectIn, ProjectOut, ProjectStatus

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[Depends(require_user)])


def _open_tasks(db: Session, project_ids: list[int]) -> dict[int, int]:
    if not project_ids:
        return {}
    rows = db.execute(
        select(Task.project_id, func.count())
        .where(Task.project_id.in_(project_ids), Task.status == "open")
        .group_by(Task.project_id)
    ).all()
    return dict(rows)


def _out(project: Project, open_tasks: int) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    out.open_tasks = open_tasks
    return out


def _get(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "פרויקט לא נמצא")
    return project


def _apply(db: Session, project: Project, body: ProjectIn) -> Project:
    if not db.get(Domain, body.domain_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "תחום לא קיים")
    if body.client_id is not None and not db.get(Client, body.client_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "לקוח לא קיים")
    client_changed = project.id is not None and project.client_id != body.client_id
    for key, value in body.model_dump().items():
        setattr(project, key, value)
    db.add(project)
    if client_changed and body.client_id is not None:
        # משימות בפרויקט של לקוח שייכות תמיד לאותו לקוח
        db.execute(update(Task).where(Task.project_id == project.id).values(client_id=body.client_id))
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(
    client_id: int | None = None,
    domain_id: int | None = None,
    status_: ProjectStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    stmt = select(Project).order_by(Project.status, Project.name)
    if client_id is not None:
        stmt = stmt.where(Project.client_id == client_id)
    if domain_id is not None:
        stmt = stmt.where(Project.domain_id == domain_id)
    if status_ is not None:
        stmt = stmt.where(Project.status == status_)
    projects = db.scalars(stmt).all()
    counts = _open_tasks(db, [p.id for p in projects])
    return [_out(p, counts.get(p.id, 0)) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = _get(db, project_id)
    return _out(project, _open_tasks(db, [project.id]).get(project.id, 0))


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    return _out(_apply(db, Project(), body), 0)


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectIn, db: Session = Depends(get_db)):
    project = _apply(db, _get(db, project_id), body)
    return _out(project, _open_tasks(db, [project.id]).get(project.id, 0))


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = _get(db, project_id)
    tasks = db.scalar(select(func.count()).select_from(Task).where(Task.project_id == project_id))
    if tasks:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"בפרויקט יש {tasks} משימות. אפשר לסמן אותו כהסתיים במקום למחוק.",
        )
    db.delete(project)
    db.commit()
    return {"ok": True}
