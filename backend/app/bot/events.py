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

import json
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import gauth, gcal, gmail
from . import entities
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
    """שורה אחת לאירוע: שעה, כותרת, ואם יש — יומן, מקום ומשתתפים.

    ⚠️ **שם היומן מופיע רק כשהוא אינו הראשי.** זה נחוץ בגלל ההכרעה לקרוא
    גם את היומן המשפחתי: "פגישה ב-20:00" בלי לדעת מאיזה יומן היא הוא
    שאלה ולא תשובה. על הראשי זה היה רעש בכל שורה.
    """
    line = f"{_clock(event)} · {event.title}"
    if not event.from_primary:
        line += f" ({event.calendar})"
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


# --- קביעת פגישה (4ב-2) ---

# ⚠️ **ההכרעה של 24.11.2026: קובעים מיד, בלי אישור מראש.** אירוע ביומן
# הפיך לגמרי — כמו ארכוב ולא כמו שליחת מייל — ולכן אישור מראש הוא חיכוך
# בלי הגנה. ⚠️ **חוץ ממצב אחד:** כשיש משתתף לזמן, כי ההזמנה שגוגל שולחת
# בשם המשתמש אינה הפיכה.

NO_TIME = (
    "לא הבנתי מתי. אפשר לכתוב למשל «תקבע פגישה עם דני מחר ב-10» "
    "או «פגישה ביום שלישי ב-14:30»."
)
NO_TITLE = "לא הבנתי על מה הפגישה. אפשר לכתוב למשל «פגישה עם דני מחר ב-10»."
UNDO_HINT = "לביטול כתוב «בטל»."


def _when_asked(raw: str) -> datetime | None:
    """ממיר את מה שהמודל החזיר לזמן בשעון ישראל, או None.

    ⚠️ **זמן שאינו זמן יורד, ולא מנוחש.** זה אותו שיקול של ``_valid_date``
    ב-4-5: המודל עלול להחזיר "שלישי" או ``2026-13-45``, **ופגישה שנקבעה
    לזמן הלא נכון בלי שמישהו שם לב גרועה מפגישה שלא נקבעה.**
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    # ⚠️ בלי שעה אין פגישה. "מחר" לבדו הוא חצות, וזה לא מה שהתכוונו
    if len(text) <= 10:
        return None
    tz = gcal.local_tz()
    return moment.replace(tzinfo=tz) if moment.tzinfo is None else moment.astimezone(tz)


def _slot(moment: datetime) -> str:
    """"מחר ב-10:00", או "יום שלישי 01/12 ב-10:00" כשזה רחוק יותר."""
    today = datetime.now(tz=gcal.local_tz()).date()
    delta = (moment.date() - today).days
    if delta == 0:
        day = "היום"
    elif delta == 1:
        day = "מחר"
    else:
        day = f"יום {day_name(moment.date())} {moment:%d/%m}"
    return f"{day} ב-{moment:%H:%M}"


def _busy_lines(ranges: list[tuple[datetime, datetime]]) -> str:
    return "\n".join(f"{start:%H:%M}–{end:%H:%M}" for start, end in ranges[:4])


def _guest(db: Session, said: str) -> tuple[str, str, Outcome | None]:
    """מי לזמן: (שם, כתובת, תשובה שעוצרת).

    ⚠️⚠️ **הכתובת נגזרת בשרת מכרטיס הלקוח ולעולם אינה מגיעה מהמודל** —
    אותו דפוס של 4-4, ומאותה סיבה: כתובת שמודל "זוכר" או משלים עלולה
    לשלוח הזמנה לאדם הלא נכון, וזה אינו הפיך.

    ⚠️ **אין התאמה — אין זימון, והבוט אומר זאת.** ⚠️ **וכמה התאמות —
    שואל ואינו בוחר**, כמו ``update_task``.
    """
    name = (said or "").strip()
    if not name:
        return "", "", None

    found = entities.similar_clients(db, name)
    with_mail = [client for client in found if (client.email or "").strip()]
    if len(with_mail) > 1:
        names = ", ".join(client.name for client in with_mail[:5])
        return name, "", Outcome(f"יש כמה שזה מתאים להם: {names}. על מי מהם מדובר?")
    if not with_mail:
        # ⚠️ קובעים בלי לזמן, ואומרים זאת. לנחש כתובת מהשם הוא בדיוק
        # מה שאסור, ולא לקבוע בכלל היה מעניש את המשתמש על חוסר נתון
        return name, "", None
    return with_mail[0].name, (with_mail[0].email or "").strip(), None


def _check_free(db: Session, begins: datetime, ends: datetime) -> Outcome | None:
    """התנגשות אינה שגיאה אלא שאלה.

    ⚠️ **הבוט אינו קובע על פגישה קיימת ואינו מסרב סתם** — הוא אומר מה
    תפוס ומציע את החלון הפנוי הבא.
    """
    clash = gcal.conflicts(db, begins, ends)
    if not clash:
        return None
    minutes = int((ends - begins).total_seconds() // 60)
    free = gcal.next_free(db, begins, minutes)
    reply = f"{_slot(begins)} תפוס:\n{_busy_lines(clash)}"
    reply += f"\n\nפנוי {_slot(free)}." if free else "\n\nלא מצאתי חלון פנוי בשבוע הקרוב."
    return Outcome(reply + "\nלקבוע שם? או תגיד לי שעה אחרת.")


def _create(db: Session, title: str, begins: datetime, minutes: int, guest: str) -> Outcome:
    """היצירה עצמה, מ-``add_event`` או מ-``confirm``."""
    ends = begins + timedelta(minutes=minutes)
    try:
        made = gcal.create(db, title, begins, ends, [guest] if guest else None)
    except gauth.GoogleDisconnected:
        return Outcome(DISCONNECTED)
    except (gcal.CalendarError, gauth.GoogleError) as exc:
        log.warning("יצירת אירוע נכשלה: %s", exc)
        return Outcome("לא הצלחתי לקבוע את הפגישה כרגע. אפשר לנסות שוב בעוד רגע.")

    reply = f"נקבע: {title}\n{_slot(begins)}–{ends:%H:%M}"
    if made.invited:
        reply += f"\nהזמנה נשלחה ל-{guest}"
    return Outcome(
        f"{reply}\n{UNDO_HINT}",
        undo={"kind": "created_event", "event_id": made.id, "invited": made.invited},
    )


def add_event(db: Session, intent: Intent) -> Outcome:
    """"תקבע פגישה עם דני מחר ב-10"."""
    blocked = _ready(db)
    if blocked:
        return blocked

    title = (intent.title or "").strip()
    begins = _when_asked(intent.event_at)
    if not begins:
        return Outcome(NO_TIME)
    if not title:
        return Outcome(NO_TITLE)

    minutes = intent.event_minutes if intent.event_minutes > 0 else gcal.DEFAULT_MINUTES
    name, guest, stop = _guest(db, intent.event_with)
    if stop:
        return stop

    try:
        clash = _check_free(db, begins, begins + timedelta(minutes=minutes))
    except gauth.GoogleDisconnected:
        return Outcome(DISCONNECTED)
    except (gcal.CalendarError, gauth.GoogleError) as exc:
        return _unavailable(exc)
    if clash:
        return clash

    if guest:
        # ⚠️⚠️ **רק כאן יש אישור מראש, וזאת הסיבה היחידה:** ההזמנה שגוגל
        # שולחת בשם המשתמש אינה הפיכה. הפעולה נשמרת ב-pending_json
        # והיצירה קורית ב-confirm, שנקרא מההודעה הקודמת ולא מהמודל
        return Outcome(
            f"לקבוע «{title}» {_slot(begins)} ולשלוח הזמנה ל-{name} ({guest})?\n"
            "⚠️ הזמנה שיצאה אי אפשר להחזיר. לאישור כתוב «כן».",
            pending={
                "kind": "add_event",
                "data": {
                    "title": title,
                    "at": begins.isoformat(),
                    "minutes": minutes,
                    "guest": guest,
                },
            },
        )

    outcome = _create(db, title, begins, minutes, "")
    if name and not guest:
        # ⚠️ נאמר במפורש ולא נבלע: המשתמש ביקש לזמן, וזה לא קרה
        outcome.reply += f"\n\nלא זימנתי את {name} — אין לו כתובת מייל בכרטיס הלקוח."
    return outcome


def confirmed(db: Session, pending: dict) -> Outcome:
    """"כן" על זימון. ⚠️ ההתנגשות נבדקת שוב, כי היומן יכול היה להשתנות."""
    data = pending.get("data") or {}
    begins = _when_asked(str(data.get("at") or ""))
    if not begins:
        return Outcome("לא הצלחתי לשחזר את מה ששאלתי. אפשר לבקש שוב.")
    minutes = int(data.get("minutes") or gcal.DEFAULT_MINUTES)
    try:
        clash = _check_free(db, begins, begins + timedelta(minutes=minutes))
    except (gcal.CalendarError, gauth.GoogleError, gauth.GoogleDisconnected) as exc:
        return _unavailable(exc)
    if clash:
        return clash
    return _create(db, str(data.get("title") or ""), begins, minutes, str(data.get("guest") or ""))


def undo(db: Session, row, data: dict) -> Outcome:
    """"בטל" על אירוע שנקבע.

    ⚠️ **ההזמנה שיצאה אינה נמחקת מהתיבה של הנמען**, אבל הודעת ביטול כן
    מגיעה אליו וההזמנה מסומנת כמבוטלת. זה הדבר הקרוב ביותר ל"בטל"
    שאפשר, ועדיף על שתיקה.
    """
    if data.get("used"):
        return Outcome("זה כבר בוטל.")
    try:
        existed = gcal.delete_event(db, str(data.get("event_id") or ""), bool(data.get("invited")))
    except (gcal.CalendarError, gauth.GoogleError, gauth.GoogleDisconnected) as exc:
        return _unavailable(exc)

    # ⚠️ מסמנים ולא מרוקנים, כמו ב-entities וב-lists: כך "בטל" שני עונה
    # "זה כבר בוטל" ואינו ממשיך אחורה ומוחק משהו אחר
    row.undo_json = json.dumps({"kind": "created_event", "used": True})
    db.commit()
    if not existed:
        return Outcome("האירוע הזה כבר לא ביומן.")
    reply = "הפגישה בוטלה והוסרה מהיומן."
    if data.get("invited"):
        reply += "\n⚠️ ההזמנה שיצאה נשארת בתיבה של הנמען, אבל הוא קיבל הודעת ביטול."
    return Outcome(reply)
