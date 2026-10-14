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
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="RESTRICT"), nullable=False)
    task_type_id: Mapped[int | None] = mapped_column(ForeignKey("task_types.id", ondelete="RESTRICT"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    due_date: Mapped[date | None] = mapped_column(Date)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[str] = mapped_column(String(10), default="normal", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


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


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
