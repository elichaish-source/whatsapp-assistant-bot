"""קריאת מיילים דרך הבוט: סיכום, חיפוש, והצגת מייל מלא (שלב 4-2).

השכבה הזאת מנסחת בעברית ושומרת את המספור. **כל מה שנוגע לגוגל, לסינון
ולניקוי הציטוטים יושב ב-``app/gmail.py``** ולא כאן — טרם הוכרע אם טריאז'
המיילים יושב בבוט או במסך בדשבורד, וההפרדה הזאת היא מה שיאפשר למסך
להשתמש באותן פונקציות בלי שכתוב.

⚠️ **רשימת מיילים מאפסת את מספור המשימות.** בלי זה "סיימתי 2" אחרי
רשימת מיילים היה נופל על הרשימה שלפניה וסוגר משימה אחרת לגמרי — בדיוק
הבאג ש-``clear_list`` נולד בשבילו בשלב 2ג1.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import gauth, gmail
from ..models import BotMessage
from .actions import Outcome
from .intent import Intent

log = logging.getLogger(__name__)

NOT_CONNECTED = (
    "חשבון הגוגל לא מחובר. אפשר לחבר אותו במסך «הגדרות» בדשבורד, ואז לנסות שוב."
)
DISCONNECTED = (
    "החיבור לגוגל נפסל וצריך לחבר מחדש. זה נעשה במסך «הגדרות» בדשבורד."
)


# ⚠️ נבנה אחרי שהמשתמש כתב "זרוק אותו לארכיון" ב-22.11.2026 וקיבל
# "לא הבנתי. אפשר לכתוב למשל תזכיר לי מחר ב-10 להתקשר לדני" — תשובה
# שמפנה אותו למשימות במקום לומר שהיכולת פשוט עוד לא קיימת. ארכוב ומענה
# הם 4-3 ו-4-4, וטרם הוכרע אם הם יושבים בבוט או במסך בדשבורד.
NOT_YET = (
    "ארכוב, מענה ויצירת משימה ממייל עוד לא נבנו.\n"
    "מה שאפשר עכשיו: «מה נכנס היום», «תראה לי את כולם», "
    "«מה כתב לי דני» ו«תראה לי את 2»."
)


def email_not_yet(db: Session, intent: Intent) -> Outcome:
    """פעולה על מייל שטרם נבנתה. עונה בכוונה בלי להבטיח מתי."""
    return Outcome(NOT_YET)


def _unavailable(exc: Exception) -> Outcome:
    """תקלה בגישה לתיבה. ‏⚠️ אינה מאפסת את המספור הקיים.

    אם הרשת נפלה באמצע, הרשימה שהבוט שלח לפני רגע עדיין תקפה, ו"תראה לי
    את 2" צריך להמשיך לעבוד אחרי שהתקלה חולפת.
    """
    log.warning("גישה לתיבת הדואר נכשלה: %s", exc)
    return Outcome("לא הצלחתי להגיע לתיבת הדואר כרגע. אפשר לנסות שוב בעוד רגע.")


def _ready(db: Session) -> Outcome | None:
    """בודק שיש חיבור לפני שפונים לגוגל, כדי לענות משהו מובן ולא שגיאה."""
    if not gauth.configured():
        return Outcome(NOT_CONNECTED)
    cred = gauth.get_credential(db)
    if cred is None or cred.status != "connected":
        return Outcome(DISCONNECTED if cred else NOT_CONNECTED)
    return None


# --- עיצוב הרשימה ---


def _when(moment) -> str:
    """שעה למייל של היום, ותאריך ושעה לכל השאר.

    ⚠️ בלי התאריך, סיכום שבועי הציג "20:36" ו-"12:29" זה מתחת לזה כאילו
    הם מאותו יום. נראה בתשובה אמיתית ב-19.11.2026.
    """
    today = datetime.now(tz=gmail.local_tz()).date()
    return moment.strftime("%H:%M" if moment.date() == today else "%d/%m %H:%M")


def _format(items: list[gmail.EmailSummary], lines: dict[str, str]) -> str:
    """הרשימה הממוספרת: שולח ושעה, ומתחת שורת התיאור.

    הפורמט נבחר על ידי המשתמש ב-19.11.2026, מתוך שלוש אפשרויות.
    """
    blocks = []
    for index, item in enumerate(items, start=1):
        detail = (lines.get(item.id) or item.subject)[:200].strip()
        block = f"{index}. {item.sender()} · {_when(item.received_at)}"
        if detail:
            block += f"\n   {detail}"
        blocks.append(block)
    return "\n\n".join(blocks)


def _listed(items: list[gmail.EmailSummary]) -> list[str]:
    return [item.id for item in items]


def _reply(body: str, items: list[gmail.EmailSummary]) -> Outcome:
    """רשימה ממוספרת, מפוצלת להודעות אם היא ארוכה.

    ⚠️ הפיצול נחוץ כאן ולא רק במייל בודד: "תראה לי את כולם" על שבוע
    החזיר 29 מיילים מול התיבה האמיתית, ווואטסאפ חותכת ב-4096 תווים —
    כלומר **סוף הרשימה היה נאבד בשקט, יחד עם המספרים הגבוהים.**
    """
    parts = gmail.split_message(body, max_parts=6)
    return Outcome(
        "\n".join(parts),
        listed_email_ids=_listed(items),
        clear_list=True,
        parts=parts if len(parts) > 1 else None,
    )


def _count(number: int) -> str:
    """"מייל אחד" ולא "1 מיילים". נראה בתשובה אמיתית ב-19.11.2026."""
    return "מייל אחד" if number == 1 else f"{number} מיילים"


def _arrived(number: int, span: str) -> str:
    return f"נכנס {span} מייל אחד" if number == 1 else f"נכנסו {span} {number} מיילים"


# ⚠️ ההכרעה שהמשתמש בחר אמרה במפורש "אתה יודע שהיה שם משהו **ויכול
# לבקש לראות**". היכולת לבקש לא נבנתה, והמשתמש גילה את זה בשימוש
# הראשון: הוא כתב "תראה לי את כולם בכל זאת" וקיבל שוב את אותה תשובה.
SHOW_ALL = 'לראות גם את מה שסוננו — כתוב "תראה לי את כולם".'


def _hint(count: int) -> str:
    """ההנחיה לקריאת מייל, עם מספר שקיים באמת ברשימה.

    ⚠️ היה כתוב כאן "תראה לי את 2" קבוע, וברשימה של מייל אחד זה הפנה
    למספר שאינו קיים. נראה מול התיבה האמיתית ב-19.11.2026.
    """
    return f'\n\nלקריאת מייל שלם כתוב "תראה לי את {1 if count == 1 else 2}".'


# --- סיכום לפי בקשה ---


def list_emails(db: Session, intent: Intent) -> Outcome:
    """"מה נכנס היום" — מה שלא נקרא בלשונית "ראשי", אחרי סינון.

    שלוש ההכרעות של המשתמש מיושמות כאן: רק מה שלא נקרא, ‏Haiku כותב את
    שורות התיאור לבדו, ומה שנדחה מוצג כמונה בשורה אחת ולא נעלם.
    """
    blocked = _ready(db)
    if blocked:
        return blocked

    scope = intent.email_scope or "today"
    show_all = bool(intent.email_show_all)
    try:
        found = gmail.list_inbox(db, scope, show_all)
    except gauth.GoogleDisconnected:
        return Outcome(DISCONNECTED)
    except (gmail.GmailError, gauth.GoogleError) as exc:
        return _unavailable(exc)

    span = "השבוע" if scope == "week" else "היום"
    if not found:
        # ‏clear_list גם כאן: הבוט ענה על מיילים, ולכן מספור קודם של
        # משימות אינו רלוונטי יותר
        return Outcome(f"אין מיילים חדשים {span}.", clear_list=True)

    # "תראה לי את כולם" — **כל** השכבות נופלות, לא רק הסינון של Haiku.
    # ⚠️ הוכרע כך אחרי שהמשתמש ביקש "כולם" וקיבל 5 מתוך 29
    if show_all:
        body = f"{_arrived(len(found), span)} בדואר הנכנס, הכול:\n\n{_format(found, {})}"
        return _reply(body + _hint(len(found)), found)

    verdicts = gmail.triage(found, gmail.client_addresses(db))
    passed = [item for item in verdicts if item.relevant]
    filtered = len(verdicts) - len(passed)

    if not passed:
        nothing = "והוא לא נראה" if filtered == 1 else "ואף אחד מהם לא נראה"
        return Outcome(
            f"{_arrived(filtered, span)}, {nothing} דורש תשומת לב.\n{SHOW_ALL}",
            clear_list=True,
        )

    items = [item.email for item in passed]
    lines = {item.email.id: item.line for item in passed}
    heading = _arrived(len(items), span)
    if filtered:
        heading += f" (ועוד {filtered} סוננו)"

    body = f"{heading}:\n\n{_format(items, lines)}" + _hint(len(items))
    if filtered:
        body += f"\n{SHOW_ALL}"
    return _reply(body, items)


# --- חיפוש ---


def search_emails(db: Session, intent: Intent) -> Outcome:
    """"מה כתב לי דני" — על כל התיבה, בלי סינון ובלי לשונית.

    ‏⚠️ אין כאן ``triage``: בחיפוש המשתמש כבר אמר מה הוא מחפש, וסינון
    היה מסתיר ממנו בדיוק את מה שביקש. זה גם חוסך קריאה למודל.
    """
    blocked = _ready(db)
    if blocked:
        return blocked

    text = (intent.email_query or "").strip()
    if not text:
        return Outcome("מה לחפש במייל?")

    try:
        found = gmail.search(db, text)
    except gauth.GoogleDisconnected:
        return Outcome(DISCONNECTED)
    except (gmail.GmailError, gauth.GoogleError) as exc:
        return _unavailable(exc)

    if not found:
        return Outcome(f'לא מצאתי מייל שמתאים ל"{text}".', clear_list=True)

    body = f'מצאתי {_count(len(found))} על "{text}":\n\n'
    # בחיפוש מוצג גם הנושא: בלי מסגרת של "מה נכנס היום" הוא מה שמאפשר
    # לזהות שזה המייל הנכון
    blocks = []
    for index, item in enumerate(found, start=1):
        when = item.received_at.strftime("%d/%m %H:%M")
        blocks.append(
            f"{index}. {item.sender()} · {when}\n   {item.subject}"
        )
    body += "\n\n".join(blocks) + _hint(len(found))
    return _reply(body, found)


# --- מייל מלא ---


def _resolve(db: Session, number: int) -> str | None:
    """מתרגם מספר לרשימת המיילים האחרונה שהבוט שלח.

    אותו דפוס של ``_resolve_by_number`` למשימות, ובכוונה: המשתמש לא אמור
    לזכור איזו רשימה הוא ממספר.
    """
    row = db.scalars(
        select(BotMessage)
        .where(BotMessage.listed_email_ids.is_not(None))
        .order_by(BotMessage.id.desc())
        .limit(1)
    ).first()
    if not row or not row.listed_email_ids:
        return None
    ids = [part for part in row.listed_email_ids.split(",") if part]
    if not 1 <= number <= len(ids):
        return None
    return ids[number - 1]


def _render(mail: gmail.EmailFull) -> str:
    head = [
        f"מאת: {mail.sender()}",
        f"נושא: {mail.subject}",
        f"התקבל: {mail.received_at:%d/%m/%Y %H:%M}",
    ]
    if mail.attachments:
        # שמות בלבד. הקבצים עצמם אינם מורדים ואינם נשמרים
        head.append("מצורף: " + ", ".join(mail.attachments[:5]))
    body = mail.body.strip() or "(המייל ריק)"
    text = "\n".join(head) + "\n\n" + body
    if mail.quoted_removed:
        text += "\n\n— (ההיסטוריה המצוטטת הושמטה)"
    return text


def show_email(db: Session, intent: Intent) -> Outcome:
    """"תראה לי את כל מייל 2" — המייל המלא, בלי ההיסטוריה המצוטטת.

    ‏⚠️ שום מודל אינו מופעל בדרך. המייל עובר מגוגל לוואטסאפ דרך הקוד
    בלבד, וזו ההגנה החזקה מפני טקסט שנראה כהוראה בתוך מייל.
    """
    blocked = _ready(db)
    if blocked:
        return blocked

    message_id: str | None = None
    if intent.task_number:
        message_id = _resolve(db, intent.task_number)
        if message_id is None:
            return Outcome(
                'לא מצאתי מייל במספר הזה. אפשר לבקש "מה נכנס היום" ולנסות שוב.'
            )

    # המשתמש תיאר את המייל במילים ולא במספר. חיפוש, ואם יש התאמה אחת —
    # מציגים אותה מיד; כמה התאמות מוצגות כרשימה ולא נבחרות לבד
    if message_id is None:
        text = (intent.email_query or "").strip()
        if not text:
            return Outcome('איזה מייל להציג? אפשר "תראה לי את 2" או "תראה לי את המייל של דני".')
        try:
            found = gmail.search(db, text)
        except gauth.GoogleDisconnected:
            return Outcome(DISCONNECTED)
        except (gmail.GmailError, gauth.GoogleError) as exc:
            return _unavailable(exc)
        if not found:
            return Outcome(f'לא מצאתי מייל שמתאים ל"{text}".', clear_list=True)
        if len(found) > 1:
            blocks = [
                f"{index}. {item.sender()} · {item.received_at:%d/%m %H:%M}\n   {item.subject}"
                for index, item in enumerate(found, start=1)
            ]
            return Outcome(
                "יש כמה מיילים שמתאימים. לאיזה התכוונת?\n\n" + "\n\n".join(blocks),
                listed_email_ids=_listed(found),
                clear_list=True,
            )
        message_id = found[0].id

    try:
        mail = gmail.fetch_full(db, message_id)
    except gauth.GoogleDisconnected:
        return Outcome(DISCONNECTED)
    except (gmail.GmailError, gauth.GoogleError) as exc:
        return _unavailable(exc)

    parts = gmail.split_message(_render(mail))
    # ‏reply הוא הכול, כדי שביומן יישמר מה שנשלח באמת. parts הוא מה
    # שיוצא לוואטסאפ, הודעה אחר הודעה
    return Outcome("\n".join(parts), parts=parts if len(parts) > 1 else None)
