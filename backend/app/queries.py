"""שליפה חופשית מהבוט: המודל כותב SELECT, והקוד מריץ אותו בגבולות קשיחים.

שאלה אמיתית של בעל עסק — "מה פתוח אצל קניון ליין", "אילו לקוחות לא ביקשו
ממני כלום החודש" — כמעט אף פעם לא נופלת בדיוק לתוך תבנית מוכנה. לכן
השאילתה נכתבת על ידי המודל ולא נבחרת מרשימה סגורה.

ההגנה עברה בגלל זה ממקום למקום: לא צמצום של השאלות, אלא גבולות הרצה.
שלושה, ובלתי תלויים זה בזה:

1. **משתמש בסיס נתונים נפרד**, בלי הרשאת כתיבה בכלל, עם SELECT על הטבלאות
   המותרות בלבד. זאת החומה היחידה שאינה תלויה בקוד שכתבנו: גם שאילתה
   שעברה את כל הבדיקות לא תוכל לכתוב, ולא תראה את קודי ההתחברות.
2. **עסקה לקריאה בלבד עם תקרת זמן.** עובדת גם כשהמשתמש הנפרד לא הוגדר
   (פיתוח ובדיקות), ועוצרת שאילתה שנתקעה.
3. **בדיקת הטקסט** לפני ההרצה: ‏SELECT יחיד, בלי פקודה שנייה, בלי הערות,
   בלי מילות כתיבה ובלי שמות הטבלאות שאינן ברשימה.

הבדיקה לבדה לא הייתה מספיקה — תמיד אפשר למצוא ניסוח שעוקף ביטוי רגולרי.
בדיוק בגלל זה היא השכבה השלישית, ולא הראשונה.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from .config import get_settings

# שם המשתמש שהמיגרציה יוצרת. הסיסמה מגיעה מ-.env ולא מהקוד
READONLY_ROLE = "assistant_ro"

# הטבלאות שהשאילתה רשאית לגעת בהן. הרחבה כאן היא החלטה ולא פרט טכני:
# כל טבלה שנוספת נשלחת למודל ויוצאת ממנו בחזרה אלינו בהודעת וואטסאפ
ALLOWED_TABLES = ("tasks", "clients", "projects", "domains", "task_types", "recurrences")

# מילים שעצם הופעתן פוסלת. ‏login_codes ראשון ברשימה כי הוא היחיד שדליפה
# ממנו היא כניסה למערכת, ולא רק מידע
BLOCKED_WORDS = (
    "login_codes",
    "memory_facts",
    "observations",
    "bot_messages",
    "alembic_version",
    "pg_",
    "information_schema",
    "current_setting",
    "session_user",
)

# רק מילים שבאמת יכולות להופיע בתוך SELECT יחיד — כלומר בתוך CTE. אין
# טעם לפסול כאן VACUUM או COMMIT, שאינם יכולים לרוץ כאן ממילא, והרשימה
# הארוכה הייתה רק פוסלת שאילתות תמימות
WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|"
    r"merge|call|do|set|lock|refresh|execute)\b",
    re.IGNORECASE,
)

ROW_LIMIT = 50  # תקרה קשיחה על מה שחוזר מהמסד
ROWS_SHOWN = 20  # כמה שורות נכנסות להודעת וואטסאפ
STATEMENT_TIMEOUT_MS = 3000


class QueryRefused(Exception):
    """השאילתה לא עברה את הבדיקה ולא הורצה בכלל."""


class QueryFailed(Exception):
    """השאילתה הורצה ונכשלה. הטקסט חוזר למודל לניסיון שני."""


# תיאור הסכימה שנשלח למודל. יושב בהנחיה הקבועה ולכן נקרא מהמטמון,
# ולא נבנה מחדש בכל הודעה
SCHEMA_DOC = """מבנה הטבלאות לשאילתות:
- tasks: id, title, status ('open'/'done'), done_at, domain_id, task_type_id,
  client_id, project_id, due_date, reminder_at, priority ('today'/'week'/'later'),
  notes, from_bot, recurrence_id, created_at
- clients: id, name, phone, email, tax_id, address, notes, is_active, created_at
- projects: id, name, domain_id, client_id, description, due_date,
  status ('active'/'done'/'paused'), created_at
- domains: id, name, sort_order, requires_client
- task_types: id, name, sort_order
- recurrences: id, title, interval_unit ('week'/'month'/'year'), interval_count,
  start_date, cycle, lead_days, domain_id, task_type_id, client_id, project_id,
  priority, notes, active, from_bot
אין טבלאות אחרות, ואסור לפנות לטבלה שאינה ברשימה."""


def gate(sql: str) -> str:
    """בודק את הטקסט ומחזיר שאילתה עטופה בתקרת שורות. זורק QueryRefused."""
    query = (sql or "").strip().rstrip(";").strip()
    if not query:
        raise QueryRefused("לא קיבלתי שאילתה")
    if "--" in query or "/*" in query:
        # הערה היא הדרך הקלאסית להסתיר את החצי השני של פקודה
        raise QueryRefused("הערות אסורות בשאילתה")
    if ";" in query:
        raise QueryRefused("יותר מפקודה אחת")
    if not re.match(r"^(select|with)\b", query, re.IGNORECASE):
        raise QueryRefused("מותר SELECT בלבד")
    if WRITE_WORDS.search(query):
        raise QueryRefused("יש בשאילתה מילה שאינה קריאה")
    lowered = query.lower()
    for word in BLOCKED_WORDS:
        if word in lowered:
            raise QueryRefused(f"אין גישה ל-{word}")
    # העטיפה גוברת על LIMIT שהמודל כתב בעצמו, גם אם הוא גדול
    return f"SELECT * FROM (\n{query}\n) AS bot_query LIMIT {ROW_LIMIT}"


def readonly_url() -> str:
    """כתובת החיבור של משתמש הקריאה, או הרגילה אם הוא לא הוגדר."""
    settings = get_settings()
    if not settings.bot_readonly_password:
        return settings.database_url
    url = make_url(settings.database_url)
    return url.set(
        username=READONLY_ROLE, password=settings.bot_readonly_password
    ).render_as_string(hide_password=False)


@lru_cache
def _engine():
    # pool קטן בכוונה: שאילתות הבוט הן אירוע נדיר, ולא תעבורה
    return create_engine(readonly_url(), pool_pre_ping=True, pool_size=1, max_overflow=1)


def run(sql: str) -> tuple[list[str], list[tuple]]:
    """מריץ שאילתה שכבר עברה את gate. זורק QueryFailed על שגיאת מסד."""
    try:
        with _engine().connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            result = conn.execute(text(sql))
            rows = [tuple(row) for row in result.fetchall()]
            return list(result.keys()), rows
    except SQLAlchemyError as exc:
        raise QueryFailed(_short_error(exc)) from exc


def _short_error(exc: Exception) -> str:
    """השורה הראשונה של שגיאת Postgres. היא זו שאומרת מה חסר."""
    first = str(exc).strip().splitlines()[0]
    return first[:300]


def cell(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "כן" if value else "לא"
    if isinstance(value, datetime):
        return f"{value:%d/%m/%Y %H:%M}"
    if isinstance(value, date):
        return f"{value:%d/%m/%Y}"
    if isinstance(value, Decimal):
        return f"{value:g}"
    return str(value)


def render(columns: list[str], rows: list[tuple], heading: str) -> str:
    """מנסח את התוצאה כהודעת וואטסאפ: כותרת, ואחריה שורות ממוספרות.

    עמודת id לא מופיעה בטקסט. היא משמשת למספור, כדי ש"סיימתי 2" יעבוד גם
    על תוצאה של שאילתה ולא רק על רשימה.
    """
    if not rows:
        return f"{heading}: אין תוצאות."

    keep = [index for index, name in enumerate(columns) if name != "id"] or list(
        range(len(columns))
    )
    lines = [f"{heading} ({len(rows)}):"]
    for number, row in enumerate(rows[:ROWS_SHOWN], start=1):
        values = " · ".join(cell(row[index]) for index in keep)
        lines.append(f"{number}. {values}")
    if len(rows) > ROWS_SHOWN:
        lines.append(f"...ועוד {len(rows) - ROWS_SHOWN}")
    return "\n".join(lines)


def task_ids(sql: str, columns: list[str], rows: list[tuple]) -> list[int]:
    """המזהים, רק כששאלו על משימות.

    ‏⚠️ בלי התנאי הזה "סיימתי 2" אחרי שאילתה על לקוחות היה סוגר משימה
    אקראית שמספרה במקרה 2. לכן: רק כש-tasks היא הטבלה שממנה שולפים,
    ורק כשיש עמודת id.
    """
    if "id" not in columns or not re.search(r"\bfrom\s+tasks\b", sql, re.IGNORECASE):
        return []
    position = columns.index("id")
    return [int(row[position]) for row in rows if isinstance(row[position], int)]
