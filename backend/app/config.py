from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://assistant:assistant@db:5432/assistant"

    # הדומיין שהדשבורד יושב עליו. ממנו נגזרת כתובת החזרה שגוגל מחזירה אליה
    domain: str = ""

    # המספר של בעל המערכת בפורמט בינלאומי בלי + (למשל 972501234567)
    owner_phone: str = ""
    # ה-LID של אותו חשבון — מזהה הפרטיות של וואטסאפ, שמנוע GOWS משתמש בו
    # בחלק מהצ'אטים במקום במספר. ריק = נשלף מ-WAHA בפעם הראשונה שצריך אותו
    owner_lid: str = ""

    waha_url: str = "http://waha:3000"
    waha_api_key: str = ""
    waha_session: str = "default"
    # המפתח שבו WAHA חותם את ה-webhook (WHATSAPP_HOOK_HMAC_KEY). ריק = הבוט לא מקבל הודעות
    waha_webhook_hmac_key: str = ""

    # --- הבוט בוואטסאפ (שלב 2א) ---
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    # עומק החשיבה של המודל: low, medium, high, xhigh, max. ברירת המחדל של Opus 5.5 היא medium
    claude_effort: str = "low"
    # ⚠️ המודל הזול שמסנן מיילים (שלב 4-2). חלוקת המודלים אינה אופציה:
    # בלי הסינון כל מייל שנכנס לתיבה היה מגיע למודל הגדול
    claude_haiku_model: str = "claude-haiku-5-5"
    # כל כמה שניות נבדקות תזכורות שהגיע זמנן
    reminder_poll_seconds: int = 30

    # --- שליפה חופשית (שלב 2ג1) ---
    # הסיסמה של משתמש הקריאה-בלבד שהמיגרציה יוצרת. ריק = השאילתות רצות
    # דרך המשתמש הרגיל, בעסקה לקריאה בלבד. בשרת זה לא אמור להישאר ריק
    bot_readonly_password: str = ""

    # --- התראות פוש (שלב 2ה) ---
    # ‏ntfy ברשת הפנימית של Docker. לא נחשף לאינטרנט אלא דרך Caddy
    ntfy_url: str = "http://ntfy"
    # שם הנושא. ריק = אין פוש, והתזכורות ממשיכות בוואטסאפ בלבד.
    # השם עצמו הוא חלק מהסוד: מי שיודע אותו יכול להירשם אליו
    ntfy_topic: str = ""
    # טוקן עם הרשאת כתיבה לנושא הזה בלבד
    ntfy_token: str = ""

    # --- חיבור גוגל (שלב 4-1) ---
    # מתוך Google Cloud Console, סוג האפליקציה "Web application".
    # ריק = הכפתור בדשבורד מושבת, ושום דבר אחר לא נשבר
    google_client_id: str = ""
    google_client_secret: str = ""
    # המפתח שבו מוצפן טוקן הרענון במסד. מחרוזת אקראית חופשית.
    # ⚠️ החלפתו פוסלת את החיבור הקיים וצריך לחבר מחדש
    google_token_key: str = ""
    # כל כמה שעות נבדק שהחיבור עדיין חי. עד פריסה 4-2 אין שום פעולה
    # אחרת שנוגעת בטוקן, ולכן בלי הבדיקה הזאת ניתוק יושב בלי שנדע
    google_check_hours: int = 24

    session_days: int = 30
    login_code_minutes: int = 5
    login_code_max_attempts: int = 5
    # האם עוגיית החיבור נשלחת רק ב-HTTPS (לכבות רק בפיתוח מקומי)
    cookie_secure: bool = True

    timezone: str = "Asia/Jerusalem"


@lru_cache
def get_settings() -> Settings:
    return Settings()
