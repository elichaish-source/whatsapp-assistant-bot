"""חיבור חשבון הגוגל מהדשבורד: התחלה, חזרה מגוגל, מצב וניתוק.

כתובת החזרה יושבת כאן, תחת ``/api/google/callback``, ולא במסך של React:
גוגל מחזירה קוד חד-פעמי שחייב להיות מוחלף בטוקן **בצד השרת**, כי ההחלפה
דורשת את ``client_secret``. קוד שהיה עובר דרך הדפדפן היה גם נרשם
בהיסטוריה שלו.

‏⚠️ ``callback`` אינו תלוי ב-``require_user`` אף שהוא מחייב כניסה: שגיאה
‏401 כאן הייתה מגיעה למשתמש כ-JSON ערום באמצע זרימת התחברות. במקום זה
הוא מחזיר את המשתמש למסך ההגדרות עם קוד שגיאה, והמסך אומר מה קרה בעברית.
"""

import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import crypto, gauth
from ..auth import SESSION_COOKIE, now, require_user, session_phone
from ..db import get_db
from ..schemas import GoogleStatusOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/google", tags=["google"])

# לאן חוזרים אחרי מסך האישור. ``google`` הוא קוד שהמסך מתרגם לעברית
SETTINGS = "/settings"


def _back(code: str) -> RedirectResponse:
    # ‏303 ולא 302: הדפדפן חייב לעבור ל-GET, והכתובת עם הקוד של גוגל
    # לא צריכה להישאר בהיסטוריה כיעד שאפשר לרענן
    return RedirectResponse(f"{SETTINGS}?google={code}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/status", response_model=GoogleStatusOut, dependencies=[Depends(require_user)])
def get_status(db: Session = Depends(get_db)) -> GoogleStatusOut:
    cred = gauth.get_credential(db)
    if cred is None:
        return GoogleStatusOut(configured=gauth.configured(), connected=False)
    return GoogleStatusOut(
        configured=gauth.configured(),
        connected=cred.status == "connected",
        email=cred.email,
        status=cred.status,
        last_error=cred.last_error,
        connected_at=cred.created_at,
        last_checked_at=cred.last_checked_at,
        missing_scopes=gauth.missing_scopes(cred),
    )


@router.post("/connect", dependencies=[Depends(require_user)])
def connect() -> dict:
    """מחזיר את כתובת מסך האישור. הדפדפן עובר אליה בעצמו.

    הפניה אמיתית (307) לא הייתה עובדת כאן: הקריאה מגיעה מ-``fetch``,
    והדפדפן היה עוקב אחריה ברקע במקום לנווט את הדף.
    """
    if not gauth.configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "חיבור גוגל לא מוגדר בשרת. חסרים מפתחות ב-.env",
        )
    return {"url": gauth.auth_url()}


@router.get("/callback")
def callback(
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> RedirectResponse:
    """החזרה ממסך האישור של גוגל."""
    if not gauth.configured():
        return _back("config")
    # העוגייה מגיעה גם כאן, כי זו ניווט ברמת הדף (SameSite=lax)
    if session_phone(db, session) is None:
        return _back("auth")
    if error or not code:
        # ``access_denied`` = המשתמש לחץ "ביטול", וזו לא תקלה
        return _back("denied")
    if not state or not gauth.valid_state(state):
        log.warning("חזרה מגוגל עם state לא תקין")
        return _back("state")

    try:
        tokens = gauth.exchange_code(code)
        cred = gauth.save_tokens(db, tokens)
    except (gauth.GoogleError, gauth.GoogleDisconnected, crypto.CryptoError) as exc:
        log.warning("החלפת הקוד מגוגל נכשלה: %s", exc)
        return _back("exchange")
    return _back("partial" if gauth.missing_scopes(cred) else "ok")


@router.post("/check", response_model=GoogleStatusOut, dependencies=[Depends(require_user)])
def check_now(db: Session = Depends(get_db)) -> GoogleStatusOut:
    """בדיקה לפי בקשה, בלי לחכות לבדיקה התקופתית."""
    gauth.check(db, now(), force=True)
    return get_status(db)


@router.post("/disconnect", dependencies=[Depends(require_user)])
def disconnect(db: Session = Depends(get_db)) -> dict:
    return {"ok": gauth.disconnect(db)}
