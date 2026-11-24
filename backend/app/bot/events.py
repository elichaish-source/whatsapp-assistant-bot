"""קריאת היומן דרך הבוט: "מה יש לי מחר" (שלב 4ב-1).

השכבה הזאת מנסחת בעברית. **כל מה שנוגע לגוגל — אילו יומנים, פרישת
התחייבות חוזרת, אזורי זמן — יושב ב-``app/gcal.py``** ולא כאן.

⚠️ **היומן נשאר בבוט, בניגוד למיילים** (הוכרע 24.11.2026). ההכרעה
מ-23.11 העבירה את טריאז' המיילים למסך כי 29 מיילים אינם נכנסים להודעת
וואטסאפ — **ויום ביומן הוא שלוש עד חמש שורות ולא 29**, ולכן אותו נימוק
פועל כאן לכיוון ההפוך. ‏17 אירועים בשבוע ו-3 מחר, נמדד מול היומן האמיתי.

⚠️ **אין מספור ואין ``listed_email_ids``.** בפריסה הזאת אין פעולה שאפשר
לעשות על אירוע, ולכן "תראה לי את 2" לא יפנה לשום דבר. מספור שאינו מוביל
לפעולה הוא הבטחה שלא נממש — וגרוע מזה, הוא היה **מאפס את מספור
המשימות** בלי שום תמורה.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from .. import gauth, gcal, gmail
from .actions import Outcome
from .intent import Intent

log = logging.getLogger(__name__)

NOT_CONNECTED = (
    "חשבון הגוגל לא מחובר. אפשר לחבר אותו במסך «הגדרות» בדשבורד, ואז לנסות שוב."
)
DISCONNECTED = "החיבור לגוגל נפסל וצריך לחבר מחדש. זה נעשה במסך «הגדרות» בדשבורד."

# ⚠️ אין כאן "סוף שבוע": בישראל יום שישי הוא יום עבודה חלקי ושבת אינה,
# וגוגל מחזירה את שמות הימים באנגלית. המיפוי נכתב ביד ולא נגזר מ-locale,
# כי locale עברי אינו מותקן בתמונת ה-Python של הקונטיינר
DAYS = ("שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון")


def _ready(db: Session) -> Outcome | None:
    """בודק שיש חיבור לפני שפונים לגוגל, כדי לענות משהו מובן ולא שגיאה."""
    if not gauth.configured():
        return Outcome(NOT_CONNECTED)
    cred = gauth.get_credential(db)
    if cred is None or cred.status != "connected":
        return Outcome(DISCONNECTED if cred else NOT_CONNECTED)
    return None


def _unavailable(exc: Exception) -> Outcome:
    """תקלה בגישה ליומן. ⚠️ אינה מאפסת שום מספור קיים.

    אם הרשת נפלה, רשימת המיילים או המשימות שהבוט שלח לפני רגע עדיין
    תקפה — ו"סיימתי 2" צריך להמשיך לעבוד אחרי שהתקלה חולפת.
    """
    log.warning("גישה ליומן נכשלה: %s", exc)
    return Outcome("לא הצלחתי להגיע ליומן כרגע. אפשר לנסות שוב בעוד רגע.")


# --- ניסוח ---


def day_name(moment: date) -> str:
    """שם היום בעברית. ``weekday()`` מחזיר 0 לשני, ולכן הסדר ב-DAYS כזה."""
    return DAYS[moment.weekday()]


def _heading(scope: str, first: date, today: date) -> str:
    """כותרת הטווח. ⚠️ "מחר" ולא "יום רביעי" כשזה באמת מחר."""
    if scope == "week":
        return "השבוע הקרוב"
    delta = (first - today).days
    if delta == 0:
        return "היום"
    if delta == 1:
        return "מחר"
    return f"יום {day_name(first)}"


def _clock(event: gcal.Event) -> str:
    """השעה, ועד מתי כשיש סיום. ⚠️ אירוע של כל היום אינו מקבל שעה בכלל."""
    if event.all_day:
        return "כל היום"
    assert event.start is not None
    if event.end and event.end.date() == event.start.date():
        return f"{event.start:%H:%M}–{event.end:%H:%M}"
    return f"{event.start:%H:%M}"


def _with(event: gcal.Event) -> str:
    """עם מי. שם אחד במלואו, ומעבר לזה מונה — כדי שהשורה תישאר שורה."""
    if not event.attendees:
        return ""
    if len(event.attendees) == 1:
        return f" · עם {event.attendees[0]}"
    return f" · עם {len(event.attendees)} משתתפים"


def _line(event: gcal.Event) -> str:
    """שורה אחת לאירוע: שעה, כותרת, ואם יש — מקום ומשתתפים."""
    line = f"{_clock(event)} · {event.title}"
    if event.location:
        line += f" · {event.location[:60]}"
    return line + _with(event)


def _format(events: list[gcal.Event], today: date, multi_day: bool) -> str:
    """הרשימה. בטווח של יום אחד בלי כותרות ביניים, ובשבוע מקובץ לפי יום.

    ⚠️ **בלי קיבוץ, שבוע שלם היה נראה כרשימת שעות בלי תאריכים** — בדיוק
    התקלה ש-``gmail._when`` נולד בשבילה ב-19.11, כשסיכום שבועי הציג
    "20:36" ו-"12:29" זה מתחת לזה כאילו הם מאותו יום.
    """
    if not multi_day:
        return "\n".join(_line(event) for event in events)

    blocks: list[str] = []
    current: date | None = None
    for event in events:
        if event.when != current:
            current = event.when
            prefix = "היום" if current == today else f"יום {day_name(current)}"
            blocks.append(f"\n*{prefix}, {current:%d/%m}*")
        blocks.append(_line(event))
    return "\n".join(blocks).strip()


def _count(number: int) -> str:
    """"אירוע אחד" ולא "1 אירועים"."""
    return "אירוע אחד" if number == 1 else f"{number} אירועים"


# --- הפעולה ---


def list_events(db: Session, intent: Intent) -> Outcome:
    """"מה יש לי מחר" — האירועים בטווח שהמשתמש ביקש.

    ⚠️ **אין כאן קריאת מודל.** שעה וכותרת הן עובדות מהיומן, בדיוק כמו
    ההתראות ב-4-6 — ולכן גם אין כאן משטח הזרקה.
    """
    blocked = _ready(db)
    if blocked:
        return blocked

    scope = intent.event_scope or "today"
    try:
        found = gcal.agenda(db, scope)
    except gauth.GoogleDisconnected:
        return Outcome(DISCONNECTED)
    except (gcal.CalendarError, gauth.GoogleError) as exc:
        return _unavailable(exc)

    today = datetime.now(tz=gcal.local_tz()).date()
    first, _ = gcal.span(scope, today)
    heading = _heading(scope, first, today)

    if not found:
        # ⚠️ בלי clear_list: קריאה מהיומן אינה משנה דבר, ואין סיבה
        # שהיא תפיל מספור של משימות או של מיילים
        return Outcome(f"אין לך כלום ביומן {heading}.")

    body = f"{heading} — {_count(len(found))}:\n\n" + _format(
        found, today, multi_day=scope == "week"
    )
    # ⚠️ הפיצול נחוץ גם כאן: שבוע עמוס יכול לעבור 4096 תווים, ווואטסאפ
    # חותכת בשקט. אותו לקח שנרשם ברשימות המיילים ב-4-2
    parts = gmail.split_message(body, max_parts=4)
    return Outcome("\n".join(parts), parts=parts if len(parts) > 1 else None)
