from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

client_family_links = Table(
    "client_family_links",
    Base.metadata,
    Column("client_id", ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True),
    Column("family_id", ForeignKey("client_families.id", ondelete="RESTRICT"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# --- רשימות שניתנות לעריכה מהדשבורד ---


class ClientFamily(Base):
    """משפחת לקוחות: יעדים, עסק פרטי, נדל"ן..."""

    __tablename__ = "client_families"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Domain(Base):
    """תחום של משימה או פרויקט: לקוחות, כספים, שיווק ומכירות..."""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # משימה בתחום הזה חייבת להיות משויכת ללקוח
    requires_client: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class TaskType(Base):
    """סוג משימה: טלפון, פגישה, מחשב..."""

    __tablename__ = "task_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# --- ישויות ---


class Client(TimestampMixin, Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    # ת"ז של עוסק פטור או מורשה, או ח"פ של חברה ועמותה
    tax_id: Mapped[str | None] = mapped_column(String(20))
    # כתובת מלאה בשדה חופשי אחד: רחוב, יישוב ומיקוד
    address: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    families: Mapped[list[ClientFamily]] = relationship(
        secondary=client_family_links, order_by=ClientFamily.sort_order, lazy="selectin"
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint("status IN ('active', 'done')", name="project_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="RESTRICT"), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'done')", name="task_status"),
        CheckConstraint("priority IN ('low', 'normal', 'high')", name="task_priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # רשות. הבוט שומר מיד את מה שהבין, ומשימה בלי תחום מופיעה בדשבורד
    # כ"ללא תחום" ומחכה לשיוך. עדיף מלעצור את המשתמש באמצע
    domain_id: Mapped[int | None] = mapped_column(ForeignKey("domains.id", ondelete="RESTRICT"))
    task_type_id: Mapped[int | None] = mapped_column(ForeignKey("task_types.id", ondelete="RESTRICT"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    due_date: Mapped[date | None] = mapped_column(Date)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # מתי התזכורת נשלחה בוואטסאפ. מונע שליחה כפולה
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[str] = mapped_column(String(10), default="normal", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    # נוצרה מהבוט בוואטסאפ ולא מהדשבורד
    from_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # ההתחייבות החוזרת שיצרה את המשימה. ריק במשימה רגילה
    recurrence_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurrences.id", ondelete="SET NULL")
    )


# --- כניסה לדשבורד ---


class LoginCode(Base):
    __tablename__ = "login_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BotMessage(Base):
    """יומן ההודעות שהבוט טיפל בהן.

    שתי תפקידים: מונע טיפול כפול באותה הודעה (WAHA שולח את ה-webhook שוב
    כשהוא לא מקבל 200), ושומר את צריכת הטוקנים כדי שאפשר יהיה לראות עלות אמיתית.
    """

    __tablename__ = "bot_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    # מזהה ההודעה של וואטסאפ, כפי שהוא מגיע ב-payload.id
    wa_message_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(40))
    reply: Mapped[str | None] = mapped_column(Text)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    # המשימות שהוצגו בתשובה, לפי הסדר, מופרדות בפסיק. כך "סיימתי 3" יודע למה הכוונה
    listed_task_ids: Mapped[str | None] = mapped_column(Text)
    # העובדה שנרשמה לזיכרון בעקבות ההודעה, כדי ש"בטל" ידע למחוק אותה
    fact_id: Mapped[int | None] = mapped_column(ForeignKey("memory_facts.id", ondelete="SET NULL"))
    # ההתחייבות החוזרת שנרשמה בעקבות ההודעה, כדי ש"בטל" ידע לבטל אותה
    recurrence_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurrences.id", ondelete="SET NULL")
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    # בלוק הזיכרון המדויק שהוזרק לפרומפט. חובה לניפוי באגים: בלי זה
    # "למה הבוט החליט את זה?" הופך לשאלה בלי תשובה
    memory_used: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- זיכרון ארוך-טווח ---


class MemoryFact(TimestampMixin, Base):
    """עובדה אחת שהבוט יודע, במשפט אחד.

    בשלב 2ב עובדה נכנסת רק משתי דרכים ודאיות: הוראה ישירה בוואטסאפ
    ("תזכור ש…") או הקלדה בדשבורד. אין הסקה אוטומטית — היא נדחתה לשלב 6ב,
    כדי שהבוט לא ילמד שגיאות בשקט.

    שלושה שדות שמופיעים במפרט אינם כאן בכוונה: ``scope`` נגזר מ-client_id
    ומ-project_id ולכן היה כפול, ו-``confidence`` ו-``superseded_by`` משרתים
    רק הסקה. מחיקה מהדשבורד היא מחיקה אמיתית, ולא סטטוס — מה שנמחק נרשם
    ב-observations, אז שום אות ללמידה לא נאבד.
    """

    __tablename__ = "memory_facts"
    __table_args__ = (
        CheckConstraint("dimension BETWEEN 1 AND 9", name="memory_fact_dimension"),
        CheckConstraint("source IN ('bot', 'dashboard')", name="memory_fact_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # ‏1–9 לפי טבלת הממדים ב-SPEC-ASSISTANT.md, סעיף 2
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    # כששניהם ריקים העובדה היא עליך עצמך
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)


class Observation(Base):
    """יומן אירועים גולמי, לכתיבה בלבד.

    ‏⚠️ אף אחד לא קורא את הטבלה הזאת בשלב 2ב, וזה לא פספוס. היא נכתבת מהיום
    כדי שכששלב 6ב יגיע יהיה ממה להסיק דפוסים — "אתה דוחה משימות מחשב ארבע
    פעמים בממוצע" — על חודשים של היסטוריה אמיתית. בוט שרץ חצי שנה בלי לתעד
    זרק חצי שנה של למידה, ואת הזמן הזה אי אפשר לקנות בחזרה.
    """

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # task_created, task_done, task_postponed, task_reclassified, fact_added...
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # bot או dashboard
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- התחייבויות חוזרות ---


class Recurrence(TimestampMixin, Base):
    """התחייבות שחוזרת מעצמה: דוח מע"מ כל חודשיים, ביטוח כל שנה.

    נרשמת פעם אחת, ומייצרת **משימה אמיתית** בכל מחזור במקום להזיז תאריך
    באותה שורה. ככה נשמרת היסטוריה — אפשר לראות שהדוח אכן הוגש בכל מחזור,
    ושלב 6ב יוכל ללמוד איזו התחייבות אתה כל הזמן דוחה.

    התאריך הבא אינו שדה, בכוונה. הוא מחושב מ-``start_date`` ומ-``cycle``,
    ולכן אין נדידה: ‏31.1 בתוספת חודש הוא 28.2, אבל בתוספת שני חודשים הוא
    ‏31.3 ולא 28.3. שדה מתגלגל היה מאבד את ה-31 לנצח, אחרי פברואר אחד.
    """

    __tablename__ = "recurrences"
    __table_args__ = (
        CheckConstraint("interval_unit IN ('week', 'month', 'year')", name="recurrence_unit"),
        CheckConstraint("interval_count BETWEEN 1 AND 60", name="recurrence_count"),
        CheckConstraint("lead_days BETWEEN 0 AND 365", name="recurrence_lead"),
        CheckConstraint("priority IN ('low', 'normal', 'high')", name="recurrence_priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    interval_unit: Mapped[str] = mapped_column(String(10), nullable=False)
    interval_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # המחזור הראשון, והעוגן לכל החישובים הבאים
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    # כמה מחזורים כבר הפכו למשימה
    cycle: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # כמה ימים לפני התאריך להזכיר. בחידוש ביטוח זה כל העניין: ביום החידוש
    # עצמו אין יותר מה לעשות
    lead_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # הסיווג עובר כמו שהוא לכל משימה שתיווצר
    domain_id: Mapped[int | None] = mapped_column(ForeignKey("domains.id", ondelete="RESTRICT"))
    task_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_types.id", ondelete="RESTRICT")
    )
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    priority: Mapped[str] = mapped_column(String(10), default="normal", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    # כיבוי במקום מחיקה: ההתחייבות נגמרה, אבל המשימות שהיא יצרה נשארות
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    from_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
