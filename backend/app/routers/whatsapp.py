"""מסך הוואטסאפ — הבוט בדשבורד (``/whatsapp``).

**למה מסך ולא עוד ערוץ.** העיקרון המנחה שנאמר במפורש ב-26.11.2026:
«כמה שפחות ערוצים שאצטרך לעבוד עליהם במהלך היום. הכול נמצא בדשבורד.»
⚠️⚠️ **«בוט פנימי» אינו מסך נוסף — הוא המסך הזה**: שני מסכים לדבר אחד
הם בדיוק מה שהעיקרון בא למנוע.

**מוח אחד, ערוץ עשיר יותר.** הפענוח והביצוע יושבים ב-``bot/pipeline.py``
ורצים כאן בדיוק כמו בוואטסאפ: סכימת כוונות אחת, קבוצת פעולות אחת,
⚠️ **ואין כאן שום פעולה שקיימת רק במסך**. מה שהמסך מוסיף הוא רינדור —
כפתורים במקום מספרים, רשימה בלי פיצול ל-4096 תווים, וקישור למסך
המיילים — ולכן אינו מכפיל תחזוקה.

⚠️⚠️ **הודעה שנכתבה כאן נענית כאן בלבד ואינה יוצאת בוואטסאפ.** אחרת
וואטסאפ מתמלא בהדים של עבודה שנעשתה במסך. יש בדיקה שתיפול אם מישהו
יוסיף כאן קריאה ל-``waha.send_text``. ⚠️ הכיוון ההפוך נשמר: **הודעה
שהמערכת יוזמת יוצאת בוואטסאפ ומופיעה גם כאן** — זה הנימוק היחיד
שמחזיק לבוט, כי מסך אינו מגיע למי שאינו מולו.

⚠️ **מצב החיבור הוא קריאה בלבד** (בחירת המשתמש, 26.11.2026): הנתיב
מדווח מה WAHA אומרת, ואין כאן איתחול סשן ואין QR.
"""

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import waha
from ..auth import now, require_user
from ..bot import actions, pipeline
from ..db import get_db
from ..models import BotMessage, Task
from ..schemas import (
    BotHistoryOut,
    BotListedTaskOut,
    BotMessageOut,
    BotPendingOut,
    BotSayIn,
    BotStatusOut,
)

log = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/whatsapp", tags=["whatsapp"], dependencies=[Depends(require_user)]
)

# כמה הודעות נטענות בפעם אחת. ⚠️ היסטוריה היא רשימה שגדלה לנצח, ומסך
# שטוען את הכול נעשה איטי יותר בכל יום שעובר
PAGE = 40
# כמה אחורה מחפשים התראות ופעולות שלא אושרו. ⚠️ מה שישן מדי אינו
# "לא טופל" אלא היסטוריה — אותו שיקול של חלון ההתראות ב-4-6
LOOKBACK = timedelta(days=30)
# מה שנחשב "לא הבנתי": הכוונה שהמודל בחר כששאל הבהרה, ותשובת ברירת
# המחדל של ``execute``. ⚠️ זאת לולאת המשוב היחידה שמראה איזה ניסוח
# נכשל — בלעדיה כל כשל כזה נעלם
UNCLEAR_INTENTS = ("clarify",)
UNCLEAR_REPLY = "לא הבנתי"

# מצב הסשן ב-WAHA, מתורגם למה שהמסך מציג
STATES = {
    "WORKING": ("connected", "הבוט מחובר לוואטסאפ ותזכורות יוצאות כרגיל."),
    "SCAN_QR_CODE": (
        "scan",
        "וואטסאפ מחכה לסריקת קוד. עד שזה ייעשה, הודעות יוזמות אינן יוצאות.",
    ),
    "STARTING": ("starting", "הסשן עולה. כדאי לרענן בעוד רגע."),
    "STOPPED": ("failed", "הסשן עצור. הבוט אינו מקבל הודעות ואינו שולח תזכורות."),
    "FAILED": (
        "failed",
        "וואטסאפ ניתקה את השרת. הבוט אינו מקבל הודעות ואינו שולח תזכורות.",
    ),
}
UNREACHABLE = "לא הצלחתי להגיע ל-WAHA בשרת. ⚠️ זה שונה מניתוק — ייתכן שהשירות עצמו אינו רץ."


# --- בניית התשובה למסך ---


def _tasks(db: Session, row: BotMessage) -> list[BotListedTaskOut]:
    """המשימות שהוצגו בשורה, לפי הסדר — הנתון שמאחורי הכפתורים.

    ⚠️ **אין כאן שום דבר חדש מהמודל**: ``listed_task_ids`` היא בדיוק
    העמודה ש-``_resolve_by_number`` קורא כשהמשתמש מקליד "סיימתי 2".
    ⚠️ המספר נשמר ומוצג, כדי שמי שעובר בין המסך לוואטסאפ יראה את אותו
    מספר שהבוט כתב.
    """
    raw = row.listed_task_ids or ""
    ids = [int(part) for part in raw.split(",") if part.strip().isdigit()]
    if not ids:
        return []
    found = {task.id: task for task in db.scalars(select(Task).where(Task.id.in_(ids))).all()}
    out = []
    for index, task_id in enumerate(ids, start=1):
        task = found.get(task_id)
        if task is not None:
            out.append(
                BotListedTaskOut(
                    number=index, id=task.id, title=task.title, status=task.status
                )
            )
    return out


def _pending_question(db: Session, row: BotMessage) -> str | None:
    if not row.pending_json:
        return None
    try:
        summary, _ = actions.describe_pending(db, json.loads(row.pending_json))
    except ValueError:
        return None
    return summary


def _out(db: Session, row: BotMessage) -> BotMessageOut:
    return BotMessageOut(
        id=row.id,
        channel=row.channel,
        initiated=row.initiated,
        body=row.body,
        reply=row.reply,
        intent=row.intent,
        error=row.error,
        created_at=row.created_at,
        handled_at=row.handled_at,
        tasks=_tasks(db, row),
        emails=[part for part in (row.listed_email_ids or "").split(",") if part],
        pending=_pending_question(db, row),
    )


# --- היסטוריה ---


@router.get("/messages", response_model=BotHistoryOut)
def history(
    db: Session = Depends(get_db),
    before: int | None = Query(None, ge=1),
    limit: int = Query(PAGE, ge=1, le=200),
) -> BotHistoryOut:
    """השיחה, **משני הערוצים יחד** — זה כל הרעיון של שיקוף.

    ⚠️ **כל שורה מסומנת באיזה ערוץ נכתבה.** בלי זה המשתמש רואה רשימה
    ממוספרת שהוצגה בוואטסאפ בתוך המסך, ומניח שהמספרים שם תקפים כאן.
    """
    stmt = select(BotMessage).order_by(BotMessage.id.desc()).limit(limit + 1)
    if before is not None:
        stmt = stmt.where(BotMessage.id < before)
    rows = list(db.scalars(stmt).all())
    more = len(rows) > limit
    rows = rows[:limit]
    # מהישן לחדש, כמו צ'אט
    return BotHistoryOut(messages=[_out(db, row) for row in reversed(rows)], more=more)


@router.post("/messages", response_model=BotMessageOut, status_code=201)
def say(body: BotSayIn, db: Session = Depends(get_db)) -> BotMessageOut:
    """הודעה שנכתבה במסך: אותו מוח, ותשובה שאינה יוצאת בוואטסאפ.

    ⚠️ **ההרצה סינכרונית.** בוואטסאפ היא רצה ברקע כי WAHA מנסה שוב
    כשאינה מקבלת 200 מיד; כאן המשתמש מחכה לתשובה מולו.
    """
    text = body.body.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "אין מה לשלוח.")
    row = BotMessage(
        # ⚠️ מזהה מלאכותי: אין כאן הודעה של וואטסאפ. התחילית מבדילה,
        # והייחודיות של העמודה נשמרת
        wa_message_id=_screen_id(),
        channel=actions.SCREEN,
        body=text[:1000],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    pipeline.run(db, row)
    db.refresh(row)
    return _out(db, row)


def _screen_id() -> str:
    return f"screen:{datetime.now():%Y%m%d%H%M%S%f}"


# --- מצב החיבור ---


@router.get("/status", response_model=BotStatusOut)
def connection() -> BotStatusOut:
    """⚠️⚠️ היכולת שחסרה הכי: כשוואטסאפ מנתקת את השרת, היום שום דבר
    אינו אומר זאת והתזכורות פשוט נפסקות. זה קרה ב-2.11.2026."""
    raw = waha.session_status()
    if not raw["status"]:
        return BotStatusOut(state="unreachable", message=UNREACHABLE)
    state, message = STATES.get(
        raw["status"], ("unknown", "מצב שאינני מכיר. כדאי לבדוק בשרת.")
    )
    return BotStatusOut(state=state, raw=raw["status"], phone=raw["phone"], message=message)


# --- התראות שלא טופלו, ומה שהבוט לא הבין ---


def _since() -> datetime:
    return now() - LOOKBACK


@router.get("/alerts", response_model=list[BotMessageOut])
def alerts(db: Session = Depends(get_db)) -> list[BotMessageOut]:
    """הודעות שהמערכת יזמה ולא סומנו כטופלו.

    ⚠️ **«טופל» הוא לחיצה מפורשת שלך ולא ניחוש של המערכת** (הכרעת
    המשתמש, 26.11.2026). תזכורת שיצאה אינה "טופלה" מפני שהמשימה
    עודכנה במקום אחר, והתראה על מייל אינה "טופלה" מפני שמישהו פתח אותו.
    """
    rows = db.scalars(
        select(BotMessage)
        .where(
            BotMessage.initiated.is_(True),
            BotMessage.handled_at.is_(None),
            BotMessage.created_at >= _since(),
        )
        .order_by(BotMessage.id.desc())
        .limit(PAGE)
    ).all()
    return [_out(db, row) for row in rows]


@router.get("/unclear", response_model=list[BotMessageOut])
def unclear(db: Session = Depends(get_db)) -> list[BotMessageOut]:
    """מה שהבוט לא הבין — הניסוחים שנכשלו, משני הערוצים.

    ⚠️ זאת לולאת המשוב היחידה שתגיד איזה ניסוח נכשל; בלעדיה כל כשל
    כזה נעלם בין ההודעות.
    """
    rows = db.scalars(
        select(BotMessage)
        .where(
            BotMessage.initiated.is_(False),
            BotMessage.handled_at.is_(None),
            BotMessage.created_at >= _since(),
            or_(
                BotMessage.intent.in_(UNCLEAR_INTENTS),
                BotMessage.intent.is_(None),
                BotMessage.reply.like(f"{UNCLEAR_REPLY}%"),
            ),
        )
        .order_by(BotMessage.id.desc())
        .limit(PAGE)
    ).all()
    # שורה בלי תשובה בכלל היא הודעה שעדיין רצה ברקע, ולא כשל
    return [_out(db, row) for row in rows if row.reply]


@router.post("/messages/{message_id}/handled", response_model=BotMessageOut)
def mark_handled(message_id: int, db: Session = Depends(get_db)) -> BotMessageOut:
    row = db.get(BotMessage, message_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "אין הודעה כזאת.")
    row.handled_at = now()
    db.commit()
    db.refresh(row)
    return _out(db, row)


# --- פעולות שלא אישרת ---


def _answered(db: Session, row: BotMessage) -> bool:
    """האם ההודעה שאחרי השאלה, באותו ערוץ, הייתה תשובה לה.

    ⚠️ בדיוק אותו כלל של ``_pending``: רק ההודעה שמיד אחרי נחשבת,
    והודעות שהמערכת יזמה אינן נספרות.
    """
    nxt = db.scalars(
        select(BotMessage)
        .where(
            BotMessage.id > row.id,
            BotMessage.channel == row.channel,
            BotMessage.initiated.is_(False),
        )
        .order_by(BotMessage.id)
        .limit(1)
    ).first()
    return nxt is not None and nxt.intent in ("confirm", "decline")


@router.get("/pending", response_model=list[BotPendingOut])
def pending(db: Session = Depends(get_db)) -> list[BotPendingOut]:
    """פעולות שהבוט שאל עליהן ולא קיבלו אישור בזמן.

    ⚠️⚠️ **היום זה מתאדה בשקט**: ביקשת למחוק, לא ענית בתוך רבע שעה,
    ושום דבר לא נמחק ושום דבר לא אמר לך.
    """
    rows = db.scalars(
        select(BotMessage)
        .where(
            BotMessage.pending_json.is_not(None),
            BotMessage.handled_at.is_(None),
            BotMessage.created_at >= _since(),
            BotMessage.created_at <= now() - actions.CONFIRM_WINDOW,
        )
        .order_by(BotMessage.id.desc())
        .limit(PAGE)
    ).all()

    out: list[BotPendingOut] = []
    for row in rows:
        if _answered(db, row):
            continue
        try:
            data = json.loads(row.pending_json or "")
        except ValueError:
            continue
        summary, executable = actions.describe_pending(db, data)
        out.append(
            BotPendingOut(
                id=row.id,
                channel=row.channel,
                created_at=row.created_at,
                question=row.reply or "",
                summary=summary,
                kind=str(data.get("kind") or ""),
                executable=executable,
            )
        )
    return out


@router.post("/pending/{message_id}/confirm", response_model=BotMessageOut, status_code=201)
def confirm(message_id: int, db: Session = Depends(get_db)) -> BotMessageOut:
    """מבצע עכשיו פעולה שלא אושרה בזמן.

    ⚠️⚠️ **מה שמבוצע נקרא מ-``pending_json`` של אותה שורה** ולא ממה
    שהלקוח שלח — בדיוק כמו שאישור בוואטסאפ נאכף בשרת. ⚠️ **הביצוע
    נרשם כהודעה חדשה במסך**, כך שהוא נראה בהיסטוריה ו"בטל" יכול
    להחזיר אותו, ואינו נעשה בשקט.
    """
    row = db.get(BotMessage, message_id)
    if row is None or not row.pending_json:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "אין פעולה כזאת.")
    if row.handled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "הפעולה הזאת כבר טופלה.")
    data = json.loads(row.pending_json)
    summary, executable = actions.describe_pending(db, data)
    if not executable:
        raise HTTPException(status.HTTP_409_CONFLICT, f"אי אפשר לבצע: {summary}")

    outcome = actions.apply_pending(db, data)
    row.handled_at = now()
    done = BotMessage(
        wa_message_id=_screen_id(),
        channel=actions.SCREEN,
        body=summary,
        intent="confirm",
        reply=outcome.reply,
        task_id=outcome.task_id,
        recurrence_id=outcome.recurrence_id,
        undo_json=json.dumps(outcome.undo, ensure_ascii=False) if outcome.undo else None,
    )
    db.add(done)
    db.commit()
    db.refresh(done)
    return _out(db, done)


@router.post("/pending/{message_id}/dismiss", response_model=BotMessageOut)
def dismiss(message_id: int, db: Session = Depends(get_db)) -> BotMessageOut:
    """מסיר מהרשימה בלי לבצע. ⚠️ אינו משנה דבר מלבד הסימון."""
    return mark_handled(message_id, db)
