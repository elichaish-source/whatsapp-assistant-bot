"""בדיקות לפעמון: מה נשלח, מה לא, ומה קורה כשהוא נכשל.

שתי השאלות החשובות כאן אינן "האם ההתראה יצאה" אלא:
‏(1) שכשל בפוש לא גורם לתזכורת להישלח פעמיים בוואטסאפ, ו-(2) שהעברית
נוסעת בגוף הבקשה ולא בכותרת HTTP, שאינה UTF-8 ונשברת.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import notify
from app.bot import reminders
from app.config import get_settings
from app.models import Task

OWNER = "972501234567"


class FakeResponse:
    def __init__(self, status: int = 200):
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("nope", request=None, response=None)


@pytest.fixture
def ntfy(monkeypatch):
    """מגדיר את הפעמון ותופס את הבקשה היוצאת. מחזיר את רשימת הקריאות."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ntfy_url", "http://ntfy")
    monkeypatch.setattr(settings, "ntfy_topic", "topic-abc")
    monkeypatch.setattr(settings, "ntfy_token", "tk_secret")

    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return FakeResponse()

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    return calls


def task(db, title: str = "להתקשר לדני", **kwargs) -> Task:
    row = Task(title=title, status="open", **kwargs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- מתי בכלל נשלח ---


def test_without_a_topic_nothing_is_sent(monkeypatch):
    """כלל הברזל: בלי מפתח המערכת מתנהגת כמו לפני השלב הזה."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ntfy_topic", "")

    def explode(*args, **kwargs):
        raise AssertionError("אסור לפנות לרשת בלי נושא מוגדר")

    monkeypatch.setattr(notify.httpx, "post", explode)
    assert notify.configured() is False
    notify.send("משהו", title="תזכורת")


def test_a_configured_bell_sends_one_request(ntfy):
    notify.send("לשלם ארנונה", title="תזכורת")
    assert len(ntfy) == 1
    assert ntfy[0]["url"] == "http://ntfy"


# --- מה נשלח ---


def test_the_hebrew_travels_in_the_body_and_never_in_a_header(ntfy):
    """⚠️ לב הבדיקה: כותרות HTTP אינן UTF-8.

    הדפוס הנפוץ ב-ntfy הוא Title ו-Priority ככותרות HTTP, וכותרת בעברית
    הייתה נשברת עוד לפני שהבקשה יוצאת. לכן השליחה היא JSON לשורש.
    """
    notify.send("לשלם ארנונה לקניון", title="תזכורת")
    call = ntfy[0]
    assert call["json"]["title"] == "תזכורת"
    assert call["json"]["message"] == "לשלם ארנונה לקניון"
    for name, value in (call["headers"] or {}).items():
        value.encode("latin-1")  # נכשל אם מישהו יחזיר עברית לכותרת
        assert name.isascii()


def test_the_topic_and_the_priority_are_ours(ntfy):
    notify.send("משהו", title="תזכורת")
    assert ntfy[0]["json"]["topic"] == "topic-abc"
    assert ntfy[0]["json"]["priority"] == notify.PRIORITY


def test_the_token_goes_in_the_authorization_header(ntfy):
    notify.send("משהו", title="תזכורת")
    assert ntfy[0]["headers"]["Authorization"] == "Bearer tk_secret"


def test_without_a_token_no_authorization_header(ntfy, monkeypatch):
    monkeypatch.setattr(get_settings(), "ntfy_token", "")
    notify.send("משהו", title="תזכורת")
    assert "Authorization" not in (ntfy[0]["headers"] or {})


# --- הלחיצה ---


def test_the_click_opens_the_bot_chat_by_default(ntfy):
    notify.send("משהו", title="תזכורת")
    assert ntfy[0]["json"]["click"] == f"https://wa.me/{OWNER}"


def test_an_explicit_empty_click_leaves_the_link_out(ntfy):
    """אם פתיחת הצ'אט לא תעבוד בטלפון, אפשר לכבות את הלחיצה."""
    notify.send("משהו", title="תזכורת", click="")
    assert "click" not in ntfy[0]["json"]


def test_an_explicit_click_overrides_the_default(ntfy):
    notify.send("משהו", title="תזכורת", click="https://example.test/tasks")
    assert ntfy[0]["json"]["click"] == "https://example.test/tasks"


# --- כשהפעמון נכשל ---


def test_a_network_failure_becomes_a_notify_error(ntfy, monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("אין חיבור")

    monkeypatch.setattr(notify.httpx, "post", fail)
    with pytest.raises(notify.NotifyError):
        notify.send("משהו", title="תזכורת")


def test_a_refused_request_becomes_a_notify_error(ntfy, monkeypatch):
    """‏403 הוא מה ש-ntfy מחזיר על טוקן שאינו מורשה לנושא."""
    monkeypatch.setattr(notify.httpx, "post", lambda *a, **k: FakeResponse(403))
    with pytest.raises(notify.NotifyError):
        notify.send("משהו", title="תזכורת")


# --- דרך התזכורות ---


def test_a_due_reminder_also_rings(db, sent, pushed):
    moment = datetime.now(timezone.utc)
    task(db, "לשלם ארנונה", reminder_at=moment - timedelta(minutes=1))

    assert reminders.send_due_reminders(db, moment) == 1
    assert len(sent) == 1
    assert len(pushed) == 1
    title, message = pushed[0]
    assert title == "תזכורת"
    # הטקסט המלא, כמו בוואטסאפ: הכותרת ואחריה שורת הפרטים
    assert message.startswith("לשלם ארנונה")
    assert "תזכורת " in message  # שורת הפרטים של describe


def test_the_push_does_not_repeat_the_word_reminder(db, sent, pushed):
    """הכותרת היא "תזכורת", ולכן הטקסט עצמו לא פותח בה שוב."""
    moment = datetime.now(timezone.utc)
    task(db, "לשלם ארנונה", reminder_at=moment - timedelta(minutes=1))
    reminders.send_due_reminders(db, moment)

    title, message = pushed[0]
    assert title == reminders.PREFIX
    assert not message.startswith(reminders.PREFIX)
    # ובוואטסאפ הטקסט המלא נשאר כפי שהיה
    assert sent[0][1].startswith(f"{reminders.PREFIX}: ")


def test_a_failed_push_does_not_send_the_whatsapp_message_twice(db, sent, monkeypatch):
    """⚠️ הבדיקה החשובה בקובץ.

    אם כשל בפוש היה עולה למעלה, התזכורת לא הייתה מסומנת כנשלחה, והסבב
    הבא היה שולח אותה שוב בוואטסאפ. כפילות גרועה מהתראה שלא הגיעה.
    """

    def fail(message, title, click=None):
        raise notify.NotifyError("השרת לא זמין")

    monkeypatch.setattr(notify, "send", fail)
    moment = datetime.now(timezone.utc)
    row = task(db, "לשלם ארנונה", reminder_at=moment - timedelta(minutes=1))

    assert reminders.send_due_reminders(db, moment) == 1
    db.refresh(row)
    assert row.reminder_sent_at is not None
    # סבב נוסף לא שולח שוב, לא בוואטסאפ ולא בפוש
    assert reminders.send_due_reminders(db, moment) == 0
    assert len(sent) == 1


def test_a_reminder_that_was_not_sent_does_not_ring(db, sent, pushed):
    """תזכורת מהעבר הרחוק מסומנת כטופלה בלי לשלוח — וגם בלי לצפצף."""
    moment = datetime.now(timezone.utc)
    task(db, "מלפני יומיים", reminder_at=moment - timedelta(days=2))

    assert reminders.send_due_reminders(db, moment) == 0
    assert sent == []
    assert pushed == []


def test_a_future_reminder_does_not_ring(db, sent, pushed):
    moment = datetime.now(timezone.utc)
    task(db, "מחר", reminder_at=moment + timedelta(hours=2))

    assert reminders.send_due_reminders(db, moment) == 0
    assert pushed == []


def test_an_ordinary_bot_reply_does_not_ring(sent, pushed):
    """⚠️ רק הודעות שהבוט יוזם מצפצפות.

    תשובה להודעה של המשתמש לא מקבלת פוש: כשהוא כותב הוא כבר בוואטסאפ,
    והתראה על תשובה שהוא מחכה לה היא בדיוק איך מרגילים אותו להתעלם.
    """
    from app.routers import bot as bot_router

    bot_router._reply(OWNER, "נשמר")
    assert len(sent) == 1
    assert pushed == []
