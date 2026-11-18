"""החיבור לחשבון הגוגל: מסך האישור, הטוקנים, והאם החיבור עדיין חי.

המודול הזה לא קורא מיילים ולא נוגע ביומן — הוא רק מחזיק את הגישה. מה
שעושים איתה מגיע בפריסות 4-2 והלאה, שישתמשו ב-``access_token()``.

**למה ההרשאות האלה ולא אחרות.** ``gmail.modify`` נותן קריאה, ארכוב
ושליחה גם יחד — התיעוד של ``users.messages.send`` מונה אותו כאחד
מהמתאימים, ולכן ``gmail.send`` מיותר. ‏⚠️ **``https://mail.google.com/``
לא מבוקש בכוונה.** היא ההרשאה היחידה שמוחקת לצמיתות, ובלעדיה הבוט טכנית
אינו יכול למחוק מייל גם אם יטעה. הרשאות היומן נכללות כבר עכשיו אף שהן
משמשות רק בשלב 4ב, כי הוספת הרשאה בהמשך מחייבת לעבור שוב את כל מסך
האישור.

**המצב באפליקציה הוא "In production" ולא "Testing".** ב-Testing גוגל
פוסלת את טוקן הרענון אחרי שבעה ימים, וזה פוסל בוט שאמור לרוץ לבד.
המחיר הוא מסך "האפליקציה לא אומתה" בכל חיבור, ואותו עוקפים ידנית.

‏⚠️ גם ב-"In production" החיבור יכול להתנתק מעצמו: ביטול גישה, חצי שנה
בלי שימוש, **החלפת סיסמת הגוגל** (כי יש כאן הרשאה מוגבלת), או טוקן
חמישים-ומשהו שדוחק טוקן ישן. לכן יש בדיקה תקופתית והודעה אחת בוואטסאפ.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto, waha
from .auth import aware, now
from .config import get_settings
from .models import GoogleCredential

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"

SCOPES = (
    # קריאה, ארכוב ושליחה. ללא מחיקה לצמיתות — זו הרשאה אחרת שלא מבוקשת
    "https://www.googleapis.com/auth/gmail.modify",
    # ‏4ב: יצירה ושינוי של אירועים, וקריאה של רשימת היומנים
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
)

# כמה זמן תקף ה-state שנשלח לגוגל. מסך האישור לוקח דקה, ורבע שעה
# מספיקה גם למי שעצר באמצע לקרוא מה הוא מאשר
STATE_MINUTES = 15
# שוליים לפני פקיעת טוקן הגישה. בלעדיהם בקשה שיוצאת שנייה לפני הזמן נכשלת
EXPIRY_MARGIN = timedelta(seconds=120)
# אחרי תקלת רשת לא בודקים שוב מיד, אבל גם לא מחכים יממה
RETRY_AFTER_ERROR = timedelta(hours=1)
TIMEOUT = 20

# מתי מותר לנסות שוב אחרי תקלה זמנית. בזיכרון בלבד: זו אינה עובדה על
# החיבור אלא על הרגע, ואין טעם לשמור אותה בין הפעלות
_retry_at: datetime | None = None


class GoogleError(Exception):
    """תקלה זמנית: רשת, או תשובה לא צפויה מגוגל. שווה לנסות שוב."""


class GoogleDisconnected(Exception):
    """גוגל פסלה את טוקן הרענון. אין מה לנסות — צריך לחבר מחדש."""


# --- הגדרה ---


def configured() -> bool:
    """בלי שלושת המפתחות אין חיבור, והמערכת כולה ממשיכה לעבוד בלעדיו."""
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret and s.google_token_key and s.domain)


def redirect_uri() -> str:
    """‏⚠️ חייבת להיות זהה **תו בתו** למה שרשום ב-Google Cloud Console."""
    return f"https://{get_settings().domain}/api/google/callback"


# --- ה-state, ההגנה מפני זיוף ---


def _sign(value: str) -> str:
    key = get_settings().google_token_key.encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:32]


def make_state() -> str:
    """חתימה על חותמת זמן, במקום טבלה של state-ים פתוחים.

    מה שצריך למנוע הוא שמישהו יגרור את המשתמש לכתובת החזרה עם קוד משלו
    ויחבר את החשבון שלו לדשבורד. חתימה שרק השרת יכול לייצר מספיקה לזה,
    ואין צורך בשורה במסד שמישהו יצטרך גם לנקות.
    """
    stamp = str(int(time.time()))
    return f"{stamp}.{_sign(stamp)}"


def valid_state(state: str) -> bool:
    """‏⚠️ הצורה נבדקת לפני ההשוואה. ``hmac.compare_digest`` מרים TypeError
    על מחרוזת שאינה ASCII, וזיוף בעברית היה מחזיר 500 במקום הפניה נקייה.
    """
    stamp, _, sig = (state or "").partition(".")
    if not stamp.isdigit() or len(sig) != 32 or not all(c in "0123456789abcdef" for c in sig):
        return False
    if not hmac.compare_digest(sig, _sign(stamp)):
        return False
    return time.time() - int(stamp) <= STATE_MINUTES * 60


def auth_url() -> str:
    """הכתובת שאליה שולחים את הדפדפן כדי לאשר.

    ``access_type=offline`` הוא מה שמחזיר טוקן רענון, ו-``prompt=consent``
    מבטיח שנקבל אותו גם בחיבור חוזר — בלעדיו גוגל מחזירה טוקן גישה בלבד
    למי שכבר אישר פעם, והחיבור היה שורד שעה אחת.
    """
    params = httpx.QueryParams(
        {
            "client_id": get_settings().google_client_id,
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": make_state(),
        }
    )
    return f"{AUTH_URL}?{params}"


# --- שיחה מול גוגל ---


def _post_token(data: dict) -> dict:
    try:
        resp = httpx.post(TOKEN_URL, data=data, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise GoogleError(f"גוגל לא נענתה: {exc}") from exc
    if resp.status_code >= 400:
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        error = str(body.get("error", "")) or f"HTTP {resp.status_code}"
        # ‏invalid_grant פירושו שטוקן הרענון נפסל. כל שאר השגיאות עשויות לחלוף
        if error == "invalid_grant":
            raise GoogleDisconnected(str(body.get("error_description") or error))
        raise GoogleError(error)
    try:
        return resp.json()
    except ValueError as exc:
        raise GoogleError("תשובה לא תקינה מגוגל") from exc


def exchange_code(code: str) -> dict:
    s = get_settings()
    return _post_token(
        {
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        }
    )


def fetch_email(token: str) -> str:
    """כתובת התיבה, דרך פרופיל Gmail ולא דרך הרשאת פרופיל נפרדת.

    זה חוסך לבקש ``openid``/``email`` במסך האישור, וגם מוכיח שההרשאה
    של Gmail באמת ניתנה — תשובה כאן היא בדיקת החיבור האמיתית.
    """
    try:
        resp = httpx.get(PROFILE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        resp.raise_for_status()
        return str(resp.json().get("emailAddress") or "")
    except (httpx.HTTPError, ValueError):
        log.warning("לא הצלחתי לקרוא את כתובת התיבה מגוגל")
        return ""


# --- השורה במסד ---


def get_credential(db: Session) -> GoogleCredential | None:
    return db.scalar(select(GoogleCredential).order_by(GoogleCredential.id).limit(1))


def save_tokens(db: Session, tokens: dict) -> GoogleCredential:
    """שומר את תוצאת מסך האישור. מחליף חיבור קיים, אם יש.

    ‏⚠️ ``scopes`` נשמר ממה שגוגל **נתנה** (``scope`` בתשובה) ולא ממה
    שביקשנו: במסך האישור אפשר להוריד סימון, ואז פעולה עתידית נכשלת
    ואנחנו רוצים לראות במסך מה חסר במקום לנחש.
    """
    refresh = str(tokens.get("refresh_token") or "")
    cred = get_credential(db)
    if not refresh:
        # קורה רק אם prompt=consent לא נשלח. שומרים על הטוקן הקיים
        if cred is None or not cred.refresh_token_enc:
            raise GoogleError("גוגל לא החזירה טוקן רענון")
        refresh = crypto.decrypt(cred.refresh_token_enc)

    access = str(tokens.get("access_token") or "")
    if cred is None:
        cred = GoogleCredential(refresh_token_enc="")
        db.add(cred)

    cred.refresh_token_enc = crypto.encrypt(refresh)
    cred.access_token_enc = crypto.encrypt(access)
    cred.access_expires_at = now() + timedelta(seconds=int(tokens.get("expires_in") or 0))
    cred.scopes = str(tokens.get("scope") or "")
    cred.status = "connected"
    cred.last_error = ""
    cred.last_checked_at = now()
    cred.disconnected_notified_at = None
    cred.email = fetch_email(access) or cred.email
    db.commit()
    db.refresh(cred)
    return cred


def missing_scopes(cred: GoogleCredential) -> list[str]:
    """הרשאות שביקשנו וגוגל לא נתנה. ריק = הכול אושר."""
    granted = set((cred.scopes or "").split())
    return [s for s in SCOPES if s not in granted]


# --- טוקן גישה חי ---


def _refresh(db: Session, cred: GoogleCredential) -> str:
    s = get_settings()
    tokens = _post_token(
        {
            "refresh_token": crypto.decrypt(cred.refresh_token_enc),
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "grant_type": "refresh_token",
        }
    )
    access = str(tokens.get("access_token") or "")
    if not access:
        raise GoogleError("גוגל לא החזירה טוקן גישה")
    cred.access_token_enc = crypto.encrypt(access)
    cred.access_expires_at = now() + timedelta(seconds=int(tokens.get("expires_in") or 0))
    # ‏גוגל לא מחזירה scope בכל רענון, ולכן מעדכנים רק כשכן
    if tokens.get("scope"):
        cred.scopes = str(tokens["scope"])
    db.commit()
    return access


def access_token(db: Session) -> str:
    """טוקן גישה תקף, מרוענן אם צריך. נקודת הכניסה של פריסות 4-2 והלאה."""
    cred = get_credential(db)
    if cred is None:
        raise GoogleDisconnected("גוגל לא מחוברת")
    token = crypto.decrypt(cred.access_token_enc)
    if token and cred.access_expires_at and aware(cred.access_expires_at) - EXPIRY_MARGIN > now():
        return token
    return _refresh(db, cred)


# --- הבדיקה התקופתית ---


def _due(cred: GoogleCredential, moment: datetime) -> bool:
    if _retry_at and moment < _retry_at:
        return False
    if cred.last_checked_at is None:
        return True
    hours = get_settings().google_check_hours
    return aware(cred.last_checked_at) <= moment - timedelta(hours=hours)


def check(db: Session, moment: datetime, force: bool = False) -> GoogleCredential | None:
    """מרענן את הטוקן כדי לראות שהחיבור חי. מחזיר את השורה אם נבדקה.

    עד פריסה 4-2 אף אחד לא נוגע בטוקן, ולכן בלי הבדיקה הזאת ניתוק היה
    מתגלה רק בחודש הבא כשמישהו ינסה לקרוא מייל.

    תקלת רשת אינה ניתוק: היא לא משנה את המצב, רק דוחה את הניסיון הבא.
    """
    global _retry_at
    cred = get_credential(db)
    if cred is None or not configured():
        return None
    if not force and (cred.status != "connected" or not _due(cred, moment)):
        return None

    try:
        _refresh(db, cred)
    except GoogleDisconnected as exc:
        log.warning("החיבור לגוגל נותק: %s", exc)
        cred.status = "disconnected"
        cred.last_error = str(exc)
    except (GoogleError, crypto.CryptoError) as exc:
        _retry_at = moment + RETRY_AFTER_ERROR
        log.warning("בדיקת החיבור לגוגל נכשלה זמנית: %s", exc)
        return None
    else:
        _retry_at = None
        cred.status = "connected"
        cred.last_error = ""
        cred.disconnected_notified_at = None

    cred.last_checked_at = moment
    db.commit()
    return cred


def announce_disconnect(db: Session, cred: GoogleCredential) -> bool:
    """הודעה אחת בוואטסאפ על ניתוק. מחזיר True אם נשלחה עכשיו.

    ‏⚠️ פעם אחת בלבד, לכן ``disconnected_notified_at``. בלעדיו הלולאה
    הייתה שולחת את אותה הודעה בכל סבב, וזה בדיוק מה שמלמד להתעלם.
    """
    if cred.status != "disconnected" or cred.disconnected_notified_at is not None:
        return False
    phone = get_settings().owner_phone
    if not phone:
        return False
    try:
        waha.send_text(
            phone,
            "החיבור לגוגל נותק ואני כבר לא רואה את המייל.\n"
            "אפשר לחבר מחדש בדשבורד, בהגדרות ← חיבור לגוגל.",
        )
    except waha.WahaError:
        # לא מסמנים כנשלח, כדי שהסבב הבא ינסה שוב
        log.exception("ההודעה על ניתוק גוגל לא יצאה")
        return False
    cred.disconnected_notified_at = now()
    db.commit()
    return True


def disconnect(db: Session) -> bool:
    """ניתוק יזום: מבטל את הגישה אצל גוגל ומוחק את השורה.

    הביטול אצל גוגל הוא מאמץ בלבד. אם הוא נכשל עדיין מוחקים כאן — אחרת
    המשתמש לוחץ "נתק", לא קורה כלום, ואין לו דרך להתקדם.
    """
    cred = get_credential(db)
    if cred is None:
        return False
    try:
        token = crypto.decrypt(cred.refresh_token_enc)
    except crypto.CryptoError:
        token = ""
    if token:
        try:
            httpx.post(REVOKE_URL, data={"token": token}, timeout=TIMEOUT)
        except httpx.HTTPError:
            log.warning("ביטול הגישה מול גוגל נכשל. השורה נמחקת בכל זאת")
    db.delete(cred)
    db.commit()
    return True
