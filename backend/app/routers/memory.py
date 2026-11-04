"""מסך "מה הוא יודע עליי": קריאה, עריכה ומחיקה של הזיכרון.

כל עובדה גלויה וניתנת לעריכה, וזה לא פינוק אלא תנאי לאמון: מערכת שלומדת
בלי שאפשר לראות מה למדה — אי אפשר לדעת למה היא עשתה מה שעשתה.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..memory import DIMENSIONS, PROMPT_DIMENSIONS, build_block, dimension_name, observe
from ..models import Client, MemoryFact, Project
from ..schemas import DimensionOut, MemoryFactIn, MemoryFactOut

router = APIRouter(prefix="/api/memory", tags=["memory"], dependencies=[Depends(require_user)])


def _get(db: Session, fact_id: int) -> MemoryFact:
    fact = db.get(MemoryFact, fact_id)
    if not fact:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "העובדה לא נמצאה")
    return fact


def _check_subject(db: Session, body: MemoryFactIn) -> None:
    if body.client_id is not None and not db.get(Client, body.client_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "לקוח לא קיים")
    if body.project_id is not None and not db.get(Project, body.project_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "פרויקט לא קיים")


@router.get("/dimensions", response_model=list[DimensionOut])
def list_dimensions():
    """תשעת הממדים, ומי מהם נשלח לבוט כרגע. הדשבורד לא מקודד אותם אצלו."""
    return [
        DimensionOut(id=key, name=name, in_prompt=key in PROMPT_DIMENSIONS)
        for key, name in DIMENSIONS.items()
    ]


@router.get("/block")
def get_block(db: Session = Depends(get_db)) -> dict:
    """הבלוק המדויק שהבוט מקבל בכל הודעה, כמו שהוא."""
    return {"block": build_block(db)}


@router.get("/facts", response_model=list[MemoryFactOut])
def list_facts(dimension: int | None = None, db: Session = Depends(get_db)):
    stmt = select(MemoryFact).order_by(MemoryFact.dimension, MemoryFact.id.desc())
    if dimension is not None:
        stmt = stmt.where(MemoryFact.dimension == dimension)
    return db.scalars(stmt).all()


@router.post("/facts", response_model=MemoryFactOut, status_code=201)
def create_fact(body: MemoryFactIn, db: Session = Depends(get_db)):
    _check_subject(db, body)
    fact = MemoryFact(**body.model_dump(), source="dashboard")
    db.add(fact)
    db.commit()
    db.refresh(fact)
    observe("fact_added", "dashboard", client_id=fact.client_id, detail=fact.content)
    return fact


@router.put("/facts/{fact_id}", response_model=MemoryFactOut)
def update_fact(fact_id: int, body: MemoryFactIn, db: Session = Depends(get_db)):
    fact = _get(db, fact_id)
    _check_subject(db, body)
    before = fact.content
    for key, value in body.model_dump().items():
        setattr(fact, key, value)
    db.commit()
    db.refresh(fact)
    observe(
        "fact_updated",
        "dashboard",
        client_id=fact.client_id,
        detail=f"{before} → {fact.content}",
    )
    return fact


@router.delete("/facts/{fact_id}")
def delete_fact(fact_id: int, db: Session = Depends(get_db)) -> dict:
    """מחיקה אמיתית. מה שנמחק נרשם ביומן, אז האות ללמידה לא נאבד."""
    fact = _get(db, fact_id)
    content, client_id, dimension = fact.content, fact.client_id, fact.dimension
    db.delete(fact)
    db.commit()
    observe(
        "fact_removed",
        "dashboard",
        client_id=client_id,
        detail=f"[{dimension_name(dimension)}] {content}",
    )
    return {"ok": True}
