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

from .. import queries
from ..config import get_settings

log = logging.getLogger(__name__)

# הפעולות שהבוט יודע לבצע
Action = Literal[
    "add_task",
    "add_recurring",
    "complete_task",
    "list_tasks",
    "query_data",
    "cancel_last",
    "update_last",
    "update_task",
    "delete_task",
    "confirm",
    "decline",
    "add_client",
    "update_client",
    "add_project",
    "update_project",
    "add_domain",
    "add_task_type",
    "pause_recurrence",
    "resume_recurrence",
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
    priority: Literal["today", "tomorrow", "week", "later"] | None = None
    notes: str | None = None
    # add_recurring. ‏"none" ו-0 ולא null, בגלל מגבלת האיחודים בסכימה שלמטה
    repeat_unit: Literal["none", "week", "month", "year"] = "none"
    repeat_count: int = 0
    lead_days: int = 0
    # query_data. מחרוזת ריקה ולא null, מאותה סיבה
    sql: str = ""
    # remember
    fact: str | None = None
    dimension: int | None = None
    # complete_task: לפי המספר שהבוט הציג ברשימה, או לפי טקסט מההודעה
    task_number: int | None = None
    task_text: str | None = None
    # list_tasks
    list_filter: Literal["open", "today", "overdue", "client", "project"] | None = None
    # add_client, update_client, add_project, update_project. מחרוזת ריקה, 0
    # ו-"" ולא null, בגלל מגבלת האיחודים בסכימה שלמטה
    name: str = ""
    phone: str = ""
    email: str = ""
    tax_id: str = ""
    address: str = ""
    family_id: int = 0
    active: Literal["", "yes", "no"] = ""
    # add_domain. false ולא null, מאותה סיבה
    requires_client: bool = False
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
#
# ⚠️ מותר עד 16 שדות שהטיפוס שלהם הוא איחוד — כלומר ‎{"type": [x, "null"]}‎
# או anyOf. מעבר לזה ה-API מחזיר 400 על **כל** הודעה, והבוט מת לגמרי.
# זה מה שקרה ב-5.11.2026: שלושה שדות חדשים העלו את המספר ל-18.
# לכן שדה חדש שאינו חובה מקבל ערך "ריק" מפורש ("none", 0) ולא null.
# יש בדיקה ששומרת על הגבול, כי ה-400 מתגלה רק מול ה-API האמיתי.
MAX_UNION_FIELDS = 16
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
                "query_data",
                "cancel_last",
                "update_last",
                "update_task",
                "delete_task",
                "confirm",
                "decline",
                "add_client",
                "update_client",
                "add_project",
                "update_project",
                "add_domain",
                "add_task_type",
                "pause_recurrence",
                "resume_recurrence",
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
        "priority": _nullable_enum(["today", "tomorrow", "week", "later"]),
        "notes": _nullable("string"),
        "repeat_unit": {"type": "string", "enum": ["none", "week", "month", "year"]},
        "repeat_count": {"type": "integer"},
        "lead_days": {"type": "integer"},
        "sql": {"type": "string"},
        "fact": _nullable("string"),
        "dimension": _nullable("integer"),
        "task_number": _nullable("integer"),
        "task_text": _nullable("string"),
        "list_filter": _nullable_enum(["open", "today", "overdue", "client", "project"]),
        "question": _nullable("string"),
        "name": {"type": "string"},
        "phone": {"type": "string"},
        "email": {"type": "string"},
        "tax_id": {"type": "string"},
        "address": {"type": "string"},
        "family_id": {"type": "integer"},
        "active": {"type": "string", "enum": ["", "yes", "no"]},
        "requires_client": {"type": "boolean"},
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
        "sql",
        "fact",
        "dimension",
        "task_number",
        "task_text",
        "list_filter",
        "question",
        "name",
        "phone",
        "email",
        "tax_id",
        "address",
        "family_id",
        "active",
        "requires_client",
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
  כתוב את מספר הימים ב-lead_days, ואחרת 0.
- complete_task: המשתמש מדווח שסיים. "סיימתי 3", "דיברתי עם דני", "בוצע".
- list_tasks: המשתמש רוצה לראות מה יש. "מה יש לי היום", "רשימה", "מה פתוח".
- query_data: שאלה על הנתונים שאינה רשימת המשימות הפשוטה. "מה פתוח אצל
  קניון ליין", "כמה משימות סגרתי החודש", "אילו לקוחות אין להם שום משימה",
  "מתי התחייבות הביטוח הבאה". כתוב ב-sql שאילתת SELECT אחת לפי מבנה
  הטבלאות שלמטה, וב-title כותרת קצרה בעברית לתשובה ("פתוח אצל קניון ליין").
  ⚠️ כששולפים משימות — בחר תמיד גם את העמודה id ראשונה, כדי שהמשתמש יוכל
  לכתוב "סיימתי 2" על התוצאה.
- cancel_last: המשתמש מבטל את מה שנשמר הרגע. "בטל", "לא התכוונתי".
- update_last: המשתמש מתקן את המשימה שנשמרה הרגע. "בעצם ביום חמישי", "זה דחוף",
  "תשייך את זה לדני", "לא, בשתיים". מלא רק את השדות שמשתנים וכל השאר null.
- update_task: המשתמש משנה משימה קיימת שהוא מציין. "תדחה את הביטוח לשבוע
  הבא", "תעביר את 3 למחר", "תשייך את החוזה לדני", "תקפיץ את הדוח להיום".
  מלא task_number או task_text כדי לזהות את המשימה, ורק את השדות שמשתנים;
  כל השאר null. ב-title כתוב ניסוח חדש רק אם המשתמש ביקש לשנות את הניסוח.
- delete_task: המשתמש רוצה למחוק משימה קיימת שהוא מציין. "תמחק את המשימה על
  הביטוח", "תמחק את 2". זה לא "בטל": "בטל" לבד הוא cancel_last.
- confirm: המשתמש עונה בחיוב לשאלת אישור — ההודעה האחרונה שלך ב"השיחה עד
  עכשיו" שאלה אם לבצע משהו ("למחוק...?", "ליצור בכל זאת...?"), והוא ענה
  "כן", "אשר", "תמחק", "תיצור".
  בלי שאלת אישור כזאת לפניו, "כן" אינו confirm.
- decline: אותו מצב, והמשתמש ענה בשלילה: "לא", "עזוב", "אל תמחק".
- add_client: המשתמש מבקש במפורש לפתוח לקוח חדש. "לקוח חדש: משה כהן",
  "תוסיף לקוח בשם...", "תפתח לקוח...". ב-name שם הלקוח כפי שנאמר. מלא phone,
  email, tax_id (ח.פ, עוסק מורשה או ת"ז), address ו-notes רק אם נאמרו.
  ב-family_id מזהה מהרשימה "משפחות לקוחות" רק אם המשתמש אמר לאיזו משפחה
  הלקוח שייך, ואחרת 0. ⚠️ שם של אדם בתוך משימה ("להתקשר למשה") אינו בקשה
  לפתוח לקוח.
- update_client: המשתמש משנה פרטים של לקוח קיים. "הטלפון של דני הוא...",
  "תוסיף לדני מייל...", "דני כבר לא לקוח", "תחזיר את דני ללקוחות הפעילים".
  ב-client_id המזהה מהרשימות — לקוחות פעילים או לא פעילים. מלא רק את מה
  שמשתנה. name רק אם המשתמש ביקש לשנות את שם הלקוח עצמו. active הוא "no"
  כשהלקוח מפסיק להיות פעיל, "yes" כשהוא חוזר, ואחרת "". notes היא הערה
  להוסיף ללקוח.
- add_project: המשתמש מבקש במפורש לפתוח פרויקט. "פרויקט חדש לדני: הקמת
  אתר", "תפתח פרויקט...". ב-name שם הפרויקט, ב-client_id הלקוח אם הפרויקט
  שלו. ב-domain_id התחום המתאים ביותר מהרשימה: פרויקט חייב תחום, ולכן בחר
  גם כשהמשתמש לא אמר; רק אם באמת אי אפשר לדעת השאר null, והשרת ישאל.
  due_date אם נאמר תאריך יעד, ו-notes אם נאמר תיאור.
- update_project: המשתמש משנה פרויקט קיים. "סגור את פרויקט האתר", "פרויקט
  האתר עד סוף ינואר", "תעביר את פרויקט האתר לתחום שיווק". ב-project_id
  המזהה מהרשימה, ורק מה שמשתנה. active הוא "no" כשהפרויקט הסתיים או נסגר,
  ואחרת "". name רק אם המשתמש ביקש לשנות את שם הפרויקט.
- add_domain: המשתמש מבקש במפורש לפתוח תחום חדש. "תחום חדש: הפקות", "תוסיף
  תחום נדל"ן". ב-name שם התחום. requires_client הוא true רק אם המשתמש אמר
  שמשימות בתחום חייבות לקוח ("מחייב לקוח", "תמיד עם לקוח"), ואחרת false.
- add_task_type: המשתמש מבקש במפורש לפתוח סוג משימה חדש. "סוג משימה חדש:
  נסיעה", "תוסיף סוג וידאו". ב-name שם הסוג.
- pause_recurrence: המשתמש עוצר התחייבות חוזרת קיימת. "תפסיק את דוח
  המע"מ", "תשהה את הגבייה החודשית", "אין צורך יותר בתזכורת על הביטוח כל
  שנה". ב-task_text מילה או שתיים מהכותרת שלה, באותה דרך של משימות.
- resume_recurrence: המשתמש מחזיר התחייבות שהושהתה. "תחזיר את דוח המע"מ",
  "תפעיל מחדש את הגבייה". ב-task_text מילה או שתיים מהכותרת שלה. כשהמשתמש
  אומר "תחזיר אותה" — קח את הכותרת מ"השיחה עד עכשיו".
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
  דחוף ("תקפיץ להיום", "דחוף", "עכשיו"), tomorrow כשאמר מחר ("מחר",
  "מחר בבוקר", "ליום שאחרי"), later כשאמר שזה לא בוער ("מתישהו", "כשיהיה
  זמן", "בהמשך"). בלי רמז כזה — null.
  תאריך לבדו אינו רמז: "תדחה לשבוע הבא" או "עד ה-20.12" הם due_date בלבד,
  והשרת קובע את מסגרת הזמן מהתאריך בעצמו.
  שים לב: "מחר בבוקר" לבד הוא reminder_at ולא priority; תן tomorrow רק אם
  "מחר" אומר מתי לטפל במשימה ולא מתי להזכיר עליה.
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
- list_tasks או query_data? רשימה פשוטה של משימות פתוחות, של היום או
  באיחור — list_tasks. כל שאר השאלות, וכל מה שדורש ספירה, חיתוך לפי לקוח
  או מבט על ישות שאינה משימה — query_data.
- "להיום" בשאילתה הוא תמיד אותו תנאי: status = 'open' AND (priority = 'today'
  OR due_date <= התאריך של היום). משימה שתאריכה עבר נחשבת להיום גם בלי
  התיוג. "באיחור" הוא due_date < התאריך של היום.
- update_last או update_task? כשהמשתמש מתקן את מה שנשמר הרגע בלי לומר איזו
  משימה ("בעצם מחר", "זה דחוף") — update_last. כשהוא מציין משימה, במספר או
  בתיאור — update_task, גם אם היא נשמרה הרגע.
- complete_task, update_task ו-delete_task מזהים משימה באותה דרך: task_number
  כשהמשתמש נקב במספר מהרשימה, ואחרת task_text — מילה או שתיים מתוך כותרת
  המשימה כפי שהמשתמש אמר אותן, בלי "את", בלי ה"א הידיעה ובלי מילות הזמן.
  "תדחה את הביטוח לשבוע הבא" הוא task_text "ביטוח". אל תנחש כותרת מלאה.
- משימה, לקוח או פרויקט? לקוח ופרויקט נפתחים רק כשהמשתמש אמר "לקוח" או
  "פרויקט" וביקש לפתוח, להוסיף או ליצור. כל השאר — משימה.
- update_client או remember? פרטי קשר ורישום (טלפון, מייל, ח.פ, כתובת, שם,
  פעיל או לא) — update_client. עובדה על ההתנהגות או ההעדפות של הלקוח ("דני
  לא עונה לפני עשר") — remember.
- ⚠️ אם ב-add_project או ב-update_client הוזכר לקוח שאינו מופיע ברשימות —
  clarify, ושאל אם לפתוח אותו קודם. אל תיצור פרויקט בלי הלקוח שהמשתמש ציין,
  ואל תבחר לקוח אחר בשם דומה.
- pause_recurrence או delete_task? התחייבות חוזרת ("כל חודש", "החודשי",
  "השנתי", או משהו שמופיע כהתחייבות) נעצרת ב-pause_recurrence. מחיקה של
  התחייבות חוזרת נעשית בדשבורד בלבד.
- תחום, סוג משימה או לקוח? "תחום" ו"סוג משימה" נפתחים רק כשהמשתמש אמר את
  המילים האלה במפורש.
- הודעה אחת היא פעולה אחת. אם המשתמש ביקש שתיים ("לקוח חדש משה כהן ותזכיר
  לי להתקשר אליו"), בצע את הראשונה בלבד.
- כל שדה שאינו רלוונטי לפעולה שבחרת — null. יש שדות שבהם אין null לעולם:
  repeat_unit הוא "none" בכל פעולה שאינה add_recurring, ‏repeat_count,
  ‏lead_days ו-family_id הם 0, ‏requires_client הוא false, ו-sql, ‏name,
  ‏phone, ‏email, ‏tax_id, ‏address ו-active הם מחרוזת ריקה בכל פעולה שאינה
  משתמשת בהם."""


SYSTEM_PROMPT = f"{SYSTEM_PROMPT}\n\n{queries.SCHEMA_DOC}"


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
