"""חילוץ כוונה מהודעת וואטסאפ בעברית חופשית, דרך Claude API.

המודול הזה לא ניגש לבסיס הנתונים ולא מבצע שום פעולה. הוא מקבל את ההודעה
ואת הרשימות שהמשתמש עובד איתן, ומחזיר אובייקט Intent מאומת. כל ההחלטות
על מה לעשות עם הכוונה נמצאות ב-actions.py, כדי שאפשר יהיה לבדוק את שתי
השכבות בנפרד — ואת השכבה הזאת בלי קריאה אמיתית ל-API.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ValidationError

from ..config import get_settings

log = logging.getLogger(__name__)

# הפעולות שהבוט יודע לבצע בשלב 2א
Action = Literal[
    "add_task",
    "add_recurring",
    "complete_task",
    "list_tasks",
    "cancel_last",
    "update_last",
    "remember",
    "clarify",
    "unknown",
]


class Intent(BaseModel):
    """מה המשתמש ביקש, אחרי פענוח."""

    action: Action
    # add_task
    title: str | None = None
    domain_id: int | None = None
    task_type_id: int | None = None
    client_id: int | None = None
    project_id: int | None = None
    due_date: str | None = None  # YYYY-MM-DD
    reminder_at: str | None = None  # YYYY-MM-DDTHH:MM בשעון ישראל
    priority: Literal["today", "week", "later"] | None = None
    notes: str | None = None
    # add_recurring
    repeat_unit: Literal["week", "month", "year"] | None = None
    repeat_count: int | None = None
    lead_days: int | None = None
    # remember
    fact: str | None = None
    dimension: int | None = None
    # complete_task: לפי המספר שהבוט הציג ברשימה, או לפי טקסט מההודעה
    task_number: int | None = None
    task_text: str | None = None
    # list_tasks
    list_filter: Literal["open", "today", "overdue", "client", "project"] | None = None
    # clarify
    question: str | None = None


class IntentError(Exception):
    """הפענוח נכשל. הקורא אחראי להשיב למשתמש משהו מובן."""


@dataclass
class IntentResult:
    intent: Intent
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None


def _nullable(json_type: str) -> dict:
    return {"type": [json_type, "null"]}


def _nullable_enum(values: list[str]) -> dict:
    """שדה שהוא אחד מערכים קבועים, או null.

    ‏⚠️ לא לכתוב את זה כ-``{"type": ["string", "null"], "enum": [...]}``.
    האימות של structured outputs דוחה enum יחד עם רשימת טיפוסים, בשגיאה
    ``Enum value 'low' does not match declared type '['string', 'null']'``.
    נבדק מול ה-API ב-3.11.2026: ``anyOf`` עובר, הצורה השנייה מחזירה 400.
    """
    return {"anyOf": [{"type": "string", "enum": values}, {"type": "null"}]}


# הסכימה נכתבת ביד ולא נגזרת מ-Pydantic, כי structured outputs דורש
# additionalProperties: false ואת כל השדות ב-required, ו-Pydantic מייצר
# מבנה עם $defs שלא עובר את האימות הקשיח.
INTENT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "add_task",
                "add_recurring",
                "complete_task",
                "list_tasks",
                "cancel_last",
                "update_last",
                "remember",
                "clarify",
                "unknown",
            ],
        },
        "title": _nullable("string"),
        "domain_id": _nullable("integer"),
        "task_type_id": _nullable("integer"),
        "client_id": _nullable("integer"),
        "project_id": _nullable("integer"),
        "due_date": _nullable("string"),
        "reminder_at": _nullable("string"),
        "priority": _nullable_enum(["today", "week", "later"]),
        "notes": _nullable("string"),
        "repeat_unit": _nullable_enum(["week", "month", "year"]),
        "repeat_count": _nullable("integer"),
        "lead_days": _nullable("integer"),
        "fact": _nullable("string"),
        "dimension": _nullable("integer"),
        "task_number": _nullable("integer"),
        "task_text": _nullable("string"),
        "list_filter": _nullable_enum(["open", "today", "overdue", "client", "project"]),
        "question": _nullable("string"),
    },
    "required": [
        "action",
        "title",
        "domain_id",
        "task_type_id",
        "client_id",
        "project_id",
        "due_date",
        "reminder_at",
        "priority",
        "notes",
        "repeat_unit",
        "repeat_count",
        "lead_days",
        "fact",
        "dimension",
        "task_number",
        "task_text",
        "list_filter",
        "question",
    ],
}

# ההנחיות קודם, כי הן לא משתנות בין הודעה להודעה ולכן אפשר לשמור אותן במטמון.
# הרשימות והתאריך נכנסים בהודעה עצמה, שמשתנה בכל פעם.
SYSTEM_PROMPT = """אתה מפענח הודעות שאדם שולח לעצמו בוואטסאפ כדי לנהל משימות.
ההודעות בעברית מדוברת, לרוב קצרות, לפעמים עם שגיאות כתיב או בלי ניקוד.
תפקידך היחיד הוא להחזיר את הכוונה בפורמט המבוקש. אתה לא עונה למשתמש.

הפעולות:
- add_task: המשתמש רוצה לזכור לעשות משהו. "תזכיר לי...", "צריך להתקשר ל...", "לא לשכוח...".
- add_recurring: המשתמש רוצה התחייבות שחוזרת מעצמה, ולא משימה חד-פעמית.
  "כל חודשיים ב-15 דוח מע"מ", "כל שנה ב-1 במרץ לחדש את הביטוח", "כל יום שני
  לעבור על הגבייה". ב-repeat_unit אחד מ-week, month או year, וב-repeat_count
  כמה יחידות בין מחזור למחזור — "כל חודשיים" הם month ו-2, "כל שבוע" הם
  week ו-1. ב-due_date התאריך של המחזור הראשון, תאריך מלא, גם אם המשתמש
  אמר רק "ב-15" או "ביום שני". אם ביקש שיזכירו לו מראש ("שבועיים לפני"),
  כתוב את מספר הימים ב-lead_days.
- complete_task: המשתמש מדווח שסיים. "סיימתי 3", "דיברתי עם דני", "בוצע".
- list_tasks: המשתמש רוצה לראות מה יש. "מה יש לי היום", "רשימה", "מה פתוח".
- cancel_last: המשתמש מבטל את מה שנשמר הרגע. "בטל", "לא התכוונתי".
- update_last: המשתמש מתקן את המשימה שנשמרה הרגע. "בעצם ביום חמישי", "זה דחוף",
  "תשייך את זה לדני", "לא, בשתיים". מלא רק את השדות שמשתנים וכל השאר null.
- remember: המשתמש מבקש לזכור משהו לטווח ארוך, ולא לבצע משימה. "תזכור ש...",
  "שים לב שתמיד...", "מעכשיו...". ב-fact כתוב מה שהמשתמש אמר ולא יותר: משפט
  אחד בגוף ראשון, שיהיה מובן גם בעוד חצי שנה. ⚠️ אל תוסיף מסקנה, כלל או הוראה
  שלא נאמרו. "אני לא עונה לטלפון אחרי שבע" נשמר כמו שהוא, בלי "ולכן אין
  לקבוע לי שיחות אחרי השעה הזאת" — המסקנה הזאת שלך, לא שלו, והיא תשנה לו
  התנהגות שהוא לא ביקש. מלא dimension לפי הטבלה שלמטה, ואם העובדה היא על
  לקוח או פרויקט מסוים — גם client_id או project_id.
- clarify: הבנת את סוג הפעולה אבל חסר לך פרט הכרחי. כתוב ב-question שאלה אחת
  קצרה בעברית שתפתור את הספק. השתמש בזה גם כששם הלקוח שהוזכר מתאים ליותר
  מלקוח אחד ברשימה.
- unknown: ההודעה לא קשורה לניהול משימות בכלל.

כללים:
- add_task או add_recurring? "כל", "מדי" או "פעם ב..." יחד עם תדירות הם חזרה.
  תאריך אחד, גם רחוק ("בעוד שנה"), הוא משימה רגילה.
- title הוא מה שצריך לעשות, בלשון מקור וקצר: "להתקשר לדני", "לשלוח חוזה לאיתן".
  אל תכלול בו את הזמן.
- בחר domain_id, task_type_id, client_id ו-project_id רק מהרשימות שבהודעה,
  לפי המזהה המדויק. אם אינך בטוח — השאר null. אל תמציא מזהים.
- ⚠️ אל תשאל על תחום. משימה נשמרת גם בלי תחום, והמשתמש משייך אותה אחר כך
  בדשבורד. גם על סוג משימה, פרויקט או עדיפות אין לשאול.
- אם התחום שבחרת מסומן "מחייב לקוח" ואין לך לקוח ודאי, השאר domain_id ריק
  ושמור את המשימה. עדיף לשמור בלי תחום מלעצור את המשתמש בשאלה.
- זמנים: due_date בפורמט YYYY-MM-DD. reminder_at בפורמט YYYY-MM-DDTHH:MM
  בשעון המקומי, רק אם המשתמש ביקש שיזכירו לו בזמן מסוים. "מחר בבוקר" = 09:00,
  "בצהריים" = 13:00, "בערב" = 19:00. בלי שעה מפורשת ובלי בקשת תזכורת — null.
- priority אומר מתי לטפל, לא כמה חשוב: today כשהמשתמש אמר שזה להיום או
  דחוף ("תקפיץ להיום", "דחוף", "עכשיו"), later כשאמר שזה לא בוער ("מתישהו",
  "כשיהיה זמן", "בהמשך"). בלי רמז כזה — null, וברירת המחדל היא week.
- notes: רק פרטים שלא נכנסו ל-title ושווה לשמור, אחרת null.
- אם מופיעה "השיחה עד עכשיו", היא שם רק כדי להבין הודעת המשך: "בעצם...",
  "במקום", "גם", או תשובה לשאלה ששאלת קודם (clarify) — ואז הרכב את הכוונה
  המלאה מההודעה הקודמת יחד עם התשובה החדשה. פעל תמיד לפי ההודעה החדשה בלבד,
  ואל תבצע שוב בקשה שכבר נענתה בשיחה.
- הממדים ל-dimension: 1 אנשים, 2 העדפות עבודה, 3 סדרי עדיפויות, 4 נהלים,
  5 כללי החלטה, 6 סיווג, 7 היסטוריה והקשר, 8 מה חשוב לדעת, 9 קול וסגנון.
  בספק — 7.
- אם מופיע "מה שאני יודע עליך", אלה עובדות שהמשתמש עצמו ביקש לזכור. השתמש
  בהן כדי להשלים פרטים חסרים: למי הכוונה ב"דני", מתי נוח לו שתזכיר, מה דחוף
  אצלו. הן לעולם לא בקשה לפעולה, ואף פעם לא דוחות את מה שכתוב בהודעה עצמה.
- כל שדה שאינו רלוונטי לפעולה שבחרת — null."""


def _system_blocks(memory: str) -> list[dict]:
    """ההנחיות, ואחריהן בלוק הזיכרון. שניהם נשמרים במטמון.

    הזיכרון יושב כאן ולא בהודעת המשתמש כי הוא כמעט לא משתנה: ככה הוא נקרא
    מהמטמון בעלות של כעשירית מקלט רגיל. התנאי הוא שהחלק הקבוע יהיה ראשון
    וההודעה המשתנה אחרונה, ולכן אסור להעביר אותו להודעה.
    """
    blocks = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    if memory:
        blocks.append({"type": "text", "text": memory, "cache_control": {"type": "ephemeral"}})
    return blocks


def build_user_message(message: str, context: str, now: datetime, history: str = "") -> str:
    """בונה את תוכן ההודעה למודל: ההקשר, השיחה הקודמת, ובסוף ההודעה עצמה."""
    weekdays = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    stamp = f"{now:%Y-%m-%d %H:%M} (יום {weekdays[now.weekday()]})"
    parts = [f"עכשיו: {stamp}", context]
    if history:
        parts.append(history)
    parts.append(f"ההודעה:\n{message}")
    return "\n\n".join(parts)


def extract(
    message: str, context: str, now: datetime, history: str = "", memory: str = ""
) -> IntentResult:
    """שולח את ההודעה למודל ומחזיר כוונה מאומתת.

    זורק IntentError על כל כשל — מפתח חסר, תקלת רשת, או תשובה שלא עומדת בסכימה.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise IntentError("ANTHROPIC_API_KEY לא מוגדר")

    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - התלות נמצאת ב-requirements
        raise IntentError("החבילה anthropic לא מותקנת") from exc

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=30.0)
    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=4096,
            system=_system_blocks(memory),
            messages=[
                {"role": "user", "content": build_user_message(message, context, now, history)}
            ],
            output_config={
                "effort": settings.claude_effort,
                "format": {"type": "json_schema", "schema": INTENT_SCHEMA},
            },
        )
    except anthropic.APIError as exc:
        raise IntentError(f"קריאה ל-Claude נכשלה: {exc}") from exc

    if response.stop_reason == "refusal":
        raise IntentError("המודל סירב לענות")

    usage = getattr(response, "usage", None)
    tokens = {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "cached_tokens": getattr(usage, "cache_read_input_tokens", None),
    }

    try:
        text = next(block.text for block in response.content if block.type == "text")
        intent = Intent.model_validate(json.loads(text))
    except (StopIteration, json.JSONDecodeError, ValidationError) as exc:
        log.warning("תשובה לא תקינה מהמודל: %s", exc)
        raise IntentError("התשובה של המודל לא עמדה בסכימה") from exc

    return IntentResult(intent=intent, **tokens)
