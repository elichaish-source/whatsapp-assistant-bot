import os

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if not TEST_DB:
    pytest.skip("TEST_DATABASE_URL לא מוגדר", allow_module_level=True)

os.environ["DATABASE_URL"] = TEST_DB
os.environ["OWNER_PHONE"] = "972501234567"
os.environ["OWNER_LID"] = "111222333444555"
os.environ["COOKIE_SECURE"] = "false"
os.environ["WAHA_WEBHOOK_HMAC_KEY"] = "test-hmac-key"
# ללא מפתח Claude, כך שאף בדיקה לא תקרא ל-API בתשלום
os.environ["ANTHROPIC_API_KEY"] = ""

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import notify, waha  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

OWNER = "972501234567"


@pytest.fixture(scope="session", autouse=True)
def migrated():
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_db():
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE bot_messages, observations, memory_facts, tasks, recurrences, projects,"
                " client_family_links, clients,"
                " login_codes, auth_sessions RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(waha, "send_text", lambda phone, body: messages.append((phone, body)))
    return messages


@pytest.fixture
def pushed(monkeypatch):
    """תופס את התראות הפוש. לא autouse: בלי נושא מוגדר אין פוש בכלל."""
    calls = []
    monkeypatch.setattr(
        notify,
        "send",
        lambda message, title, click=None: calls.append((title, message)),
    )
    return calls


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def anon():
    return TestClient(app)


@pytest.fixture
def client(sent):
    c = TestClient(app)
    c.post("/api/auth/request-code", json={"phone": OWNER})
    code = sent[-1][1].split(": ")[1][:6]
    assert c.post("/api/auth/verify", json={"phone": OWNER, "code": code}).status_code == 200
    return c
