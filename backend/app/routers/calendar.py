"""מסך היומן בדשבורד — קריאה בלבד (שלב 4ב-4).

**למה מסך בנוסף לבוט, ולא במקומו.** ההכרעה מ-23.11.2026 העבירה את
טריאז' המיילים מהבוט למסך, כי 29 מיילים אינם נכנסים להודעת וואטסאפ.
⚠️ **ביומן הנימוק פועל לכיוון ההפוך** — יום הוא שלוש עד חמש שורות ולא
29 — ולכן ההכרעה מ-24.11 השאירה את היומן בבוט. **המסך אינו מחליף
אותו:** "מה יש לי מחר" נשאר התשובה הנוחה, והלוח השבועי הוא מה שהבוט
אינו יכול לתת — תמונת שבוע שרואים בבת אחת, עם החורים בין הפגישות.

⚠️⚠️ **היה קריאה בלבד, ומ-26.11.2026 יש בו גם יצירה, שינוי ומחיקה.**
ההכרעה מ-25.11 הייתה קריאה בלבד; המשתמש היפך אותה ביודעין, אחרי שהוצג
לו ששינוי אירוע שהמערכת לא יצרה עלול לדרוס פגישה שמישהו אחר קבע. מה
שבא במקום האיסור הגורף הן ארבע הגנות צרות, וכל אחת מהן נשברה פעם
במקום אחר בפרויקט:

1. ⚠️ **``PUT`` נשאר אסור, ורק ``PATCH`` נפתח.** ‏``PUT`` מחליף את
   המשאב כולו, ולכן שדה שלא נשלח נמחק בשקט — כלל החזרה של פגישה
   חוזרת, התזכורות וקישור ה-Meet. הבדיקה על ``httpx.put`` לא בוטלה.
2. ⚠️⚠️ **"הפגישה הזאת" מול "כל הסדרה" נשאל ואינו מונח.** ‏כמעט כל
   הפגישות ביומן האמיתי חוזרות, ולכן זה המקרה הרגיל ולא הקצה.
3. ⚠️ **``If-Match`` עם ה-etag.** מי ששינה את האירוע בגוגל בינתיים
   מקבל 409 ולא דריסה שקטה.
4. ⚠️ **``writable`` נבדק בשרת.** חדר הישיבות והחגים הם ``reader``,
   והאיסור אינו נשען על כך שהמסך הסתיר את הכפתור.

⚠️⚠️ **זימון משתתפים הוא הפעולה היחידה כאן שאינה הפיכה.** גוגל שולחת
את ההזמנה **בשם המשתמש**, ומחיקת האירוע אינה מוציאה אותה מהתיבה של
הנמען. לכן ``notify`` הוא False כברירת מחדל: משתתף נוסף בלי שנשלח לו
דבר, אלא אם המשתמש אישר במסך במפורש.

⚠️⚠️ **המסך קורא יותר יומנים מהבוט, וזאת הכרעה ולא פשרה.** הבוט עונה
על הראשי והמשפחתי בלבד, כי חג היה מוסיף שורה כמעט בכל תשובה יומית.
המסך קורא גם את חדר הישיבות ואת החגים (``owned_only=False``), כי בלוח
שבועי הם הקשר ולא רעש. ⚠️ ``CALENDAR_SKIP`` חל על שניהם, ולכן יומן
"משימות" של גוגל נשאר בחוץ בשני המסלולים.

⚠️ **אין כאן שום קריאת מודל.** שעה וכותרת הן עובדות מהיומן, בניגוד
למסך המיילים שבו המודל הזול מסווג — ולכן **אין כאן משטח הזרקה** בכלל:
כותרת אירוע שאדם אחר כתב אינה מגיעה לאף מודל. שתי בדיקות אוכפות זאת,
ואחת מהן סורקת את המודול הזה ותיפול על שם של מודל בטקסט.

⚠️ **שום תוכן יומן אינו נשמר.** אין טבלה, אין מיגרציה ואין כתיבה למסד.
זאת ההבטחה ב-``frontend/public/privacy.html``, ויש עליה בדיקה שעוברת על
כל העמודות הטקסטואליות בכל הטבלאות.

⚠️ **הנתיב אינו מכיר את גוגל.** כל הקריאות, אילו יומנים, פרישת פגישה
חוזרת וקידוד מזהה היומן יושבים ב-``app/gcal.py`` — בדיוק כמו
``routers/emails.py`` מול ``app/gmail.py``, וזאת הסיבה שהשכבה נבנתה בלי
לדעת שיש בוט.
"""

import logging
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import gauth, gcal
from ..auth import require_user
from ..db import get_db
from ..schemas import (
    CalendarEventOut,
    CalendarOut,
    CalendarPersonOut,
    CalendarRefOut,
    EventIn,
    EventPatch,
    EventSaved,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["calendar"], dependencies=[Depends(require_user)])

# אותם ארבעה משפטים של מסך המיילים, מאותה סיבה: ‏503 הוא מצב שהמשתמש
# יכול לתקן בהגדרות, ו-502 הוא "אפשר לנסות שוב"
NOT_CONFIGURED = "חיבור גוגל לא מוגדר בשרת. חסרים מפתחות ב-.env"
NOT_CONNECTED = "חשבון הגוגל לא מחובר. אפשר לחבר אותו במסך ההגדרות."
DISCONNECTED = "החיבור לגוגל נפסל וצריך לחבר מחדש, במסך ההגדרות."
UNAVAILABLE = "לא הצלחתי להגיע ליומן כרגע. אפשר לנסות שוב בעוד רגע."
# ⚠️ שני משפטים של הכתיבה. "השתנה בינתיים" אינו תקלה אלא מצב אמיתי:
# מישהו אחר נגע באירוע, והדבר הנכון הוא לרענן ולא לדרוס
CHANGED = "הפגישה השתנתה בגוגל בינתיים. כדאי לרענן ולנסות שוב."
MISSING = "הפגישה כבר לא קיימת ביומן."

# ⚠️ **תקרה על אורך הטווח, ולא רק ברירת מחדל.** בלעדיה בקשה עם
# ``days=4000`` הייתה שולפת שנים מכל היומנים בקריאה אחת — ויומן החגים
# לבדו מחזיר אירוע בשבוע לנצח. 31 יום מכסה חודש, שהוא הכי רחב שהמסך
# מציג בפועל
MAX_DAYS = 31


def _require_connection(db: Session) -> None:
    """עוצר לפני הפנייה לגוגל, כדי להחזיר משפט מובן ולא שגיאת רשת."""
    if not gauth.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED)
    cred = gauth.get_credential(db)
    if cred is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONNECTED)
    if cred.status != "connected":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DISCONNECTED)


@router.get("", response_model=CalendarOut)
def list_calendar(
    db: Session = Depends(get_db),
    start: date | None = Query(None, description="היום הראשון בטווח. ברירת מחדל: היום"),
    days: int = Query(7, ge=1, le=MAX_DAYS),
) -> CalendarOut:
    """האירועים בטווח, והיומנים שנקראו.

    ⚠️ **``start`` ו-``days`` ולא "השבוע".** המסך מדפדף אחורה וקדימה,
    ושבוע שאינו השבוע הזה אינו ``scope`` — ולכן ההמרה מתצוגה לטווח
    נעשית בצד הלקוח, והשרת מקבל שני מספרים מדויקים.

    ⚠️ **שתי הקבוצות חוזרות באותה תשובה**, כמו במסך המיילים: החלפת
    תצוגה בין לוח לרשימה היא סידור של אותם נתונים, ואינה פנייה נוספת
    לגוגל.
    """
    _require_connection(db)
    today = gcal.today_local()
    first = start or today
    try:
        # ⚠️ ``owned_only=False`` — חדר ישיבות וחגים נכללים במסך
        cals = gcal.calendars(db, owned_only=False)
        found = gcal.day_range(db, first, days, owned_only=False)
    except gauth.GoogleDisconnected as exc:
        log.warning("החיבור לגוגל נפסל באמצע בקשה למסך היומן: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DISCONNECTED) from exc
    except (gcal.CalendarError, gauth.GoogleError) as exc:
        log.warning("שליפת היומן למסך נכשלה: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, UNAVAILABLE) from exc

    return CalendarOut(
        start=first,
        days=days,
        today=today,
        calendars=[
            CalendarRefOut(
                id=cal.id, name=cal.name, primary=cal.primary, writable=cal.writable
            )
            for cal in cals
        ],
        events=[
            CalendarEventOut(
                id=event.id,
                title=event.title,
                calendar=event.calendar,
                calendar_id=event.calendar_id,
                from_primary=event.from_primary,
                all_day=event.all_day,
                start=event.start,
                end=event.end,
                day=event.day,
                location=event.location,
                # ⚠️ שמות המשתתפים, אחרי שכרטיס הלקוח החליף בהם כתובת
                # שגוגל לא נתנה לה שם. ``event.emails`` אינו נשלח —
                # הוא קיים לזיהוי בתדריך ואין לו שימוש בתצוגה
                attendees=event.attendees,
                description=event.description,
                # ⚠️ **האם זה מופע של סדרה, ולא מזהה הסדרה.** המזהה
                # עצמו נקרא בשרת לפני כל שינוי, כדי שבקשה לא תוכל
                # להצהיר "זאת סדרה" ולגעת בפגישות שלא נראו
                recurring=bool(event.recurring_id),
                etag=event.etag,
            )
            for event in found
        ],
    )


@router.get("/people", response_model=list[CalendarPersonOut])
def list_people(db: Session = Depends(get_db)) -> list[CalendarPersonOut]:
    """הלקוחות שיש להם כתובת מייל, לבורר המשתתפים.

    ⚠️ **זה לא "אנשי הקשר של גוגל".** אוטוקומפליט אמיתי מאנשי הקשר
    דורש את ההרשאה ``contacts.readonly``, כלומר מסך אישור חדש מול גוגל
    ועדכון של שני דפי המדיניות. הבורר מציע את מה שכבר במסד, ולצידו
    אפשר להקליד כל כתובת ביד — וזה מכסה זימון בלי לגעת בהרשאות.

    ⚠️ **אין כאן פנייה לגוגל בכלל**, ולכן גם לא 503/502.
    """
    found = gcal.client_names(db)
    people = [CalendarPersonOut(name=name, email=address) for address, name in found.items()]
    people.sort(key=lambda person: person.name)
    return people


def _busy_text(ranges: list[tuple[datetime, datetime]]) -> str:
    """מה תפוס, במשפט אחד בעברית."""
    parts = [f"{start:%H:%M}–{end:%H:%M}" for start, end in ranges[:3]]
    return "תפוס ב" + ", ".join(parts)


def _clashes(
    db: Session,
    begins: datetime,
    ends: datetime,
    ignore: tuple[datetime | None, datetime | None] = (None, None),
) -> list[tuple[datetime, datetime]]:
    """התנגשויות בטווח, בלי הפגישה שאותה עצמה מזיזים.

    ⚠️⚠️ **בלי ``ignore`` כל הארכה של פגישה הייתה מתנגשת בעצמה.**
    ‏``freeBusy`` מחזיר גם את האירוע שמשנים, שעדיין יושב בשעה הישנה,
    ולכן "להאריך פגישה ברבע שעה" היה מחזיר "תפוס" תמיד — התנגשות
    מדומה שהמשתמש לא יכול ליישב, והוא היה לומד ללחוץ "בכל זאת" תמיד.
    """
    found = gcal.conflicts(db, begins, ends)
    was_start, was_end = ignore
    if was_start is None or was_end is None:
        return found
    return [(start, end) for start, end in found if (start, end) != (was_start, was_end)]


def _moment(day: date, begins: time, ends: time) -> tuple[datetime, datetime]:
    """מרכיב יום ושעות קיר לשתי נקודות זמן בשעון ההתקנה.

    ⚠️⚠️ **כאן, ולא בדפדפן.** ``Asia/Jerusalem`` יושב בשרת, ומחשב
    באזור זמן אחר היה קובע את הפגישה בשעה הלא נכונה בלי שאיש יראה.
    """
    tz = gcal.local_tz()
    return (
        datetime.combine(day, begins, tzinfo=tz),
        datetime.combine(day, ends, tzinfo=tz),
    )


def _google(exc: Exception) -> HTTPException:
    """מתרגם שגיאה של שכבת היומן לתשובה שהמסך יודע להציג."""
    if isinstance(exc, gauth.GoogleDisconnected):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DISCONNECTED)
    if isinstance(exc, gcal.ReadOnlyCalendar):
        # ⚠️ 403 ולא 502: זה אינו "נסה שוב", וחדר הישיבות לעולם לא
        # יהיה ניתן לעריכה מכאן
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, gcal.EventChanged):
        # ⚠️ 412 ולא 409, כדי שהמסך יבדיל בין "תפוס, רוצה בכל זאת?"
        # (409, שאפשר לאשר) לבין "השתנה בינתיים" (412, שחייב רענון)
        return HTTPException(status.HTTP_412_PRECONDITION_FAILED, CHANGED)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, UNAVAILABLE)


@router.post("/events", response_model=EventSaved, status_code=status.HTTP_201_CREATED)
def add_event(payload: EventIn, db: Session = Depends(get_db)) -> EventSaved:
    """קובע פגישה חדשה.

    ⚠️ **התנגשות אינה שגיאה אלא שאלה.** הפנייה הראשונה מחזירה 409 עם
    מה שתפוס, המסך מציג אותו, והמשתמש מחליט — בדיוק כמו בבוט.
    """
    _require_connection(db)
    begins, ends = _moment(payload.day, payload.start_time, payload.end_time)
    try:
        if not payload.force:
            clash = _clashes(db, begins, ends)
            if clash:
                raise HTTPException(status.HTTP_409_CONFLICT, _busy_text(clash))
        made = gcal.create(
            db,
            payload.title.strip(),
            begins,
            ends,
            payload.attendees,
            calendar_id=payload.calendar_id,
            location=payload.location,
            description=payload.description,
            notify=payload.notify,
        )
    except HTTPException:
        raise
    except (gcal.CalendarError, gauth.GoogleError) as exc:
        log.warning("יצירת פגישה מהמסך נכשלה: %s", exc)
        raise _google(exc) from exc
    return EventSaved(id=made.id, calendar_id=payload.calendar_id or gcal.PRIMARY,
                      invited=made.invited and payload.notify)


@router.patch("/events/{event_id}", response_model=EventSaved)
def change_event(event_id: str, payload: EventPatch, db: Session = Depends(get_db)) -> EventSaved:
    """משנה פגישה קיימת, מופע אחד או כל הסדרה.

    ⚠️⚠️ **מזהה הסדרה נקרא מגוגל ולא מגיע מהלקוח.** בקשה שמצהירה
    ``whole_series`` על אירוע שאינו חוזר פשוט משנה אותו עצמו, ואי אפשר
    להשתמש בה כדי לגעת בפגישות שלא נראו.
    """
    _require_connection(db)
    try:
        current = gcal.one_event(db, event_id, payload.calendar_id or gcal.PRIMARY)
        if current is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, MISSING)
        target = event_id
        if payload.whole_series and current.recurring_id:
            target = current.recurring_id
        begins = ends = None
        if payload.day and payload.start_time and payload.end_time:
            begins, ends = _moment(payload.day, payload.start_time, payload.end_time)
            if not payload.force:
                clash = _clashes(db, begins, ends, (current.start, current.end))
                if clash:
                    raise HTTPException(status.HTTP_409_CONFLICT, _busy_text(clash))
        changed = gcal.update_event(
            db,
            target,
            payload.calendar_id or gcal.PRIMARY,
            title=payload.title,
            begins=begins,
            ends=ends,
            location=payload.location,
            description=payload.description,
            attendees=payload.attendees,
            notify=payload.notify,
            # ⚠️ ה-etag שייך למופע, ולכן אינו נשלח כששומרים על הסדרה
            etag="" if target != event_id else payload.etag,
        )
    except HTTPException:
        raise
    except (gcal.CalendarError, gauth.GoogleError) as exc:
        log.warning("שינוי פגישה מהמסך נכשל: %s", exc)
        raise _google(exc) from exc
    if changed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MISSING)
    return EventSaved(
        id=changed.id,
        calendar_id=payload.calendar_id or gcal.PRIMARY,
        invited=bool(payload.attendees) and payload.notify,
    )


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_event(
    event_id: str,
    db: Session = Depends(get_db),
    calendar_id: str = Query("", description="היומן. ברירת מחדל: הראשי"),
    whole_series: bool = Query(False),
    notify: bool = Query(False),
) -> None:
    """מבטל פגישה, מופע אחד או כל הסדרה.

    ⚠️ **``notify`` שולח הודעת ביטול למשתתפים.** ההזמנה שכבר יצאה אינה
    נמחקת מהתיבה שלהם, אבל היא מסומנת כמבוטלת — וזה הדבר הקרוב ביותר
    ל"בטל" שאפשר, ועדיף על שתיקה.
    """
    _require_connection(db)
    try:
        current = gcal.one_event(db, event_id, calendar_id or gcal.PRIMARY)
        if current is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, MISSING)
        target = event_id
        if whole_series and current.recurring_id:
            target = current.recurring_id
        gone = gcal.delete_event(db, target, notify, calendar_id or gcal.PRIMARY)
    except HTTPException:
        raise
    except (gcal.CalendarError, gauth.GoogleError) as exc:
        log.warning("מחיקת פגישה מהמסך נכשלה: %s", exc)
        raise _google(exc) from exc
    if not gone:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MISSING)
