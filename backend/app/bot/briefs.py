"""התדריך לפני פגישה (שלב 4ב-3).

‏45 דקות לפני פגישה שיש עליה מה לומר, הבוט שולח הודעה אחת: מה פתוח מול
הלקוח, מתי נפגשתם לאחרונה ומה נסגר מאז, ומה שביקשת לזכור עליו.

⚠️⚠️ **"מה דובר בפעם הקודמת" אינו נשמר באף מקום, ולכן אינו נאמר כאן.**
אין תמלול פגישות ואין סיכום פגישה, וכתיבת "דובר על X" הייתה המצאה.
מה שכן קיים זה **מתי** הייתה הפגישה הקודמת ומה **נסגר** מאז — שתי
עובדות מהיומן ומהמסד. זה פחות ממה שנשמע באפיון של 2.11, וזה מה שאמת.

⚠️⚠️ **אין כאן שום קריאת מודל**, בדיוק כמו ב-4ב-1 וב-4-6: משימה פתוחה,
תאריך יעד ועובדה שהמשתמש ביקש לזכור הן עובדות מהמסד, ואין מה לפענח בהן.
זה אומר גם ש**אין כאן משטח הזרקה** — כותרת של אירוע שאדם אחר כתב אינה
מגיעה לשום מודל. יש בדיקה שאוכפת זאת.

⚠️ **"רק כשיש מה לומר" (הוכרע 25.11.2026).** פגישה בלי לקוח מזוהה, או
עם לקוח שאין עליו כלום, **אינה מייצרת הודעה** — את השעה והכותרת המשתמש
רואה ביומן בעצמו, והודעה ריקה היא בדיוק מה שמלמד להתעלם מההודעות.

⚠️ **התדריך הוא הודעה יוזמת, ולכן מגיע בלי צליל** עד שהבוט יעבור למספר
וואטסאפ משלו — אותה התנגשות שנרשמה ב-4-6, והמשתמש בחר במודע לבנות בכל
זאת.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from email.utils import parseaddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import gcal, memory, waha
from ..config import get_settings
from ..models import Client, EventBrief, MemoryFact, Task
from .entities import name_words

log = logging.getLogger(__name__)

PREFIX = "לפני הפגישה"

# ⚠️ **תקרה לסבב.** שלוש פגישות רצופות הן מצב אמיתי, אבל היכולת הזאת
# שולחת הודעות שהמשתמש לא ביקש — ותקרה היא ההגנה שנרשמה כלקח ב-4-6,
# אחרי ש-22 התראות היו יוצאות ברצף
PER_RUN = 3

# כמה משימות פתוחות מוצגות בשמן. מעבר לזה מונה — הודעה שנגללת היא
# הודעה שלא נקראת, וזה אותו שיקול של ``_with`` ב-4ב-1
MAX_TASKS = 3
# כמה עובדות מהזיכרון. שתיים כי העובדות ארוכות מכותרת משימה
MAX_FACTS = 2
# ההערות מכרטיס הלקוח הן טקסט חופשי שאין לו גבול, ולכן נחתכות
MAX_NOTES = 200


def _brief_minutes() -> int:
    """כמה דקות לפני הפגישה. הוכרע 45, וניתן לשינוי ב-.env."""
    value = get_settings().brief_minutes
    return value if 1 <= value <= 24 * 60 else 45


# --- זיהוי הלקוח ---


def _by_address(db: Session, event: gcal.Event) -> Client | None:
    """הלקוח לפי כתובת של משתתף מול ``clients.email``.

    ⚠️ **בקוד ולא במודל**, אותו דפוס של שיוך הלקוח ב-4-5 ושל
    ``gcal.client_names``: תדריך על הלקוח הלא נכון גרוע מאין תדריך.

    ⚠️ **מחזיר את השורה ולא מחפש לפי שם.** ``gcal.client_names`` מחזיר
    כתובת ← **שם**, ושם לקוח אינו ייחודי בסכימה — חיפוש חוזר לפיו היה
    יכול להחזיר לקוח אחר עם אותו שם.
    """
    wanted = {address for address in event.emails if address}
    if not wanted:
        return None
    rows = db.scalars(
        select(Client).where(Client.email.is_not(None)).order_by(Client.id)
    ).all()
    for row in rows:
        address = parseaddr(str(row.email))[1].strip().lower()
        if address and address in wanted:
            return row
    return None


def _by_title(db: Session, event: gcal.Event) -> Client | None:
    """הלקוח לפי שמו בכותרת האירוע, כשאין משתתף שזוהה.

    ⚠️⚠️ **רץ רק כשהזיהוי לפי כתובת לא מצא כלום**, וזה מה שהופך אותו
    לבטוח: הוא יכול רק להפוך "לא נמצא" ל"נמצא", ולא לדרוס זיהוי טוב
    יותר. אותו דפוס סבבים של ``_find_open`` ב-2ג2א.

    ⚠️ **ולמה הוא נחוץ:** מול היומן האמיתי רק 5 מתוך 17 הפגישות היו עם
    משתתפים. בלי הסבב הזה התדריך היה קיים כמעט רק לפגישות שהבוט עצמו
    קבע. ⚠️ **נדרשת התאמה מלאה של כל מילות שם הלקוח**, ולא מילה אחת,
    ו**מינימום ארבע אותיות לשם** — אחרת "בנק" או "ברק" היו מתאימים
    לחצי היומן.
    """
    words = name_words(event.title)
    if not words:
        return None
    for client in db.scalars(select(Client).order_by(Client.name)).all():
        target = name_words(client.name)
        if not target or len("".join(target)) < 4:
            continue
        if target <= words:
            return client
    return None


def client_for(db: Session, event: gcal.Event) -> Client | None:
    """על איזה לקוח הפגישה. ``None`` = אין תדריך."""
    return _by_address(db, event) or _by_title(db, event)


# --- מה יש לומר ---


def _open_tasks(db: Session, client_id: int) -> list[Task]:
    """המשימות הפתוחות מול הלקוח, הדחופות קודם."""
    return list(
        db.scalars(
            select(Task)
            .where(Task.status == "open", Task.client_id == client_id)
            .order_by(Task.due_date.is_(None), Task.due_date, Task.id)
        ).all()
    )


def _closed_since(db: Session, client_id: int, since: datetime) -> int:
    """כמה משימות נסגרו מול הלקוח מאז הפגישה הקודמת."""
    return len(
        db.scalars(
            select(Task.id).where(
                Task.client_id == client_id,
                Task.status == "done",
                Task.done_at.is_not(None),
                Task.done_at >= since,
            )
        ).all()
    )


def _facts(db: Session, client_id: int) -> list[str]:
    """העובדות שהמשתמש ביקש לזכור על הלקוח הזה."""
    rows = db.scalars(
        select(MemoryFact)
        .where(MemoryFact.client_id == client_id)
        .order_by(MemoryFact.id.desc())
        .limit(MAX_FACTS)
    ).all()
    return [" ".join((fact.content or "").split()) for fact in rows if fact.content]


def compose(
    db: Session, event: gcal.Event, client: Client, previous: gcal.Event | None
) -> str:
    """התדריך כטקסט. מחרוזת ריקה = אין מה לומר, ולכן אין הודעה.

    ⚠️ **הכותרת והשעה נכנסות רק אחרי שיש מה לומר** — הן ההקשר של
    התדריך, לא התדריך עצמו.
    """
    tasks = _open_tasks(db, client.id)
    facts = _facts(db, client.id)
    notes = " ".join((client.notes or "").split())[:MAX_NOTES]
    if not tasks and not facts and not notes and previous is None:
        return ""

    assert event.start is not None
    head = f"{PREFIX} {event.start:%H:%M} — {event.title}"
    lines = [head, f"לקוח: {client.name}"]

    if tasks:
        lines.append(f"פתוח מולו: {len(tasks)}")
        for task in tasks[:MAX_TASKS]:
            due = f" (עד {task.due_date:%d/%m})" if task.due_date else ""
            lines.append(f"• {task.title}{due}")
        if len(tasks) > MAX_TASKS:
            lines.append(f"• ועוד {len(tasks) - MAX_TASKS}")
    else:
        lines.append("אין משימות פתוחות מולו.")

    if previous is not None and previous.start is not None:
        # ⚠️ **"נפגשתם" ולא "דובר על":** מה דובר אינו נשמר באף מקום
        said = f"הפגישה הקודמת: {previous.start:%d/%m}"
        closed = _closed_since(db, client.id, previous.start)
        if closed == 1:
            said += ", ומאז נסגרה משימה אחת"
        elif closed:
            said += f", ומאז נסגרו {closed} משימות"
        lines.append(said + ".")

    lines.extend(f"זכור: {fact}" for fact in facts)
    if notes:
        lines.append(f"מהכרטיס: {notes}")
    return "\n".join(lines)


# --- השליחה ---


def _briefed(db: Session, event_id: str) -> bool:
    return (
        db.scalars(select(EventBrief.id).where(EventBrief.event_id == event_id)).first()
        is not None
    )


def due_events(db: Session, moment: datetime) -> list[gcal.Event]:
    """הפגישות שהתדריך שלהן אמור לצאת עכשיו.

    ⚠️ **רק מה שעוד לא התחיל.** תדריך לפגישה שכבר רצה אינו תדריך, ולכן
    פגישה שהתחילה בזמן שהשרת היה כבוי אינה מקבלת הודעה מאוחרת — אותו
    שיקול של ``STALE_AFTER`` בתזכורות.

    ⚠️ **אירוע של כל היום אינו פגישה** ואין לו שעה להתכונן אליה.
    """
    begins = moment
    ends = moment + timedelta(minutes=_brief_minutes())
    found = gcal.window(db, begins, ends)
    return [
        event
        for event in found
        if not event.all_day
        and event.start is not None
        and begins <= event.start <= ends
        and event.id
    ]


def send_briefs(
    db: Session,
    moment: datetime | None = None,
    ring: Callable[[str], None] | None = None,
) -> int:
    """שולח את התדריכים שהגיע זמנם, ומחזיר כמה יצאו.

    ⚠️⚠️ **תדריך אחד לכל פגישה, אי פעם** — ``event_briefs``. בלי זה הוא
    היה יוצא בכל סבב של הלולאה בתוך אותן 45 דקות.

    ⚠️ **המסד מסומן רק אחרי שהוואטסאפ הצליח.** תקלת רשת לא תגרום
    לפגישה לאבד את התדריך שלה, והסבב הבא ינסה שוב.

    ⚠️ **``ring`` מגיע מבחוץ ולא מיובא.** הפעמון יושב ב-``reminders``,
    ולייבא אותו לכאן היה יוצר ייבוא מעגלי — ובלי להעביר אותו, התדריך
    היה ההודעה היוזמת היחידה בלי פעמון אם הפוש יופעל אי פעם.
    """
    moment = moment or datetime.now(tz=gcal.local_tz())
    phone = get_settings().owner_phone
    if not phone:
        return 0

    sent = 0
    for event in due_events(db, moment):
        if sent >= PER_RUN:
            break
        if _briefed(db, event.id):
            continue
        client = client_for(db, event)
        if client is None:
            continue
        previous = None
        if event.emails:
            try:
                previous = gcal.last_meeting_with(db, set(event.emails), moment)
            except gcal.CalendarError:
                # ⚠️ הפגישה הקודמת היא העשרה: בלעדיה התדריך עדיין נשלח
                log.warning("שליפת הפגישה הקודמת נכשלה")
        text = compose(db, event, client, previous)
        if not text:
            continue
        try:
            waha.send_text(phone, text)
        except waha.WahaError:
            log.exception("שליחת תדריך לפגישה נכשלה")
            continue
        sent += 1
        db.add(EventBrief(event_id=event.id, briefed_at=moment))
        db.commit()
        # ⚠️ **בלי ``detail``.** כותרת האירוע היא תוכן יומן, והיומן אינו
        # משוקף למסד — מזהה הלקוח והזמן מספיקים ללמידה של 6ב. יש בדיקה
        # שעוברת על כל העמודות הטקסטואליות ותיפול אם תוכן ייכנס לכאן
        memory.observe("brief_sent", "bot", client_id=client.id)
        if ring is not None:
            ring(text)

    if sent:
        log.info("נשלחו %d תדריכים", sent)
    return sent
