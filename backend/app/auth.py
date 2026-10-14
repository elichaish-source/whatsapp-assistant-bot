"""כניסה לדשבורד עם קוד חד-פעמי שנשלח ל"הודעה לעצמי" בוואטסאפ."""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuthSession, LoginCode

SESSION_COOKIE = "session"
CODE_RESEND_SECONDS = 60
CODES_PER_HOUR = 5


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime) -> datetime:
    # SQLite (בבדיקות) מחזיר זמנים בלי אזור זמן
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("0"):
        digits = "972" + digits[1:]
    return digits


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def is_owner(phone: str) -> bool:
    owner = normalize_phone(get_settings().owner_phone)
    return bool(owner) and hmac.compare_digest(phone, owner)


def create_login_code(db: Session, phone: str) -> str | None:
    """יוצר קוד חדש. מחזיר None אם נשלחו יותר מדי קודים לאחרונה."""
    settings = get_settings()
    last = db.scalar(
        select(LoginCode).where(LoginCode.phone == phone).order_by(LoginCode.created_at.desc()).limit(1)
    )
    if last and now() - aware(last.created_at) < timedelta(seconds=CODE_RESEND_SECONDS):
        return None
    recent = db.scalar(
        select(func.count())
        .select_from(LoginCode)
        .where(LoginCode.phone == phone, LoginCode.created_at > now() - timedelta(hours=1))
    )
    if recent >= CODES_PER_HOUR:
        return None

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        LoginCode(
            phone=phone,
            code_hash=_hash(f"{phone}:{code}"),
            expires_at=now() + timedelta(minutes=settings.login_code_minutes),
            created_at=now(),
        )
    )
    db.commit()
    return code


def verify_login_code(db: Session, phone: str, code: str) -> bool:
    settings = get_settings()
    entry = db.scalar(
        select(LoginCode)
        .where(LoginCode.phone == phone, LoginCode.used_at.is_(None))
        .order_by(LoginCode.created_at.desc())
        .limit(1)
    )
    if not entry or aware(entry.expires_at) < now() or entry.attempts >= settings.login_code_max_attempts:
        return False
    entry.attempts += 1
    ok = hmac.compare_digest(entry.code_hash, _hash(f"{phone}:{code.strip()}"))
    if ok:
        entry.used_at = now()
    db.commit()
    return ok


def create_session(db: Session, phone: str) -> str:
    token = secrets.token_urlsafe(32)
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
    db.add(
        AuthSession(
            token_hash=_hash(token),
            phone=phone,
            expires_at=now() + timedelta(days=get_settings().session_days),
        )
    )
    db.commit()
    return token


def delete_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == _hash(token)))
    db.commit()


def require_user(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> str:
    if session:
        entry = db.scalar(select(AuthSession).where(AuthSession.token_hash == _hash(session)))
        if entry and aware(entry.expires_at) > now() and is_owner(entry.phone):
            return entry.phone
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "נדרשת כניסה")
