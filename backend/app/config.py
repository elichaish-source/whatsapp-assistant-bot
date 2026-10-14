from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://assistant:assistant@db:5432/assistant"

    # המספר של בעל המערכת בפורמט בינלאומי בלי + (למשל 972501234567)
    owner_phone: str = ""

    waha_url: str = "http://waha:3000"
    waha_api_key: str = ""
    waha_session: str = "default"

    session_days: int = 30
    login_code_minutes: int = 5
    login_code_max_attempts: int = 5
    # האם עוגיית החיבור נשלחת רק ב-HTTPS (לכבות רק בפיתוח מקומי)
    cookie_secure: bool = True

    timezone: str = "Asia/Jerusalem"


@lru_cache
def get_settings() -> Settings:
    return Settings()
