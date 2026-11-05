from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://assistant:assistant@db:5432/assistant"

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
    # כל כמה שניות נבדקות תזכורות שהגיע זמנן
    reminder_poll_seconds: int = 30

    # --- שליפה חופשית (שלב 2ג1) ---
    # הסיסמה של משתמש הקריאה-בלבד שהמיגרציה יוצרת. ריק = השאילתות רצות
    # דרך המשתמש הרגיל, בעסקה לקריאה בלבד. בשרת זה לא אמור להישאר ריק
    bot_readonly_password: str = ""

    session_days: int = 30
    login_code_minutes: int = 5
    login_code_max_attempts: int = 5
    # האם עוגיית החיבור נשלחת רק ב-HTTPS (לכבות רק בפיתוח מקומי)
    cookie_secure: bool = True

    timezone: str = "Asia/Jerusalem"


@lru_cache
def get_settings() -> Settings:
    return Settings()
