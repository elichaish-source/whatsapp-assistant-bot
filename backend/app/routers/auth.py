import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from .. import auth, waha
from ..config import get_settings
from ..db import get_db
from ..schemas import MeOut, RequestCodeIn, VerifyCodeIn

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/request-code")
def request_code(body: RequestCodeIn, db: Session = Depends(get_db)) -> dict:
    phone = auth.normalize_phone(body.phone)
    # תשובה זהה לכל מספר, כדי לא לחשוף איזה מספר רשום
    if auth.is_owner(phone):
        code = auth.create_login_code(db, phone)
        if code:
            try:
                waha.send_text(phone, f"קוד הכניסה שלך לדשבורד: {code}\nתקף ל-{get_settings().login_code_minutes} דקות.")
            except waha.WahaError:
                log.exception("שליחת קוד דרך WAHA נכשלה")
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, "שליחת הקוד בוואטסאפ נכשלה. בדוק ש-WAHA מחובר.")
    return {"ok": True}


@router.post("/verify")
def verify(body: VerifyCodeIn, response: Response, db: Session = Depends(get_db)) -> MeOut:
    phone = auth.normalize_phone(body.phone)
    if not auth.is_owner(phone) or not auth.verify_login_code(db, phone, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "קוד שגוי או שפג תוקפו")
    settings = get_settings()
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.create_session(db, phone),
        max_age=settings.session_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return MeOut(phone=phone)


@router.post("/logout")
def logout(
    response: Response,
    session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> dict:
    if session:
        auth.delete_session(db, session)
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(phone: str = Depends(auth.require_user)) -> MeOut:
    return MeOut(phone=phone)
