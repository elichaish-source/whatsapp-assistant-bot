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

# ⚠️⚠️ **מה שהמסך קורא, והוא רחב יותר מהבוט בכוונה** (הוכרע 25.11.2026,
# ב-4ב-4). חדר הישיבות והחגים מגיעים בהרשאת ``reader``, ובתשובה היומית
# של הבוט הם היו רעש — חג מוסיף שורה כמעט כל שבוע. **בלוח שבועי הם
# דווקא הקשר:** "חמישי חג" ו"החדר תפוס ב-14:00" הם בדיוק מה שמסתכלים
# עליו כשמתכננים. ⚠️ ``CALENDAR_SKIP`` ממשיך לחול גם כאן, ולכן יומן
# "משימות" נשאר בחוץ בשני המסלולים.
READABLE = ("owner", "writer", "reader")

# ⚠️⚠️ **לאן מותר לכתוב, ולמה זה לא אותה רשימה כמו קריאה** (נוסף
# 26.11.2026, כשהמסך קיבל יצירה ועריכה). המסך מציג ארבעה יומנים, ושניים
# מהם מגיעים בהרשאת ``reader`` — חדר הישיבות שאינו של המשתמש, ויומן
# החגים של גוגל. **כפתור "שינוי" על אירוע כזה היה מייצר 403 מגוגל
# בלחיצה**, וגרוע מזה: גרירה שלו הייתה נראית כאילו הצליחה עד הרענון
# הבא. לכן ``writable`` נגזר מההרשאה שגוגל מחזירה, והשרת בודק אותו שוב
# לפני כל כתיבה — **לא מסתמך על כך שהמסך הסתיר את הכפתור.**
WRITABLE = ("owner", "writer")

# ⚠️ **ברירת המחדל ליצירה.** הבוט יוצר ביומן הראשי בלבד; המסך מרשה
# לבחור, אבל רק מתוך ``WRITABLE``
PRIMARY = "primary"

# אורך פגישה כשהמשתמש לא אמר. ⚠️ **נגזר מהיומן האמיתי ולא מניחוש:**
# 11 מתוך 17 הפגישות בשבוע שנמדד הן בנות שעה
DEFAULT_MINUTES = 60

# ⚠️ הגבולות של "חלון פנוי סביר". חלון בשתיים לפנות בוקר הוא תשובה
# נכונה טכנית וחסרת תועלת, ולכן ההצעה מוגבלת לשעות שבהן באמת עובדים
DAY_START = 8
DAY_END = 19
# ברזולוציה של רבע שעה, כדי לא להציע "10:07"
SLOT_MINUTES = 15
# ‏``weekday()`` מחזיר 5 לשבת. הצעה לקבוע בשבת אינה הצעה
SATURDAY = 5


class CalendarError(Exception):
    """היומן לא נגיש כרגע: רשת, או תשובה לא צפויה מגוגל."""


class ReadOnlyCalendar(CalendarError):
    """ניסיון לכתוב ליומן שאין בו הרשאת כתיבה, או שאינו ברשימה.

    ⚠️ **שגיאה נפרדת כי התשובה למשתמש שונה לגמרי.** זה אינו "נסה שוב
    בעוד רגע" — זה מצב שלא ישתנה מעצמו, וחדר הישיבות לעולם לא יהיה
    ניתן לעריכה מכאן.
    """


class EventChanged(CalendarError):
    """האירוע השתנה בגוגל מאז שהמסך קרא אותו (``If-Match`` החזיר 412).

    ⚠️⚠️ **זה בדיוק הסיכון שבגללו המסך היה קריאה בלבד עד 26.11.2026:**
    עריכה של אירוע שהמערכת לא יצרה עלולה לדרוס שינוי של מישהו אחר.
    ‏``If-Match`` הופך את הדריסה השקטה לשגיאה שאפשר להציג.
    """


@dataclass
class Created:
    """האירוע שנוצר. ⚠️ ``invited`` קובע אם "בטל" ישלח הודעת ביטול."""

    id: str
    invited: bool = False


@dataclass
class Calendar:
    """יומן אחד שהמשתמש קורא ממנו."""

    id: str
    name: str
    primary: bool = False
    # ⚠️ **האם מותר לכתוב ליומן הזה** (``owner`` או ``writer``). נגזר
    # מגוגל ולא מניחוש: חדר הישיבות והחגים הם ``reader``
    writable: bool = False


@dataclass
class Event:
    """אירוע אחד, כפי שהוא מוצג.

    ⚠️ **``emails`` אינו מוצג למשתמש וקיים לזיהוי בלבד** (נוסף ב-4ב-3).
    ‏``attendees`` הוא מה שנראה — ושם הלקוח מחליף בו את הכתובת — ולכן
    אי אפשר להשתמש בו לזיהוי: אחרי ההחלפה אין בו כתובת, ולפניה גוגל
    מחזירה בו לפעמים ``displayName``. **זיהוי הולך לפי כתובת.**
    """

    id: str
    title: str
    calendar: str
    # ⚠️ **מזהה היומן, לא השם.** נוסף ב-4ב-4 כדי שהמסך יצבע אירוע לפי
    # היומן שלו: שם יומן הוא טקסט שהמשתמש יכול לשנות בגוגל, והמזהה הוא
    # המפתח היציב. ‏הבוט אינו משתמש בו, והוא אינו מוצג לעולם
    calendar_id: str = ""
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
    # ⚠️ כתובות המשתתפים, באותיות קטנות. לזיהוי בקוד ולא להצגה
    emails: list[str] = field(default_factory=list)
    description: str = ""
    # ⚠️⚠️ **מזהה הסדרה, כשהאירוע הוא מופע של פגישה חוזרת** (נוסף
    # 26.11.2026). ``singleEvents=true`` מחזיר מופעים, ולכן ``id`` הוא
    # של **המופע** — ושינוי לפיו משנה פגישה אחת. **וכמעט כל הפגישות
    # ביומן האמיתי חוזרות**, ולכן "הפגישה הזאת או כל הסדרה" אינו מקרה
    # קצה אלא המקרה הרגיל, ובלי המזהה הזה אי אפשר לענות עליו בכלל
    recurring_id: str = ""
    # ⚠️ חתימת הגרסה של גוגל, ל-``If-Match`` בעדכון. בלעדיה שני מסכים
    # פתוחים דורסים זה את זה בשקט
    etag: str = ""

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


def today_local() -> date:
    """איזה יום היום בשעון של ההתקנה.

    ⚠️ **נקבע בשרת ולא בדפדפן.** המסך מדגיש את עמודת היום, ודפדפן
    באזור זמן אחר היה מדגיש את העמודה הלא נכונה — שגיאה שקטה שאי אפשר
    לראות בבדיקה מקומית, כי המחשב במשרד יושב באותו אזור זמן.
    """
    return datetime.now(tz=local_tz()).date()


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


def calendars(db: Session, owned_only: bool = True) -> list[Calendar]:
    """היומנים שנקראים, פחות מה שהוחרג ב-.env.

    ⚠️ **ברירת המחדל היא מה שהבוט קורא: בבעלות המשתמש בלבד.** יומן
    בהרשאת reader אינו נכלל — חדר הישיבות אינו שלו, ויומן החגים היה
    מוסיף שורה כמעט כל שבוע לתשובה היומית.

    ⚠️⚠️ **``owned_only=False`` הוא המסך ולא הבוט** (4ב-4). הוא מרחיב
    ל-``READABLE`` וגם מבטל את ההחרגה של יומני גוגל המיוצרים, כי יומן
    החגים **הוא** אחד מהם. הברירה נשארה ברירת מחדל ולא נהפכה, כדי
    שהתנהגות הבוט שאומתה מול היומן האמיתי ב-25.11 לא תשתנה בשקט —
    אותו שיקול שכתב את ``window`` עם טווח במקום ``scope``.
    """
    data = _request(gauth.access_token(db), "users/me/calendarList")
    skip = skipped()
    allowed = OWNED if owned_only else READABLE
    found: list[Calendar] = []
    for item in data.get("items") or []:
        cal_id = item.get("id") or ""
        if not cal_id or cal_id in skip:
            continue
        if item.get("accessRole") not in allowed:
            continue
        if owned_only and cal_id.endswith(GENERATED_SUFFIX):
            continue
        found.append(
            Calendar(
                id=cal_id,
                name=item.get("summaryOverride") or item.get("summary") or cal_id,
                primary=bool(item.get("primary")),
                writable=item.get("accessRole") in WRITABLE,
            )
        )
    # הראשי קודם, ואחריו לפי שם — כדי שהסדר יהיה קבוע בין הרצות
    found.sort(key=lambda cal: (not cal.primary, cal.name))
    return found


def _parse(
    raw: dict, calendar_name: str, from_primary: bool = True, calendar_id: str = ""
) -> Event | None:
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
    # ⚠️ הכתובות בנפרד מהשמות המוצגים, לזיהוי הלקוח ב-4ב-3. אותו סינון
    # של ``self``, כדי שפגישה שהמשתמש ארגן לא תזוהה לפי הכתובת שלו עצמו
    emails = [
        parseaddr(person.get("email", ""))[1].strip().lower()
        for person in raw.get("attendees") or []
        if person.get("email") and not person.get("self")
    ]
    common = {
        "id": raw.get("id") or "",
        "title": title,
        "calendar": calendar_name,
        "calendar_id": calendar_id,
        "from_primary": from_primary,
        "location": (raw.get("location") or "").strip(),
        "attendees": attendees,
        "emails": [address for address in emails if address],
        "description": (raw.get("description") or "").strip(),
        "recurring_id": str(raw.get("recurringEventId") or ""),
        "etag": str(raw.get("etag") or ""),
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
    found = [_parse(raw, cal.name, cal.primary, cal.id) for raw in data.get("items") or []]
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


def window(
    db: Session, begins: datetime, ends: datetime, owned_only: bool = True
) -> list[Event]:
    """מה יש בין שתי נקודות זמן, מכל היומנים שנקראים, ממוין לפי זמן.

    ⚠️ **קורא מכמה יומנים ולא רק מהראשי.** כרגע רק הראשי בשימוש בפועל,
    ולכן ההבדל אינו נראה — **אבל ברגע שתיכנס פגישה ליומן המשפחתי, תשובה
    שקוראת רק את הראשי תהיה שגויה בשקט.** זה אותו סוג כשל של
    ``resultSizeEstimate`` ב-4-6: מספר שנראה סביר ואינו נכון.

    ⚠️ **מקבל זמנים ולא ``scope``** (פוצל ב-4ב-3): התדריך צריך "מהרגע
    הזה ועד 45 דקות קדימה", וטווח כזה אינו יום ואינו שבוע. ``agenda``
    נשארה העטיפה שממירה ``scope`` לזמנים.

    ⚠️ ``owned_only=False`` מוסיף את היומנים בהרשאת קריאה — המסך ולא
    הבוט (4ב-4). עובר הלאה ל-``calendars`` ואינו משנה דבר אחר.
    """
    cals = calendars(db, owned_only)
    if not cals:
        return []

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


def agenda(db: Session, scope: str = "today") -> list[Event]:
    """מה יש בטווח שהמשתמש ביקש: היום, מחר או השבוע."""
    tz = local_tz()
    first, last = span(scope)
    return window(
        db,
        datetime.combine(first, time.min, tzinfo=tz),
        datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz),
    )


def day_range(db: Session, first: date, days: int, owned_only: bool = True) -> list[Event]:
    """האירועים ב-``days`` ימים שמתחילים ב-``first``, לפי שעון מקומי.

    ⚠️ **מקבל תאריך התחלה ולא ``scope``, וזה מה שהמסך צריך.** הבוט עונה
    על "היום" ו"מחר", ואילו לוח שבועי צריך לדפדף אחורה וקדימה — שבוע
    שאינו השבוע הזה אינו ``scope`` כלל. ``agenda`` נשארה כפי שהייתה,
    ולכן התנהגות הבוט שאומתה מול היומן האמיתי אינה נוגעת בזה.

    ⚠️ **גבולות היום נבנים כ-``datetime`` ולא מחושבים משעות.** זה אותו
    לקח שנרשם ב-4ב-2, כשבדיקה על ``finish.hour`` הפכה 23:00 לחלון פנוי:
    יום נגמר בחצות של **היום הבא**, ולא בשעה 24 של היום הזה.
    """
    tz = local_tz()
    return window(
        db,
        datetime.combine(first, time.min, tzinfo=tz),
        datetime.combine(first + timedelta(days=days), time.min, tzinfo=tz),
        owned_only,
    )


def last_meeting_with(
    db: Session, addresses: set[str], before: datetime, days: int = 90
) -> Event | None:
    """הפגישה האחרונה שהייתה עם אחת הכתובות האלה, לפני ``before``.

    ⚠️ **זיהוי לפי כתובת ולא לפי שם** — ``Event.emails`` ולא
    ``attendees``: גוגל מחזירה ``displayName`` רק לפעמים, וב-4ב-1 נמדד
    שהיא לא החזירה אותו לאף אחד מ-7 המשתתפים.

    ⚠️ **חלון של 90 יום, ולא "מאז ומתמיד".** פגישה מלפני שנה אינה
    "הפעם הקודמת" במובן שמעניין לפני פגישה, והטווח גם חוסם שליפה שתגדל
    בלי גבול. ``None`` פירושו "לא נמצאה", ולא "אין נתונים".
    """
    if not addresses:
        return None
    found = [
        event
        for event in window(db, before - timedelta(days=days), before)
        if not event.all_day
        and event.start is not None
        and event.start < before
        and addresses & set(event.emails)
    ]
    if not found:
        return None
    return max(found, key=lambda event: event.start)  # type: ignore[arg-type,return-value]


# --- בדיקת התנגשות ---
#
# ⚠️ ``freeBusy`` הוא POST שאינו כותב דבר: הוא מקבל טווח ורשימת יומנים
# ומחזיר טווחי "תפוס" בלבד, **בלי כותרות ובלי משתתפים**. הוא עובד עם
# ``calendar.readonly`` שכבר מאושרת, ולכן בדיקת התנגשות אינה פיצ'ר נפרד
# אלא חלק מהקביעה — אין סיבה לקבוע פגישה בלי לבדוק.


def busy(db: Session, begins: datetime, ends: datetime) -> list[tuple[datetime, datetime]]:
    """טווחי "תפוס" בכל היומנים שנקראים, ממוינים לפי זמן."""
    cals = calendars(db)
    if not cals:
        return []
    token = gauth.access_token(db)
    try:
        response = httpx.post(
            f"{API}/freeBusy",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "timeMin": begins.isoformat(),
                "timeMax": ends.isoformat(),
                "items": [{"id": cal.id} for cal in cals],
            },
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise CalendarError(f"הפנייה ליומן נכשלה: {exc}") from exc
    if response.status_code >= 400:
        log.warning("גוגל החזירה %s על freeBusy", response.status_code)
        raise CalendarError(f"גוגל החזירה {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise CalendarError("תשובה לא תקינה מגוגל") from exc

    tz = local_tz()
    found: list[tuple[datetime, datetime]] = []
    for entry in (data.get("calendars") or {}).values():
        for slot in entry.get("busy") or []:
            try:
                start = datetime.fromisoformat(slot["start"]).astimezone(tz)
                end = datetime.fromisoformat(slot["end"]).astimezone(tz)
            except (KeyError, ValueError):
                continue
            found.append((start, end))
    found.sort()
    return found


def conflicts(db: Session, begins: datetime, ends: datetime) -> list[tuple[datetime, datetime]]:
    """מה תפוס בתוך הטווח המבוקש.

    ⚠️ **חפיפה ולא הכלה:** פגישה שמתחילה לפני ונגמרת בתוך הטווח היא
    התנגשות בדיוק כמו אחת שיושבת בתוכו. ``start < ends and end > begins``
    הוא התנאי היחיד שתופס את כל ארבעת המצבים.
    """
    return [(start, end) for start, end in busy(db, begins, ends) if start < ends and end > begins]


def next_free(
    db: Session, after: datetime, minutes: int, days: int = 7
) -> datetime | None:
    """ההתחלה הפנויה הבאה באורך המבוקש, בשעות שבהן כבר יש פגישות.

    ⚠️ **מוגבל ל-``DAY_START``–``DAY_END``**: חלון פנוי בשתיים לפנות בוקר
    הוא תשובה נכונה טכנית וחסרת תועלת. ⚠️ **ומדלג על שבת** — הצעה לקבוע
    בשבת אינה הצעה.
    """
    tz = local_tz()
    step = timedelta(minutes=SLOT_MINUTES)
    length = timedelta(minutes=minutes)
    limit = after + timedelta(days=days)
    taken = busy(db, after, limit)

    def opens(day: date) -> datetime:
        return datetime.combine(day, time(hour=DAY_START), tzinfo=tz)

    def closes(day: date) -> datetime:
        return datetime.combine(day, time(hour=DAY_END), tzinfo=tz)

    moment = after.astimezone(tz).replace(second=0, microsecond=0)
    # מעגלים לרבע שעה הבאה, כדי לא להציע 10:07
    moment += timedelta(minutes=(-moment.minute) % SLOT_MINUTES)

    while moment < limit:
        # ⚠️⚠️ **הגבולות נשמרים כזמנים ולא כשעות.** בגרסה הראשונה הבדיקה
        # הייתה על ``finish.hour``, ובקשה ב-23:00 נתנה סיום ב-00:00 —
        # ‏`0 > 19` הוא False, ולכן **23:00 נראה כחלון פנוי תקין.**
        # נתפס בבדיקה שנכתבה בדיוק בשביל זה
        if moment < opens(moment.date()):
            moment = opens(moment.date())
            continue
        if moment >= closes(moment.date()) or moment.weekday() == SATURDAY:
            moment = opens(moment.date() + timedelta(days=1))
            continue
        finish = moment + length
        if finish > closes(moment.date()):
            moment = opens(moment.date() + timedelta(days=1))
            continue
        if not any(start < finish and end > moment for start, end in taken):
            return moment
        moment += step
    return None


# --- יצירה, שינוי ומחיקה ---


def writable_id(db: Session, calendar_id: str = "") -> str:
    """מאמת שמותר לכתוב ליומן המבוקש, ומחזיר את המזהה לשימוש.

    ⚠️⚠️ **הבדיקה בשרת, ולא בכך שהמסך הסתיר את הכפתור.** המסך מציג גם
    את חדר הישיבות ואת יומן החגים, שניהם בהרשאת ``reader``; בקשה אפשר
    לשלוח גם בלי המסך, ומה שגוגל הייתה מחזירה הוא 403 גולמי — שנראה
    למשתמש כתקלה ולא כאיסור.
    """
    wanted = (calendar_id or "").strip()
    if not wanted or wanted == PRIMARY:
        return PRIMARY
    for cal in calendars(db, owned_only=False):
        if cal.id != wanted:
            continue
        if not cal.writable:
            raise ReadOnlyCalendar(f"אין הרשאת כתיבה ליומן {cal.name}")
        return cal.id
    raise ReadOnlyCalendar("היומן המבוקש אינו ברשימת היומנים")


def _guests(attendees: list[str] | None) -> list[str]:
    """כתובות המשתתפים, בלי ריקים.

    ⚠️⚠️ ``.strip()`` **ולא רק** ``if address``. מחרוזת של רווחים היא
    truthy בפייתון, ולכן בלעדיו ``[" "]`` היה מדליק ``sendUpdates="all"``
    ושולח הזמנה לכתובת ריקה — **פעולה שאינה הפיכה, על קלט זבל.**
    """
    return [address.strip() for address in (attendees or []) if address and address.strip()]


def create(
    db: Session,
    title: str,
    begins: datetime,
    ends: datetime,
    attendees: list[str] | None = None,
    calendar_id: str = PRIMARY,
    location: str = "",
    description: str = "",
    notify: bool = True,
) -> Created:
    """יוצר אירוע. ⚠️ מזמין משתתפים רק אם נמסרו במפורש.

    ⚠️⚠️ **``sendUpdates`` הוא הגבול היחיד כאן שאינו הפיך.** כשיש
    משתתפים גוגל שולחת מייל **בשם המשתמש**, ומחיקת האירוע לא מוציאה את
    ההזמנה מהתיבה של הנמען. לכן ``"all"`` רק כשיש משתתפים, ו-``"none"``
    אחרת — ויש בדיקה שאוכפת את שתי הצורות.

    ⚠️ **ברירת המחדל היא היומן הראשי**, וזה מה שהבוט עושה. המסך רשאי
    לבקש יומן אחר, אבל ``writable_id`` מוודא שמותר לכתוב אליו — חדר
    הישיבות והחגים נפסלים שם.

    ⚠️⚠️ **``notify`` אינו נוחות אלא אישור.** גוגל שולחת את ההזמנה
    **בשם המשתמש**, ומחיקת האירוע לא מוציאה אותה מהתיבה של הנמען. הבוט
    מגיע לכאן רק אחרי אישור מפורש, והמסך שואל לפני השמירה — ולכן
    ``notify=False`` מוסיף משתתפים **בלי** לשלוח להם דבר.
    """
    guests = _guests(attendees)
    target = writable_id(db, calendar_id)
    body: dict = {
        "summary": title,
        "start": {"dateTime": begins.isoformat(), "timeZone": str(local_tz())},
        "end": {"dateTime": ends.isoformat(), "timeZone": str(local_tz())},
    }
    if location.strip():
        body["location"] = location.strip()
    if description.strip():
        body["description"] = description.strip()
    if guests:
        body["attendees"] = [{"email": address} for address in guests]

    token = gauth.access_token(db)
    try:
        response = httpx.post(
            f"{API}/{_path(target)}",
            headers={"Authorization": f"Bearer {token}"},
            params={"sendUpdates": "all" if guests and notify else "none"},
            json=body,
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise CalendarError(f"הפנייה ליומן נכשלה: {exc}") from exc
    if response.status_code >= 400:
        log.warning("יצירת אירוע נכשלה: %s", response.status_code)
        raise CalendarError(f"גוגל החזירה {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise CalendarError("תשובה לא תקינה מגוגל") from exc
    return Created(id=str(data.get("id") or ""), invited=bool(guests))


def delete_event(
    db: Session, event_id: str, invited: bool = False, calendar_id: str = PRIMARY
) -> bool:
    """מוחק אירוע. מחזיר False אם הוא כבר לא קיים.

    ⚠️ **מזהה של מופע מוחק פגישה אחת; מזהה של סדרה מוחק את כולה.**
    מי שבוחר ביניהם הוא הקורא, אחרי ששאל את המשתמש — כאן אין ניחוש.

    ⚠️ **``sendUpdates="all"`` כשהיו משתתפים.** ההזמנה שיצאה אינה נמחקת
    מהתיבה של הנמען, אבל הודעת ביטול כן מגיעה אליו וההזמנה מסומנת
    כמבוטלת — זה הדבר הקרוב ביותר ל"בטל" שאפשר, ועדיף על שתיקה.
    """
    token = gauth.access_token(db)
    target = writable_id(db, calendar_id)
    try:
        response = httpx.delete(
            f"{API}/{_path(target)}/{quote(event_id, safe='')}",
            headers={"Authorization": f"Bearer {token}"},
            params={"sendUpdates": "all" if invited else "none"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise CalendarError(f"הפנייה ליומן נכשלה: {exc}") from exc
    if response.status_code in (404, 410):
        return False
    if response.status_code >= 400:
        log.warning("מחיקת אירוע נכשלה: %s", response.status_code)
        raise CalendarError(f"גוגל החזירה {response.status_code}")
    return True


def update_event(
    db: Session,
    event_id: str,
    calendar_id: str = PRIMARY,
    *,
    title: str | None = None,
    begins: datetime | None = None,
    ends: datetime | None = None,
    location: str | None = None,
    description: str | None = None,
    attendees: list[str] | None = None,
    notify: bool = False,
    etag: str = "",
) -> Event | None:
    """משנה אירוע קיים. מחזיר אותו אחרי השינוי, או None אם אינו קיים.

    ⚠️⚠️ **``PATCH`` ולא ``PUT``, וזה הגבול שנשאר סגור.** ‏``PUT`` מחליף
    את המשאב כולו, ולכן כל שדה שלא נשלח **נמחק בשקט** — כלל החזרה של
    פגישה חוזרת, התזכורות, קישור ה-Meet וההגדרות שהמשתמש קבע ביד.
    ‏``PATCH`` נוגע רק במה שנשלח. יש בדיקה שתיפול אם מישהו יוסיף
    ``httpx.put``, והיא לא נפתחה ב-26.11.2026 אלא צומצמה בכוונה.

    ⚠️⚠️ **``event_id`` של מופע משנה פגישה אחת; של סדרה משנה את כולן.**
    ‏``singleEvents=true`` מחזיר מופעים, וכמעט כל הפגישות ביומן האמיתי
    חוזרות — ולכן זו השאלה הראשונה שנשאלת, ולא ברירת מחדל שקטה.

    ⚠️ **``If-Match`` עם ה-etag.** אם מישהו אחר שינה את האירוע מאז
    שהמסך קרא אותו, גוגל מחזירה 412 ואנחנו מרימים ``EventChanged``
    במקום לדרוס. זה בדיוק הסיכון שבגללו המסך היה קריאה בלבד.

    ⚠️ **``None`` הוא "לא נגעת" ו-``""`` הוא "לרוקן".** בלי ההבחנה הזאת
    עדכון שעה בלבד היה מוחק את המקום ואת התיאור.
    """
    target = writable_id(db, calendar_id)
    body: dict = {}
    if title is not None and title.strip():
        body["summary"] = title.strip()
    if begins is not None:
        body["start"] = {"dateTime": begins.isoformat(), "timeZone": str(local_tz())}
    if ends is not None:
        body["end"] = {"dateTime": ends.isoformat(), "timeZone": str(local_tz())}
    if location is not None:
        body["location"] = location.strip()
    if description is not None:
        body["description"] = description.strip()
    guests: list[str] = []
    if attendees is not None:
        guests = _guests(attendees)
        body["attendees"] = [{"email": address} for address in guests]
    if not body:
        return None

    headers = {"Authorization": f"Bearer {gauth.access_token(db)}"}
    if etag.strip():
        headers["If-Match"] = etag.strip()
    try:
        response = httpx.patch(
            f"{API}/{_path(target)}/{quote(event_id, safe='')}",
            headers=headers,
            # ⚠️ הזמנה יוצאת רק כשהתבקשה **וגם** יש למי לשלוח. שינוי
            # שעה של פגישה עם משתתפים מודיע להם — וזה רצוי — אבל רק
            # אחרי שהמשתמש אישר במסך
            params={"sendUpdates": "all" if notify and guests else "none"},
            json=body,
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise CalendarError(f"הפנייה ליומן נכשלה: {exc}") from exc
    if response.status_code in (404, 410):
        return None
    if response.status_code == 412:
        raise EventChanged("האירוע השתנה בגוגל מאז שהמסך קרא אותו")
    if response.status_code >= 400:
        log.warning("עדכון אירוע נכשל: %s", response.status_code)
        raise CalendarError(f"גוגל החזירה {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise CalendarError("תשובה לא תקינה מגוגל") from exc
    return _parse(data, "", target == PRIMARY, target)


def one_event(db: Session, event_id: str, calendar_id: str = PRIMARY) -> Event | None:
    """אירוע אחד לפי מזהה, כדי לדעת מה באמת שם לפני שמשנים.

    ⚠️ **השרת אינו סומך על מה שהמסך מספר לו.** המזהה של הסדרה, ה-etag
    והמשתתפים הקיימים נקראים מגוגל, אחרת בקשה מזויפת הייתה יכולה
    להצהיר "זה מופע של סדרה" ולשנות פגישות שלא נראו.
    """
    name = ""
    primary = calendar_id in ("", PRIMARY)
    for cal in calendars(db, owned_only=False):
        if cal.id == calendar_id:
            name, primary = cal.name, cal.primary
            break
    raw = _request(
        gauth.access_token(db),
        f"{_path(calendar_id or PRIMARY)}/{quote(event_id, safe='')}",
    )
    return _parse(raw, name, primary, calendar_id or PRIMARY)
