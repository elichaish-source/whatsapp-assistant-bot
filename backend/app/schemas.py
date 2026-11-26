from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProjectStatus = Literal["active", "done"]
TaskStatus = Literal["open", "done"]
Priority = Literal["today", "tomorrow", "week", "later"]
# מאיפה המשימה הגיעה. הדשבורד מציג אייקון לפי זה.
# ⚠️ ``screen`` הוא הצ'אט שבמסך הוואטסאפ — אותו בוט, ערוץ אחר
TaskSource = Literal["whatsapp", "screen", "dashboard", "email", "claude"]


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


class EmailAttachmentOut(BaseModel):
    """קובץ מצורף אחד: מה שמאפשר להציג שורה **ולהוריד**.

    ⚠️⚠️ **מזהה ושם, לא תוכן.** הבייטים אינם נשמרים בשום מקום ואינם
    עוברים כאן — הם נמשכים מגוגל רק בלחיצה על ההורדה.

    ⚠️ **תמונה מוטבעת בחתימה אינה קובץ מצורף** ואינה מגיעה לכאן: היא
    מסוננת לפי ``Content-Disposition: inline`` ו-``Content-ID``, אחרי
    שנמדד בדואר אמיתי שהיא הוצגה ליד קבלה כאילו היא קובץ.
    """

    id: str
    name: str
    mime: str = ""
    size: int = 0


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
    attachments: list[EmailAttachmentOut] = []
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


# --- מסך היומן (4ב-4). ⚠️ קריאה בלבד: אין כאן שום סכימת קלט ---


class CalendarRefOut(BaseModel):
    """יומן אחד שהמסך קורא ממנו, למקרא ולצביעה.

    ⚠️ **המזהה חוזר כדי שהצבע ייקבע לפיו ולא לפי השם.** שם יומן הוא
    טקסט שהמשתמש יכול לשנות בגוגל, והמזהה הוא המפתח היציב.
    """

    id: str
    name: str
    primary: bool = False
    # ⚠️ **האם מותר לכתוב ליומן.** נגזר מההרשאה שגוגל מחזירה: חדר
    # הישיבות והחגים הם reader, ולכן המסך אינו מציג עליהם כפתור שינוי
    writable: bool = False


class CalendarEventOut(BaseModel):
    """אירוע אחד בלוח. ⚠️ **אינו נשמר בשום מקום** — נקרא מגוגל ברגע
    הבקשה, מוצג, ונזרק, בדיוק כמו מייל ב-``EmailItemOut``.

    ⚠️ **``emails`` של ``gcal.Event`` אינו כאן בכוונה.** הוא קיים בשכבת
    השירות לזיהוי הלקוח בתדריך (4ב-3), ואין לו שום שימוש בתצוגה —
    ``attendees`` הוא מה שנראה.
    """

    id: str
    title: str
    calendar: str
    calendar_id: str = ""
    # ⚠️ שם היומן מוצג רק כשזה False. אירוע משפחתי או חג שנראה כמו
    # פגישת עבודה מרוקן את ההכרעה לקרוא גם אותם
    from_primary: bool = True
    # ⚠️ אירוע של כל היום אין לו שעה בכלל, ולכן ``day`` ולא ``start``.
    # להמיר אותו ל-00:00 היה מציג חג בראש היום כאילו הוא פגישה
    all_day: bool = False
    start: datetime | None = None
    end: datetime | None = None
    day: date | None = None
    location: str = ""
    attendees: list[str] = []
    description: str = ""
    # ⚠️⚠️ **האם זה מופע של פגישה חוזרת.** המסך שואל לפיו "הפגישה הזאת
    # או כל הסדרה", וכמעט כל הפגישות ביומן האמיתי חוזרות — ולכן בלעדיו
    # כל שינוי היה חל על מופע אחד בשקט. ⚠️ מזהה הסדרה עצמו **אינו**
    # נשלח ללקוח: השרת קורא אותו מגוגל כדי שלא יהיה אפשר להצהיר עליו
    recurring: bool = False
    # חתימת הגרסה, חוזרת בעדכון כ-``If-Match``
    etag: str = ""


class CalendarPersonOut(BaseModel):
    """לקוח עם כתובת מייל, לבורר המשתתפים.

    ⚠️ **רשימת הלקוחות ולא אנשי הקשר של גוגל.** אוטוקומפליט מאנשי
    הקשר דורש הרשאת ``contacts.readonly`` ומסך אישור נוסף, ולכן הבורר
    מציע את הלקוחות שכבר במסד — ולצידו אפשר להקליד כל כתובת.
    """

    name: str
    email: str


class EventIn(BaseModel):
    """פגישה חדשה מהמסך.

    ⚠️⚠️ **``notify`` הוא האישור לשליחת הזמנה, והוא ברירת מחדל False.**
    זימון הוא הפעולה היחידה ביומן שאי אפשר לבטל: גוגל שולחת מייל בשם
    המשתמש, ומחיקת האירוע אינה מוציאה אותו מהתיבה של הנמען. לכן מוסיפים
    משתתפים בלי לשלוח, אלא אם המשתמש אישר במפורש במסך.

    ⚠️⚠️ **יום ושעות, ולא ``datetime`` מוכן.** השעה שהמשתמש הקליד היא
    שעת קיר — "11:00" — והמרתה לנקודת זמן שייכת לשרת, שהוא זה שמחזיק
    את ``Asia/Jerusalem``. אם הדפדפן היה מרכיב אותה, פגישה שנקבעת
    ממחשב באזור זמן אחר הייתה נשמרת בשעה הלא נכונה **בשקט** — בדיוק
    הלקח של ``today_local`` ב-4ב-4.
    """

    title: str = Field(min_length=1, max_length=300)
    day: date
    start_time: time
    end_time: time
    calendar_id: str = ""
    location: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=4000)
    attendees: list[str] = []
    notify: bool = False
    # ⚠️ התנגשות אינה שגיאה אלא שאלה: הפנייה הראשונה מחזירה 409 עם מה
    # שתפוס, והמשתמש מחליט. ``force`` הוא התשובה שלו
    force: bool = False

    @field_validator("end_time")
    @classmethod
    def _after_start(cls, value: time, info):
        start = info.data.get("start_time")
        if start is not None and value <= start:
            raise ValueError("הסיום חייב להיות אחרי ההתחלה")
        return value


class EventPatch(BaseModel):
    """שינוי של פגישה קיימת. ⚠️ ``None`` הוא "לא נגעת", לא "לרוקן".

    ⚠️ **זמן משתנה כיחידה אחת:** יום, שעת התחלה ושעת סיום באים יחד או
    לא באים כלל. "רק שעת הסיום" היה דורש לקרוא את ההתחלה מהמסך ולסמוך
    עליה, ושני מסכים פתוחים היו נותנים תוצאות שונות.
    """

    title: str | None = Field(default=None, max_length=300)
    day: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    attendees: list[str] | None = None
    notify: bool = False
    force: bool = False
    etag: str = ""
    calendar_id: str = ""
    # ⚠️⚠️ **"הפגישה הזאת" או "כל הסדרה".** ברירת המחדל היא המופע הבודד,
    # כי היא הפחות הרסנית — שינוי סדרה נוגע גם בפגישות שהמשתמש לא ראה
    whole_series: bool = False

    @field_validator("end_time")
    @classmethod
    def _whole_time(cls, value: time | None, info):
        given = [info.data.get("day"), info.data.get("start_time"), value]
        if any(part is not None for part in given) and not all(
            part is not None for part in given
        ):
            raise ValueError("יום, שעת התחלה ושעת סיום באים יחד")
        start = info.data.get("start_time")
        if start is not None and value is not None and value <= start:
            raise ValueError("הסיום חייב להיות אחרי ההתחלה")
        return value


class EventSaved(BaseModel):
    """תוצאת שמירה. ``invited`` אומר אם באמת יצאה הזמנה."""

    id: str
    calendar_id: str = ""
    invited: bool = False


class CalendarOut(BaseModel):
    """הטווח שנשלף, היומנים שנקראו, והאירועים.

    ⚠️ **``today`` נקבע בשרת ולא בדפדפן.** השרת הוא זה שמחזיק את
    ``Asia/Jerusalem``, ודפדפן באזור זמן אחר היה מדגיש את העמודה הלא
    נכונה — שגיאה שקטה שאי אפשר לראות בבדיקה מקומית.
    """

    start: date
    days: int
    today: date
    calendars: list[CalendarRefOut] = []
    events: list[CalendarEventOut] = []


# --- מסך הוואטסאפ: הבוט בדשבורד ---

# ⚠️ הערוץ שבו ההודעה נכתבה. **כל שורה במסך מסומנת**, אחרת המשתמש רואה
# רשימה ממוספרת מוואטסאפ בתוך המסך ומניח שהמספרים שם תקפים גם כאן
BotChannel = Literal["whatsapp", "screen"]


class BotListedTaskOut(BaseModel):
    """משימה שהוצגה בתשובה, לכפתור "סיימתי".

    ⚠️ **הנתון כבר קיים** — ``bot_messages.listed_task_ids`` הוא בדיוק
    מה ש-``_resolve_by_number`` קורא היום. המסך מרנדר את אותה עמודה
    ככפתורים במקום מספרים, ואין כאן שום דבר חדש מהמודל.
    """

    number: int
    id: int
    title: str
    status: str


class BotMessageOut(BaseModel):
    """שורה אחת ביומן ההודעות, כפי שהמסך מציג אותה."""

    id: int
    channel: BotChannel
    # הודעה שהמערכת יזמה (תזכורת, סיכום, התראה, תדריך) ולא המשתמש
    initiated: bool
    # ``body`` ריק בהודעה יוזמת — אין שם צד ששאל
    body: str | None = None
    reply: str | None = None
    intent: str | None = None
    error: str | None = None
    created_at: datetime
    handled_at: datetime | None = None
    tasks: list[BotListedTaskOut] = []
    # מזהי המיילים שהוצגו, לפי הסדר. המסך הופך אותם לקישורים למסך
    # המיילים — שם כבר יש ארכוב, מענה והפוך למשימה
    emails: list[str] = []
    # השאלה שמחכה ל"כן" בשורה הזאת, אם היא עדיין ההודעה האחרונה
    pending: str | None = None


class BotHistoryOut(BaseModel):
    messages: list[BotMessageOut] = []
    # האם יש עוד אחורה. המסך מציג כפתור "עוד"
    more: bool = False


class BotSayIn(BaseModel):
    """הודעה שנכתבה במסך.

    ⚠️⚠️ **היא נענית במסך בלבד ואינה יוצאת בוואטסאפ.** אחרת וואטסאפ
    מתמלא בהדים של עבודה שנעשתה במסך.
    """

    body: str = Field(min_length=1, max_length=1000)


class BotStatusOut(BaseModel):
    """מצב החיבור לוואטסאפ, כפי ש-WAHA מדווחת אותו.

    ``state`` הוא ``connected`` / ``scan`` / ``failed`` / ``starting`` /
    ``unknown``, ו-``unreachable`` אומר שהשרת שלנו לא הצליח להגיע
    ל-WAHA בכלל — ⚠️ זה שונה מ"וואטסאפ ניתקה אותנו".
    """

    state: str
    raw: str = ""
    phone: str = ""
    message: str = ""


class BotPendingOut(BaseModel):
    """פעולה שהבוט שאל עליה ולא אושרה בזמן.

    ⚠️⚠️ **היום זה מתאדה בשקט**: ביקשת למחוק, לא ענית "כן" בתוך רבע
    שעה, ושום דבר לא נמחק ושום דבר לא אמר לך.
    """

    id: int
    channel: BotChannel
    created_at: datetime
    # מה הבוט שאל, כפי שנשלח. זה מה שהמשתמש מזהה
    question: str
    # תיאור קצר של הפעולה עצמה, מתוך ``pending_json``
    summary: str
    kind: str
    # האם עדיין אפשר לבצע אותה. פעולה שהפריט שלה כבר לא קיים יורדת
    executable: bool = True
