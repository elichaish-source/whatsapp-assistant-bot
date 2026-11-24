from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProjectStatus = Literal["active", "done"]
TaskStatus = Literal["open", "done"]
Priority = Literal["today", "tomorrow", "week", "later"]
# מאיפה המשימה הגיעה. הדשבורד מציג אייקון לפי זה
TaskSource = Literal["whatsapp", "dashboard", "email", "claude"]


def _blank_to_none(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- רשימות ---


class LookupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("שם לא יכול להיות ריק")
        return v


class LookupOut(ORMModel):
    id: int
    name: str
    sort_order: int


class DomainIn(LookupIn):
    requires_client: bool = False


class DomainOut(LookupOut):
    requires_client: bool


# --- לקוחות ---


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = None
    email: str | None = None
    tax_id: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=300)
    notes: str | None = None
    is_active: bool = True
    family_ids: list[int] = []

    _clean = field_validator("phone", "email", "tax_id", "address", "notes", mode="before")(_blank_to_none)


class ClientOut(ORMModel):
    id: int
    name: str
    phone: str | None
    email: str | None
    tax_id: str | None
    address: str | None
    notes: str | None
    is_active: bool
    families: list[LookupOut]
    open_tasks: int = 0
    created_at: datetime


# --- פרויקטים ---


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain_id: int
    client_id: int | None = None
    description: str | None = None
    due_date: date | None = None
    status: ProjectStatus = "active"

    _clean = field_validator("description", mode="before")(_blank_to_none)


class ProjectOut(ORMModel):
    id: int
    name: str
    domain_id: int
    client_id: int | None
    description: str | None
    due_date: date | None
    status: ProjectStatus
    open_tasks: int = 0
    created_at: datetime


# --- משימות ---


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    status: TaskStatus = "open"
    # אם לא נשלח ויש פרויקט, התחום נלקח מהפרויקט
    domain_id: int | None = None
    task_type_id: int | None = None
    client_id: int | None = None
    project_id: int | None = None
    due_date: date | None = None
    reminder_at: datetime | None = None
    priority: Priority = "week"
    notes: str | None = None
    # המייל שממנו נוצרה המשימה (שלב 4-5). ⚠️ מזהה בלבד ולא תוכן, ומה
    # שנשמר בכותרת ובהערות הוא מה שהמשתמש אישר בטופס
    email_message_id: str | None = Field(default=None, max_length=100)

    _clean = field_validator("notes", mode="before")(_blank_to_none)


class TaskOut(ORMModel):
    id: int
    title: str
    status: TaskStatus
    done_at: datetime | None
    domain_id: int | None
    task_type_id: int | None
    client_id: int | None
    project_id: int | None
    due_date: date | None
    reminder_at: datetime | None
    priority: Priority
    notes: str | None
    source: TaskSource
    # ריק בכל משימה שלא נוצרה ממייל. ממנו נבנה הקישור חזרה לג'ימייל
    email_message_id: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskStatusIn(BaseModel):
    status: TaskStatus


class TaskPriorityIn(BaseModel):
    priority: Priority


# --- כניסה ---


class RequestCodeIn(BaseModel):
    phone: str


class VerifyCodeIn(BaseModel):
    phone: str
    code: str


class MeOut(BaseModel):
    phone: str


# --- זיכרון ---


class MemoryFactIn(BaseModel):
    # הממד הוא 1–9 לפי טבלת הממדים ב-SPEC-ASSISTANT.md, סעיף 2
    dimension: int = Field(ge=1, le=9)
    content: str = Field(min_length=1, max_length=1000)
    client_id: int | None = None
    project_id: int | None = None

    @field_validator("content")
    @classmethod
    def squeeze_content(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("תוכן לא יכול להיות ריק")
        return v


class MemoryFactOut(ORMModel):
    id: int
    dimension: int
    content: str
    client_id: int | None
    project_id: int | None
    source: str
    created_at: datetime
    updated_at: datetime


class DimensionOut(BaseModel):
    id: int
    name: str
    # האם עובדות בממד הזה נשלחות לבוט בשלב הנוכחי
    in_prompt: bool


# --- התחייבויות חוזרות ---

RepeatUnit = Literal["week", "month", "year"]


class RecurrenceIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    interval_unit: RepeatUnit
    interval_count: int = Field(default=1, ge=1, le=60)
    # המחזור הראשון, וגם העוגן שממנו מחושבים כל הבאים
    start_date: date
    lead_days: int = Field(default=0, ge=0, le=365)
    domain_id: int | None = None
    task_type_id: int | None = None
    client_id: int | None = None
    project_id: int | None = None
    priority: Priority = "week"
    notes: str | None = None
    active: bool = True

    _clean = field_validator("notes", mode="before")(_blank_to_none)


class RecurrenceOut(ORMModel):
    id: int
    title: str
    interval_unit: RepeatUnit
    interval_count: int
    start_date: date
    cycle: int
    lead_days: int
    domain_id: int | None
    task_type_id: int | None
    client_id: int | None
    project_id: int | None
    priority: Priority
    notes: str | None
    active: bool
    from_bot: bool
    # שלושת אלה מחושבים ואינם עמודות: התאריך הבא, תיאור התדירות בעברית,
    # והמשימה הפתוחה של המחזור הנוכחי — אם יש כזאת
    next_due: date | None = None
    every: str = ""
    open_task_id: int | None = None


# --- חיבור גוגל (שלב 4-1) ---


class GoogleStatusOut(BaseModel):
    """מה שמסך "חיבור לגוגל" בהגדרות צריך לדעת.

    ‏``configured`` הוא על השרת ולא על החשבון: בלי שלושת המפתחות ב-.env
    אין בכלל מה ללחוץ, וזה שונה מ"מוגדר אבל לא מחובר".
    """

    configured: bool
    connected: bool
    email: str = ""
    status: str = ""
    last_error: str = ""
    connected_at: datetime | None = None
    last_checked_at: datetime | None = None
    # הרשאות שביקשנו והמשתמש לא אישר. ריק = הכול תקין
    missing_scopes: list[str] = []


# --- מסך המיילים (שלב 4-3) ---


class EmailItemOut(BaseModel):
    """מייל אחד בשורת הרשימה. ⚠️ **אינו נשמר בשום מקום** — נקרא מגוגל
    ברגע הבקשה, מוצג, ונזרק. ``line`` הוא תיאור שנכתב על ידי המודל הזול.
    """

    id: str
    thread_id: str = ""
    sender: str
    sender_email: str = ""
    subject: str
    line: str = ""
    received_at: datetime
    important: bool
    # סומן חשוב בקוד ולא במודל, כי הכתובת רשומה בכרטיס לקוח
    is_client: bool = False
    unread: bool = False
    has_attachments: bool = False
    # ⚠️ מחכה לתשובה בכתב. שונה מ-important: חשבונית חשובה, אבל עונים
    # עליה בתשלום ולא במילים. זה גם מי שמקבל טיוטת מענה מוכנה מראש
    needs_reply: bool = False
    # כמה הודעות יש בשרשור שהשורה מייצגת. ⚠️ מוצג למשתמש, כדי ששורה
    # שמאחוריה שתי הודעות לא תיראה כאילו אחת מהן נעלמה
    thread_count: int = 1
    # ⚠️ כל ההודעות של השרשור שנמצאות בדואר הנכנס. **זה מה שהמסך שולח
    # לארכוב**, ולא ``id`` לבדו — אחרת הודעה ישנה בשרשור נשארת בדואר
    # הנכנס והשורה חוזרת ברענון הבא
    thread_ids: list[str] = []


class EmailListOut(BaseModel):
    """הרשימה, ושני המונים שהמסך מציג בלשוניות הסינון."""

    scope: str
    items: list[EmailItemOut] = []
    important: int = 0
    other: int = 0
    # האם נגענו בתקרת השליפה. המסך אומר את זה למשתמש
    truncated: bool = False


class EmailIdsIn(BaseModel):
    """המיילים שעליהם פועלים: שרשור אחד, או כל הלא-חשובים יחד.

    ⚠️ **המזהים מגיעים מהמסך ואינם מחושבים מחדש בשרת.** אחרת מייל
    שנכנס בין הטעינה ללחיצה היה מתארכב בלי שהמשתמש ראה אותו.
    """

    ids: list[str] = Field(min_length=1, max_length=1000)


class EmailIdsOut(BaseModel):
    """מה שהוצא בפועל. המסך שומר את זה, ושולח אותו חזרה בביטול."""

    ids: list[str] = []


class EmailBodyOut(BaseModel):
    """המייל המלא לקריאה במסך, בלי ההיסטוריה המצוטטת."""

    id: str
    thread_id: str = ""
    sender: str
    sender_email: str = ""
    to: str = ""
    subject: str
    received_at: datetime
    body: str
    attachments: list[str] = []
    quoted_removed: bool = False


class TaskDraftOut(BaseModel):
    """הצעה למשימה ממייל (שלב 4-5). ⚠️ **אינה נשמרת** — הטופס נפתח
    מלא מראש, והמשימה נוצרת רק בלחיצה על "שמור"."""

    title: str
    due_date: date | None = None
    # לפי כתובת השולח מול כרטיסי הלקוחות. ⚠️ נקבע בקוד ולא במודל
    client_id: int | None = None
    notes: str = ""
    email_message_id: str = ""


class ReplyOptionOut(BaseModel):
    """הצעת ניסוח. ⚠️ **אינה נשלחת** — המשתמש עורך, מאשר ושולח."""

    label: str = ""
    text: str


class ReplyDraftOut(BaseModel):
    """מה שהמסך צריך כדי להציע תשובה: לאן היא תצא, ומה אפשר לכתוב.

    ⚠️ **הנמען נגזר בשרת מהמייל המקורי**, והמסך רק מציג אותו.
    """

    to: str
    subject: str
    options: list[ReplyOptionOut] = []
    # ⚠️ מתי ההצעות הוכנו, כשהוכנו מראש. ריק = נוסחו עכשיו. מוצג
    # למשתמש, כדי שידע שהוא קורא טקסט שנכתב לפני כמה שעות
    prepared_at: datetime | None = None


class ReplyIn(BaseModel):
    """גוף התשובה. ⚠️ **הנמען אינו כאן בכוונה** — הוא נקרא בשרת מהמייל
    המקורי, אחרת היה אפשר לגרום למסך לשלוח לכל כתובת."""

    body: str = Field(min_length=1, max_length=20000)


class ReplySentOut(BaseModel):
    """מה יצא ולאן, כדי שהמסך יאמר למשתמש בדיוק מה קרה."""

    to: str
    subject: str
    archived: bool = False
