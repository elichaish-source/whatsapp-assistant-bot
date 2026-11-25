"""קריאה מהיומן של גוגל: אילו יומנים, ומה יש בהם (שלב 4ב-1).

**המודול הזה אינו יודע שיש בוט**, בדיוק כמו ``gmail.py``: הוא מקבל
``Session`` ומחזיר אובייקטים, ומי שמנסח מהם תשובה בעברית הוא
``bot/events.py``. ההכרעה מ-24.11.2026 היא שהיומן נשאר בבוט ולא עובר
למסך, אבל מסך יומן הוא יכולת מתוכננת — וההפרדה היא מה שיאפשר לו
להשתמש באותן פונקציות בלי שכתוב.

**שום תוכן אירוע אינו נשמר.** האירועים נקראים מגוגל ברגע הבקשה
ונזרקים. בפריסה הזאת אין מיגרציה ואין עמודה חדשה בכלל.

⚠️ **אין כאן שום קריאת מודל.** שעה וכותרת הן עובדות מהיומן, ולכן אין
מה לפענח — אותו שיקול כמו בהתראות של 4-6. זה גם אומר שאין כאן משטח
הזרקה: טקסט שאדם אחר כתב בכותרת אירוע אינו מגיע לשום מודל.

⚠️⚠️ **מזהה יומן חייב קידוד URL.** מזהה יומן החגים הוא
``iw.jewish#holiday@group.v.calendar.google.com``, וה-``#`` בתוכו הופך
את שאר הכתובת לעוגן — גוגל מקבלת נתיב קטוע ומחזירה **404**. ‏404 נראה
כמו "אין יומן כזה" ולא כמו "קודדת לא נכון", ולכן זה בוזבז זמן ב-24.11
עד שהתגלה. ``quote(…, safe="")`` על כל מזהה, בלי יוצא מן הכלל.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from email.utils import parseaddr
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import gauth
from .config import get_settings
from .models import Client

log = logging.getLogger(__name__)

API = "https://www.googleapis.com/calendar/v3"
TIMEOUT = 30

# כמה אירועים נשלפים מיומן אחד בבקשה אחת. ביומן האמיתי היו 17 בשבוע,
# ולכן 250 (התקרה של גוגל) הוא מרחב ולא אופטימיזציה
PAGE = 250

# כמה יומנים נקראים במקביל. קטן בכוונה: שניים-שלושה יומנים בפועל, והמקביליות
# כאן היא כדי ששליפה לא תארך סכום הזמנים — אותו שיקול שהוריד את סריקת
# השרשורים ב-4-6 מ-24 שניות ל-3.4
WORKERS = 4

# ⚠️ יומני החגים והלידים של גוגל יושבים תמיד תחת הדומיין הזה. הם מגיעים
# בהרשאת reader, ולכן הכלל של accessRole כבר מסנן אותם — זאת חגורה שנייה,
# כי יומן חגים שייכנס לתשובה היומית יוסיף שורה כמעט כל שבוע
GENERATED_SUFFIX = "@group.v.calendar.google.com"

# ⚠️ ההכרעה של 24.11.2026: "מה יש לי מחר" עונה על **הראשי והמשפחתי**.
# שניהם בהרשאת owner, וחדר הישיבות והחגים בהרשאת reader — ולכן הכלל
# הזה לבדו מוציא את מה שאינו של המשתמש.
OWNED = ("owner",)


class CalendarError(Exception):
    """היומן לא נגיש כרגע: רשת, או תשובה לא צפויה מגוגל."""


@dataclass
class Calendar:
    """יומן אחד שהמשתמש קורא ממנו."""

    id: str
    name: str
    primary: bool = False


@dataclass
class Event:
    """אירוע אחד, כפי שהוא מוצג. בלי שדה שאינו מוצג למשתמש."""

    id: str
    title: str
    calendar: str
    # ⚠️ **האם האירוע מהיומן הראשי.** נחוץ כי ההכרעה של 24.11.2026 היא
    # לקרוא גם את היומן המשפחתי — ואירוע משפחתי שמופיע בלי סימון נראה
    # כמו פגישת עבודה. "פגישה ב-20:00" בלי הסימון הזה הוא שאלה, לא תשובה
    from_primary: bool = True
    # ⚠️ אירוע של כל היום מגיע כ-``start.date`` ולא ``start.dateTime``, ואין
    # לו שעה בכלל. להמיר אותו ל-00:00 היה מציג "חופשה 00:00" בראש היום
    all_day: bool = False
    start: datetime | None = None
    end: datetime | None = None
    day: date | None = None
    location: str = ""
    attendees: list[str] = field(default_factory=list)

    @property
    def when(self) -> date:
        """באיזה יום האירוע. מאחד את שני המצבים למיון ולקיבוץ."""
        return self.day if self.all_day else self.start.date()  # type: ignore[union-attr]

    @property
    def minutes(self) -> int:
        """אורך האירוע בדקות. אפס לאירוע של כל היום."""
        if self.all_day or not self.start or not self.end:
            return 0
        return int((self.end - self.start).total_seconds() // 60)


def local_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def skipped() -> set[str]:
    """מזהי יומנים שלא נקראים, מ-``CALENDAR_SKIP`` ב-.env.

    ⚠️ **ריק בברירת המחדל, בכוונה.** מזהה יומן הוא נתון של ההתקנה ולא של
    הקוד, ולכן הוא יושב ב-.env כמו ``OWNER_PHONE`` — ולא בקוד במאגר.

    ⚠️ **וכשהוא ריק נקראים כל היומנים שבבעלות המשתמש**, כלומר הכשל הוא
    לכיוון "להציג". זאת אותה הכרעה שנקבעה לסינון המיילים ב-4-2: אירוע
    שנעלם בשקט הוא הכשל היחיד שאסור, ואירוע מיותר הוא רק רעש.
    """
    raw = get_settings().calendar_skip
    return {part.strip() for part in raw.split(",") if part.strip()}


# --- הקריאות לגוגל ---


def _request(token: str, path: str, params: dict | None = None) -> dict:
    """קריאת GET ליומן עם טוקן שכבר ביד.

    ⚠️ **מקבלת טוקן ולא ``Session``, ולכן בטוחה לקריאה מכמה תהליכונים.**
    ‏``Session`` של SQLAlchemy אינו בטוח לשימוש מקביל. זה אותו באג שתוקן
    ב-``gmail._summaries`` וכמעט חזר ב-``_thread_tail`` ב-4-6, ולכן הוא
    נכתב כך מההתחלה ולא אחרי שהוא נשבר.
    """
    try:
        response = httpx.get(
            f"{API}/{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise CalendarError(f"הפנייה ליומן נכשלה: {exc}") from exc

    if response.status_code >= 400:
        log.warning("גוגל החזירה %s על %s", response.status_code, path)
        raise CalendarError(f"גוגל החזירה {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise CalendarError("תשובה לא תקינה מגוגל") from exc


def _path(calendar_id: str, suffix: str = "events") -> str:
    """נתיב ליומן, עם המזהה מקודד.

    ⚠️⚠️ **``safe=""`` הוא העיקר כאן ולא קוסמטיקה.** בלעדיו ``#`` במזהה
    נשאר כמו שהוא, הופך את שאר המזהה לעוגן, וגוגל מחזירה 404 על יומן
    שקיים לגמרי.
    """
    return f"calendars/{quote(calendar_id, safe='')}/{suffix}"


def client_names(db: Session) -> dict[str, str]:
    """כתובת מייל ← שם הלקוח, מכרטיסי הלקוחות.

    ⚠️⚠️ **זה מה שבאמת פותר את שמות המשתתפים.** גוגל מחזירה
    ``displayName`` רק כשהמשתתף הוזן בשם או נמצא באנשי הקשר, ובפלט
    האמיתי של 25.11.2026 היא לא החזירה אותו **לאף אחד** מ-7 המשתתפים
    — כלומר העדפת ``displayName`` נכונה אך אינה מספיקה.

    ⚠️ **בקוד ולא במודל**, בדיוק כמו שיוך הלקוח ב-4-5 וכמו
    ``client_addresses`` בסינון: שם שמוצג למשתמש אינו אמור להיות תלוי
    בשיקול דעת של מודל.
    """
    found: dict[str, str] = {}
    rows = db.execute(select(Client.name, Client.email).where(Client.email.is_not(None))).all()
    for name, value in rows:
        address = parseaddr(str(value))[1].strip().lower()
        if address and name:
            found[address] = str(name).strip()
    return found


def calendars(db: Session) -> list[Calendar]:
    """היומנים שנקראים: בבעלות המשתמש, פחות מה שהוחרג ב-.env.

    ⚠️ **יומן בהרשאת reader אינו נכלל** — חדר הישיבות אינו שלו, ויומן
    החגים היה מוסיף שורה כמעט כל שבוע לתשובה היומית.
    """
    data = _request(gauth.access_token(db), "users/me/calendarList")
    skip = skipped()
    found: list[Calendar] = []
    for item in data.get("items") or []:
        cal_id = item.get("id") or ""
        if not cal_id or cal_id in skip:
            continue
        if item.get("accessRole") not in OWNED:
            continue
        if cal_id.endswith(GENERATED_SUFFIX):
            continue
        found.append(
            Calendar(
                id=cal_id,
                name=item.get("summaryOverride") or item.get("summary") or cal_id,
                primary=bool(item.get("primary")),
            )
        )
    # הראשי קודם, ואחריו לפי שם — כדי שהסדר יהיה קבוע בין הרצות
    found.sort(key=lambda cal: (not cal.primary, cal.name))
    return found


def _parse(raw: dict, calendar_name: str, from_primary: bool = True) -> Event | None:
    """ממיר אירוע של גוגל ל-``Event``. מחזיר None למה שאין מה להציג בו."""
    start, end = raw.get("start") or {}, raw.get("end") or {}
    title = (raw.get("summary") or "").strip() or "(בלי כותרת)"
    attendees = [
        # ⚠️ **השם קודם לכתובת.** התגלה בפלט האמיתי ב-25.11.2026: התשובה
        # הציגה את כתובת המייל של המשתתף במקום את שמו. כתובת גולמית היא
        # פחות קריאה **ופחות שימושית** — צריך לפענח אותה בראש כדי לדעת
        # עם מי הפגישה, וזה בדיוק מה שהשורה אמורה לחסוך
        (person.get("displayName") or "").strip() or person.get("email", "")
        for person in raw.get("attendees") or []
        # ⚠️ המשתמש עצמו אינו "משתתף" בעיני המשתמש. בלי הסינון הזה כל
        # פגישה שהוא ארגן הייתה מוצגת כאילו יש בה אדם אחד יותר
        if person.get("email") and not person.get("self")
    ]
    common = {
        "id": raw.get("id") or "",
        "title": title,
        "calendar": calendar_name,
        "from_primary": from_primary,
        "location": (raw.get("location") or "").strip(),
        "attendees": attendees,
    }

    if start.get("date"):
        try:
            day = date.fromisoformat(start["date"])
        except ValueError:
            return None
        return Event(all_day=True, day=day, **common)

    if not start.get("dateTime"):
        return None
    try:
        begins = datetime.fromisoformat(start["dateTime"])
        finishes = datetime.fromisoformat(end["dateTime"]) if end.get("dateTime") else None
    except ValueError:
        return None
    tz = local_tz()
    return Event(
        start=begins.astimezone(tz),
        end=finishes.astimezone(tz) if finishes else None,
        **common,
    )


def _events(token: str, cal: Calendar, begins: datetime, ends: datetime) -> list[Event]:
    """האירועים של יומן אחד בטווח. ``singleEvents`` פורש התחייבות חוזרת."""
    data = _request(
        token,
        _path(cal.id),
        {
            "timeMin": begins.isoformat(),
            "timeMax": ends.isoformat(),
            # ⚠️ בלי singleEvents, פגישה שבועית חוזרת מוחזרת כהגדרה אחת
            # ולא כמופע בתאריך — ו"מה יש לי מחר" היה מחמיץ אותה
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": PAGE,
        },
    )
    found = [_parse(raw, cal.name, cal.primary) for raw in data.get("items") or []]
    return [event for event in found if event is not None]


def span(scope: str, today: date | None = None) -> tuple[date, date]:
    """הטווח שהמשתמש ביקש, כשני תאריכים כולל.

    ⚠️ "השבוע" הוא שבעה ימים קדימה מהיום ולא "עד שבת". מי ששואל ביום
    חמישי "מה יש לי השבוע" מתכוון לשבוע הקרוב, לא ליומיים שנשארו.
    """
    first = today or datetime.now(tz=local_tz()).date()
    if scope == "tomorrow":
        return first + timedelta(days=1), first + timedelta(days=1)
    if scope == "week":
        return first, first + timedelta(days=6)
    return first, first


def agenda(db: Session, scope: str = "today") -> list[Event]:
    """מה יש בטווח המבוקש, מכל היומנים שנקראים, ממוין לפי זמן.

    ⚠️ **קורא מכמה יומנים ולא רק מהראשי.** כרגע רק הראשי בשימוש בפועל,
    ולכן ההבדל אינו נראה — **אבל ברגע שתיכנס פגישה ליומן המשפחתי, תשובה
    שקוראת רק את הראשי תהיה שגויה בשקט.** זה אותו סוג כשל של
    ``resultSizeEstimate`` ב-4-6: מספר שנראה סביר ואינו נכון.
    """
    cals = calendars(db)
    if not cals:
        return []

    tz = local_tz()
    first, last = span(scope)
    begins = datetime.combine(first, time.min, tzinfo=tz)
    ends = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)

    # ⚠️ הטוקן נשלף **פעם אחת לפני** התהליכונים. ``Session`` אינו בטוח
    # לשימוש מקביל, ושליפה בתוך תהליכון היא בדיוק הבאג של 4-6
    token = gauth.access_token(db)
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(cals))) as pool:
        batches = list(pool.map(lambda cal: _events(token, cal, begins, ends), cals))

    found = [event for batch in batches for event in batch]

    # ⚠️ שמות הלקוחות מוחלפים **אחרי** השליפה ולא בתוך ``_parse``:
    # ‏``_parse`` טהורה ואינה מכירה את המסד, וכך היא נשארת ניתנת לבדיקה
    # בלי בסיס נתונים. שאילתה אחת לכל הסבב, ולא אחת לכל משתתף
    known = client_names(db)
    if known:
        for event in found:
            event.attendees = [known.get(who.lower(), who) for who in event.attendees]

    # אירוע של כל היום ראשון באותו תאריך, ואחריו לפי שעה
    found.sort(key=lambda event: (event.when, not event.all_day, event.start or begins))
    return found
