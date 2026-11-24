"""בדיקות לקריאת היומן דרך הבוט (שלב 4ב-1).

אין כאן אף פנייה לגוגל: שכבת השירות מוחלפת ב-monkeypatch, וזה בדיוק מה
שההפרדה בין ``app/gcal.py`` ל-``app/bot/events.py`` קנתה.

⚠️ מה שהבדיקות **לא** יכולות לכסות, ולכן נבדק מול היומן האמיתי אחרי
הפריסה: בחירת הפעולה על ידי המודל, ושהסכימה החדשה עוברת את ה-API.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import gauth, gcal
from app.bot import actions, events
from app.bot.intent import Intent
from app.models import BotMessage, Task

IL = ZoneInfo("Asia/Jerusalem")

TOKENS = {
    "refresh_token": "refresh-1",
    "access_token": "access-1",
    "expires_in": 3600,
    "scope": " ".join(gauth.SCOPES),
}


@pytest.fixture
def connected(db, monkeypatch):
    """חיבור גוגל תקף במסד, בלי אף פנייה לגוגל."""
    monkeypatch.setattr(gauth, "fetch_email", lambda token: "me@gmail.com")
    cred = gauth.save_tokens(db, dict(TOKENS))
    yield cred
    db.rollback()


def event(hour: int, title: str, minutes: int = 60, **extra) -> gcal.Event:
    """⚠️ אירוע של **מחר**, ולא תאריך קבוע.

    התשובה מציגה שם יום, ולכן בדיקה עם תאריך קבוע נשברת מעצמה. זה קרה
    ב-23.11.2026 על בדיקת מיילים שנכתבה ב-19.11, ולכן זה נכתב כך מראש.
    """
    day = datetime.now(tz=IL).date() + timedelta(days=1)
    start = datetime.combine(day, datetime.min.time(), tzinfo=IL).replace(hour=hour)
    return gcal.Event(
        id=f"e{hour}",
        title=title,
        calendar="ראשי",
        start=start,
        end=start + timedelta(minutes=minutes),
        **extra,
    )


def run(db, scope: str = "tomorrow") -> actions.Outcome:
    return actions.execute(db, Intent(action="list_events", event_scope=scope))


# --- התשובה ---


def test_tomorrow_is_called_tomorrow_and_not_by_its_day_name(db, connected, monkeypatch):
    """⚠️ "מחר" ולא "יום רביעי" כשזה באמת מחר. אחרת צריך לחשב בראש."""
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [event(9, "פגישה עם דני")])
    outcome = run(db)
    assert "מחר" in outcome.reply
    assert "09:00" in outcome.reply
    assert "פגישה עם דני" in outcome.reply


def test_an_empty_day_says_so_plainly(db, connected, monkeypatch):
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [])
    outcome = run(db)
    assert "אין לך כלום ביומן מחר" in outcome.reply


def test_an_empty_day_does_not_reset_any_numbering(db, connected, monkeypatch):
    """⚠️ קריאה מהיומן אינה משנה דבר, ולכן אינה מפילה מספור קיים.

    אם היא הייתה מאפסת, "סיימתי 2" אחרי שאלה על היומן היה נכשל — או
    גרוע מזה, סוגר משימה אחרת.
    """
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [])
    outcome = run(db)
    assert outcome.clear_list is False
    assert outcome.listed_task_ids == []
    assert outcome.listed_email_ids == []


def test_a_full_day_does_not_reset_any_numbering_either(db, connected, monkeypatch):
    """⚠️ אין מספור ואין איפוס גם כשיש אירועים.

    בפריסה הזאת אין פעולה שאפשר לעשות על אירוע, ולכן מספור היה הבטחה
    שלא נממש — וגרוע מזה, הוא היה מאפס את מספור המשימות בלי שום תמורה.
    """
    monkeypatch.setattr(
        gcal, "agenda", lambda session, scope: [event(9, "אחד"), event(11, "שניים")]
    )
    outcome = run(db)
    assert outcome.clear_list is False
    assert outcome.listed_email_ids == []


def test_the_count_is_singular_for_one_event(db, connected, monkeypatch):
    """"אירוע אחד" ולא "1 אירועים". אותו לקח מ-19.11 על המיילים."""
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [event(9, "לבד")])
    assert "אירוע אחד" in run(db).reply

    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [event(9, "א"), event(10, "ב")])
    assert "2 אירועים" in run(db).reply


def test_an_event_shows_its_end_time(db, connected, monkeypatch):
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [event(9, "פגישה", minutes=90)])
    assert "09:00–10:30" in run(db).reply


def test_an_all_day_event_has_no_clock(db, connected, monkeypatch):
    """⚠️ "כל היום" ולא "00:00", שנראה כמו אירוע שמתחיל בחצות."""
    day = datetime.now(tz=IL).date() + timedelta(days=1)
    whole = gcal.Event(id="w", title="חופשה", calendar="ראשי", all_day=True, day=day)
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [whole])
    reply = run(db).reply
    assert "כל היום · חופשה" in reply
    assert "00:00" not in reply


def test_one_attendee_is_named_and_several_are_counted(db, connected, monkeypatch):
    """שם אחד במלואו, ומעבר לזה מונה — כדי שהשורה תישאר שורה."""
    one = event(9, "פגישה", attendees=["dani@example.com"])
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [one])
    assert "עם dani@example.com" in run(db).reply

    many = event(9, "פגישה", attendees=["a@x.com", "b@x.com", "c@x.com"])
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [many])
    assert "עם 3 משתתפים" in run(db).reply


def test_a_meeting_with_no_attendees_says_nothing_about_them(db, connected, monkeypatch):
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [event(9, "לבד")])
    assert "עם" not in run(db).reply.split("לבד")[-1]


def test_the_location_is_shown_when_there_is_one(db, connected, monkeypatch):
    monkeypatch.setattr(
        gcal, "agenda", lambda session, scope: [event(9, "פגישה", location="רחוב הרצל 1")]
    )
    assert "רחוב הרצל 1" in run(db).reply


# --- שבוע ---


def test_a_week_is_grouped_by_day(db, connected, monkeypatch):
    """⚠️ בלי קיבוץ, שבוע נראה כרשימת שעות בלי תאריכים.

    זאת בדיוק התקלה ש-``gmail._when`` נולד בשבילה ב-19.11, כשסיכום שבועי
    הציג "20:36" ו-"12:29" זה מתחת לזה כאילו הם מאותו יום.
    """
    today = datetime.now(tz=IL).date()
    first = datetime.combine(today, datetime.min.time(), tzinfo=IL).replace(hour=9)
    later = first + timedelta(days=2)
    week = [
        gcal.Event(id="a", title="היום", calendar="ראשי", start=first, end=first),
        gcal.Event(id="b", title="בעוד יומיים", calendar="ראשי", start=later, end=later),
    ]
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: week)
    reply = actions.execute(db, Intent(action="list_events", event_scope="week")).reply
    assert "השבוע הקרוב" in reply
    assert "*היום" in reply
    assert f"{later:%d/%m}" in reply


def test_a_single_day_is_not_grouped(db, connected, monkeypatch):
    """ביום אחד כותרת ביניים היא רעש: כל השורות מאותו יום."""
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [event(9, "א"), event(11, "ב")])
    reply = run(db).reply
    assert "*" not in reply


# --- כשהיומן לא נגיש ---


def test_no_google_connection_points_at_the_dashboard(db, monkeypatch):
    monkeypatch.setattr(gauth, "configured", lambda: True)
    outcome = run(db)
    assert "הגדרות" in outcome.reply


def test_a_revoked_connection_says_to_reconnect(db, connected, monkeypatch):
    def disconnected(session, scope):
        raise gauth.GoogleDisconnected("invalid_grant")

    monkeypatch.setattr(gcal, "agenda", disconnected)
    assert "לחבר מחדש" in run(db).reply


def test_a_network_failure_says_try_again_and_keeps_the_numbering(db, connected, monkeypatch):
    """⚠️ תקלת רשת אינה ניתוק, ואינה מאפסת מספור.

    אותה הבחנה שנקבעה ב-4-2: "נסה שוב" מול "צריך לחבר מחדש" הם שני
    מצבים שונים לגמרי מבחינת מה שהמשתמש צריך לעשות.
    """

    def broken(session, scope):
        raise gcal.CalendarError("timeout")

    monkeypatch.setattr(gcal, "agenda", broken)
    outcome = run(db)
    assert "לנסות שוב" in outcome.reply
    assert "לחבר מחדש" not in outcome.reply
    assert outcome.clear_list is False


# --- מה שהפעולה אינה עושה ---


def test_reading_the_calendar_creates_nothing_in_the_database(db, connected, monkeypatch):
    """⚠️ קריאה בלבד: אין משימה, אין אירוע, אין שורה חדשה."""
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [event(9, "פגישה")])
    run(db)
    db.flush()
    assert db.scalars(select(Task)).all() == []


def test_the_calendar_itself_is_not_copied_into_the_database(db, connected, monkeypatch):
    """⚠️⚠️ כאן ההבטחה **שונה** מזו של המיילים, וזה נבדק ולא הונח.

    ב-4-2 נקבע ש"שום תוכן מייל אינו נשמר", והוא נכון כי התשובה מכילה את
    שורת התיאור שכתב Haiku ולא את הנושא. **ביומן זה לא היה נכון לטעון:**
    התשובה היא השעה והכותרת עצמן, והיא נשמרת ב-``bot_messages.reply``
    כמו כל תשובה של הבוט.

    לכן מה שנבדק כאן הוא מה שאפשר להתחייב עליו באמת: **אין עמודה, טבלה
    או מיגרציה שמחזיקה אירועים.** היומן אינו משוקף למסד, ומה שנשאר הוא
    יומן ההודעות — ו-``frontend/public/privacy.html`` אומר זאת מפורשות.
    """
    title = "פגישה עם רואה החשבון"
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [event(9, title)])
    outcome = run(db)
    db.flush()

    # ‏Outcome אינו נושא שום מזהה או תוכן של אירוע לשמירה
    assert outcome.task_id is None
    assert outcome.listed_email_ids == []
    assert outcome.listed_task_ids == []
    assert outcome.undo is None
    assert outcome.pending is None
    # ואין טבלה שאירוע נכנס אליה
    assert "events" not in {table for table in BotMessage.metadata.tables}
    assert title in outcome.reply


def test_the_bot_layer_calls_no_model():
    """⚠️ אין כאן קריאת מודל, ולכן כותרת אירוע אינה מגיעה לשום מודל."""
    source = (events.__file__ or "").replace(".pyc", ".py")
    with open(source, encoding="utf-8") as handle:
        text = handle.read().lower()
    for marker in ("anthropic", "claude", "messages.create"):
        assert marker not in text, marker


# --- שמות הימים ---


def test_the_day_names_are_hebrew_and_aligned_with_weekday():
    """⚠️ ``weekday()`` מחזיר 0 לשני, ולכן הסדר ב-DAYS מתחיל בשני.

    מיפוי שמוזז ביום אחד הוא בדיוק סוג הבאג שאיש לא שם לב אליו עד
    שהתשובה אומרת "יום שלישי" על רביעי.
    """
    # 23.11.2026 הוא יום שני
    assert events.day_name(date(2026, 11, 23)) == "שני"
    assert events.day_name(date(2026, 11, 28)) == "שבת"
    assert events.day_name(date(2026, 11, 29)) == "ראשון"
