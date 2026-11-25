"""מסך היומן בדשבורד — קריאה בלבד (שלב 4ב-4).

**למה מסך בנוסף לבוט, ולא במקומו.** ההכרעה מ-23.11.2026 העבירה את
טריאז' המיילים מהבוט למסך, כי 29 מיילים אינם נכנסים להודעת וואטסאפ.
⚠️ **ביומן הנימוק פועל לכיוון ההפוך** — יום הוא שלוש עד חמש שורות ולא
29 — ולכן ההכרעה מ-24.11 השאירה את היומן בבוט. **המסך אינו מחליף
אותו:** "מה יש לי מחר" נשאר התשובה הנוחה, והלוח השבועי הוא מה שהבוט
אינו יכול לתת — תמונת שבוע שרואים בבת אחת, עם החורים בין הפגישות.

⚠️ **קריאה בלבד, והוכרע במפורש ב-25.11.2026.** אין כאן קביעה, אין
עריכה ואין מחיקה. ``gcal.py`` אוסר ``PATCH`` ו-``PUT`` ויש בדיקה שתיפול
אם מישהו יוסיף אותם — שינוי אירוע שהמערכת לא יצרה עלול לדרוס פגישה —
והמסך הזה אינו פותח את הגבול ההוא. קביעה נעשית בבוט (4ב-2).

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
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import gauth, gcal
from ..auth import require_user
from ..db import get_db
from ..schemas import CalendarEventOut, CalendarOut, CalendarRefOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["calendar"], dependencies=[Depends(require_user)])

# אותם ארבעה משפטים של מסך המיילים, מאותה סיבה: ‏503 הוא מצב שהמשתמש
# יכול לתקן בהגדרות, ו-502 הוא "אפשר לנסות שוב"
NOT_CONFIGURED = "חיבור גוגל לא מוגדר בשרת. חסרים מפתחות ב-.env"
NOT_CONNECTED = "חשבון הגוגל לא מחובר. אפשר לחבר אותו במסך ההגדרות."
DISCONNECTED = "החיבור לגוגל נפסל וצריך לחבר מחדש, במסך ההגדרות."
UNAVAILABLE = "לא הצלחתי להגיע ליומן כרגע. אפשר לנסות שוב בעוד רגע."

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
            CalendarRefOut(id=cal.id, name=cal.name, primary=cal.primary) for cal in cals
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
            )
            for event in found
        ],
    )
