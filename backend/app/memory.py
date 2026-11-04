"""הזיכרון ארוך-הטווח: מה הבוט יודע, ומה הוא ראה.

‏⚠️ **כלל הברזל של השלב הזה: הזיכרון הוא העשרה ולא תלות.** אם הטבלאות ריקות,
אם שאילתה נכשלת או אם הכתיבה ליומן נופלת — המשימות, התזכורות והבוט ממשיכים
לעבוד בדיוק כמו קודם, רק בלי התאמה אישית. לכן כל פונקציה כאן בולעת חריגות
במקום לזרוק אותן, ו-``observe`` כותבת בחיבור נפרד לבסיס הנתונים: כשל ביומן
לא יכול להפיל את הטרנזקציה שבאמת חשובה למשתמש.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Client, MemoryFact, Observation, Project

log = logging.getLogger(__name__)

# תשעת הממדים מ-SPEC-ASSISTANT.md, סעיף 2. העובדה נשמרת עם תווית הממד שלה
# גם כשהממד לא נשלח לבוט, כדי שלא נאבד מידע שהמשתמש ביקש לזכור.
DIMENSIONS: dict[int, str] = {
    1: "אנשים",
    2: "העדפות עבודה",
    3: "סדרי עדיפויות",
    4: "נהלים",
    5: "כללי החלטה",
    6: "סיווג",
    7: "היסטוריה והקשר",
    8: "מה חשוב לדעת",
    9: "קול וסגנון",
}

# הממדים שנכנסים לפרומפט של הבוט בשלב 2ב. אלה שמשרתים ניהול משימות:
# מי זה "דני", מתי להעמיד תזכורת, מה דחוף, ומה סוכם. נהלים (4), סיווג (6),
# מה חשוב לדעת (8) וקול (9) יידרשו רק משלב 3 והלאה, ואין טעם לשלם עליהם היום.
PROMPT_DIMENSIONS = (1, 2, 3, 5, 7)

# תקרה לבלוק שנשלח בכל הודעה. בלי תקרה, זיכרון שמצטבר שנה הופך את כל הודעה
# לפרומפט ענק — וזה מתגלה בחשבון ולא בבדיקות
MAX_PROMPT_FACTS = 60
MAX_FACT_CHARS = 300
MAX_CONTENT_CHARS = 1000

# ממד ברירת המחדל כשהמודל החזיר ממד לא חוקי. 7 נבחר כי "היסטוריה והקשר"
# הוא הסל הרחב, והוא נכנס לפרומפט — כך עובדה לא נעלמת בגלל תווית שגויה
FALLBACK_DIMENSION = 7


def dimension_name(dimension: int) -> str:
    return DIMENSIONS.get(dimension, DIMENSIONS[FALLBACK_DIMENSION])


def clean_dimension(value: int | None) -> int:
    return value if value in DIMENSIONS else FALLBACK_DIMENSION


def _subject(db: Session, fact: MemoryFact) -> str:
    """על מי העובדה, כשהיא לא עליך עצמך."""
    if fact.client_id:
        client = db.get(Client, fact.client_id)
        if client:
            return f" · לקוח {client.name}"
    if fact.project_id:
        project = db.get(Project, fact.project_id)
        if project:
            return f" · פרויקט {project.name}"
    return ""


def build_block(db: Session) -> str:
    """הבלוק שנשלח למודל בכל הודעה. מחרוזת ריקה כשאין זיכרון או בכל כשל.

    נשלף בשאילתה אחת, ולא אחת לממד, כי הוא נקרא בכל הודעה.
    """
    try:
        facts = db.scalars(
            select(MemoryFact)
            .where(MemoryFact.dimension.in_(PROMPT_DIMENSIONS))
            .order_by(MemoryFact.dimension, MemoryFact.id)
            .limit(MAX_PROMPT_FACTS)
        ).all()
    except Exception:  # noqa: BLE001 - כלל הברזל: בלי זיכרון עובדים כרגיל
        log.exception("שליפת הזיכרון נכשלה")
        return ""

    if not facts:
        return ""

    lines = ["מה שאני יודע עליך:"]
    for fact in facts:
        content = " ".join((fact.content or "").split())[:MAX_FACT_CHARS]
        if not content:
            continue
        lines.append(f"[{dimension_name(fact.dimension)}{_subject(db, fact)}] {content}")
    return "\n".join(lines) if len(lines) > 1 else ""


def observe(
    kind: str,
    source: str,
    *,
    task_id: int | None = None,
    client_id: int | None = None,
    detail: str | None = None,
) -> None:
    """רושם אירוע ביומן. לכתיבה בלבד — אף אחד לא קורא אותו בשלב 2ב.

    נכתב בחיבור נפרד ובולע כל חריגה, כדי שרישום ביומן לא יוכל להכשיל את
    הפעולה שהמשתמש ביקש. יומן חסר שורה הוא מטרד, משימה שלא נשמרה היא באג.
    """
    # כל השלבים עטופים, כולל פתיחת החיבור עצמו: כשל כאן לא אמור לטפס
    # חזרה אל הפעולה שהמשתמש ביקש
    db = None
    try:
        db = SessionLocal()
        db.add(
            Observation(
                kind=kind[:40],
                source=source[:20],
                task_id=task_id,
                client_id=client_id,
                detail=detail,
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 - ראה הערת המודול
        log.exception("רישום ליומן האירועים נכשל")
    finally:
        if db is not None:
            # close מגלגל לאחור טרנזקציה פתוחה, אז אין צורך ב-rollback נפרד
            db.close()
