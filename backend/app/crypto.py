"""הצפנה סימטרית לערכים שנשמרים במסד ואסור שיישבו שם כטקסט גלוי.

נכון לעכשיו זה טוקן הרענון של גוגל. הוא שווה ערך לסיסמה: מי שמחזיק בו
יכול לקרוא את כל התיבה עד שהחיבור יבוטל, ולכן גיבוי של בסיס הנתונים —
שנשמר כקובץ רגיל בתיקייה ``backups/`` — לא יכיל אותו כטקסט.

‏⚠️ המפתח אינו במסד אלא ב-``.env`` בלבד (``GOOGLE_TOKEN_KEY``). זה כל
העניין: גיבוי שדלף בלי הקובץ הזה הוא חסר ערך. **החלפת המפתח פוסלת את
הטוקנים הקיימים** וצריך לחבר את גוגל מחדש — אין כאן גיבוי שני.

המפתח ב-``.env`` הוא מחרוזת חופשית (``openssl rand -hex 32``) ולא מפתח
‏Fernet בפורמט שלו. הגזירה ל-32 בתים נעשית כאן, כדי שהמשתמש לא יצטרך
להריץ פייתון על השרת רק כדי לייצר ערך — שאר הסודות בקובץ נוצרים כולם
באותה פקודה, וחריג אחד הוא בדיוק מה שנשכח.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


class CryptoError(Exception):
    pass


def configured() -> bool:
    return bool(get_settings().google_token_key)


def _fernet() -> Fernet:
    key = get_settings().google_token_key
    if not key:
        raise CryptoError("GOOGLE_TOKEN_KEY לא מוגדר")
    # ‏Fernet דורש בדיוק 32 בתים בבסיס 64 בטוח-לכתובת. ‏SHA-256 נותן 32
    # בתים מכל קלט, ולכן כל מחרוזת ב-.env עובדת ואין פורמט לטעות בו
    digest = hashlib.sha256(key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    """מחרוזת ריקה נשארת ריקה, כדי ששדה בלי ערך לא ייראה כמו ערך מוצפן."""
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """‏⚠️ מרים CryptoError כשהמפתח הוחלף, ולא מחזיר מחרוזת ריקה בשקט.

    ערך ריק הוא "אין טוקן" ומוביל לחיבור מחדש; פענוח שנכשל הוא תקלת
    הגדרה, ומי שבולע אותה מקבל "החיבור נותק" במקום "המפתח השתנה".
    """
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise CryptoError("פענוח נכשל — ‏GOOGLE_TOKEN_KEY כנראה שונה") from exc
