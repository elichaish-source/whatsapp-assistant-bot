"""בדיקות לקריאת היומן דרך הבוט (שלב 4ב-1).

אין כאן אף פנייה לגוגל: שכבת השירות מוחלפת ב-monkeypatch, וזה בדיוק מה
שההפרדה בין ``app/gcal.py`` ל-``app/bot/events.py`` קנתה.

⚠️ מה שהבדיקות **לא** יכולות לכסות, ולכן נבדק מול היומן האמיתי אחרי
הפריסה: בחירת הפעולה על ידי המודל, ושהסכימה החדשה עוברת את ה-API.
"""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import gauth, gcal
from app.bot import actions, events
from app.bot.intent import Intent
from app.models import BotMessage, Client, Task

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


def test_an_event_from_another_calendar_is_marked(db, connected, monkeypatch):
    """⚠️ נחוץ בגלל ההכרעה לקרוא גם את היומן המשפחתי.

    אירוע משפחתי שמופיע בלי סימון נראה כמו פגישת עבודה — "פגישה ב-20:00"
    בלי לדעת מאיזה יומן היא הוא שאלה ולא תשובה. התגלה מול היומן האמיתי
    ב-25.11.2026, כשהריצה החזירה שלושה יומנים ולא אחד.
    """
    family = event(20, "ארוחה")
    family.calendar = "היומן המשפחתי"
    family.from_primary = False
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [family])
    assert "(היומן המשפחתי)" in run(db).reply


def test_an_event_from_the_primary_calendar_is_not_marked(db, connected, monkeypatch):
    """על הראשי שם היומן היה רעש בכל שורה, ועוד כתובת מייל."""
    monkeypatch.setattr(gcal, "agenda", lambda session, scope: [event(9, "פגישה")])
    reply = run(db).reply
    assert "(" not in reply


# --- קביעת פגישה דרך הבוט (4ב-2) ---


@pytest.fixture
def made(monkeypatch):
    """תופס את היצירה והמחיקה, בלי אף פנייה לגוגל."""
    log: dict = {"created": [], "deleted": [], "exists": True}

    def create(session, title, begins, ends, attendees=None):
        guests = [a for a in (attendees or []) if a]
        log["created"].append(
            {"title": title, "begins": begins, "ends": ends, "guests": guests}
        )
        return gcal.Created(id=f"ev-{len(log['created'])}", invited=bool(guests))

    def delete(session, event_id, invited=False):
        log["deleted"].append({"id": event_id, "invited": invited})
        return log["exists"]

    monkeypatch.setattr(gcal, "create", create)
    monkeypatch.setattr(gcal, "delete_event", delete)
    monkeypatch.setattr(gcal, "conflicts", lambda session, begins, ends: [])
    monkeypatch.setattr(gcal, "next_free", lambda session, after, minutes, days=7: None)
    return log


def at(hour: int = 10, minute: int = 0, days: int = 1) -> str:
    """⚠️ זמן ביחס להיום, כי התשובה אומרת "מחר" ושם יום."""
    day = datetime.now(tz=IL).date() + timedelta(days=days)
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}"


def book(db, **extra) -> actions.Outcome:
    fields = {"action": "add_event", "title": "פגישה עם דני", "event_at": at()}
    fields.update(extra)
    return actions.execute(db, Intent(**fields))


def test_a_meeting_is_booked_immediately(db, connected, made):
    """⚠️ ההכרעה: קובעים מיד, בלי אישור מראש. אירוע ביומן הפיך לגמרי."""
    outcome = book(db)
    assert len(made["created"]) == 1
    assert made["created"][0]["title"] == "פגישה עם דני"
    assert "נקבע" in outcome.reply
    assert outcome.pending is None


def test_the_default_length_is_an_hour(db, connected, made):
    """⚠️ נגזר מהיומן האמיתי: 11 מתוך 17 הפגישות הן בנות שעה."""
    book(db)
    first = made["created"][0]
    assert (first["ends"] - first["begins"]) == timedelta(minutes=60)


def test_a_length_the_user_gave_is_used(db, connected, made):
    book(db, event_minutes=30)
    first = made["created"][0]
    assert (first["ends"] - first["begins"]) == timedelta(minutes=30)


def test_a_booking_can_be_undone(db, connected, made):
    """⚠️ זה מה שמצדיק לקבוע בלי אישור: יש ביטול אמיתי."""
    outcome = book(db)
    assert outcome.undo == {"kind": "created_event", "event_id": "ev-1", "invited": False}


def test_without_a_time_nothing_is_booked(db, connected, made):
    """⚠️ זמן שאינו זמן יורד ואינו מנוחש.

    פגישה שנקבעה לזמן הלא נכון בלי שמישהו שם לב גרועה מפגישה שלא נקבעה.
    """
    for value in ("", "מחר", "2026-13-45T10:00", "2026-11-26"):
        outcome = book(db, event_at=value)
        assert "לא הבנתי מתי" in outcome.reply, value
    assert made["created"] == []


def test_without_a_title_nothing_is_booked(db, connected, made):
    outcome = book(db, title="")
    assert "לא הבנתי על מה" in outcome.reply
    assert made["created"] == []


# --- התנגשות ---


def test_a_clash_asks_instead_of_booking(db, connected, made, monkeypatch):
    """⚠️ התנגשות אינה שגיאה אלא שאלה: אומר מה תפוס ומציע חלון פנוי."""
    day = datetime.now(tz=IL).date() + timedelta(days=1)
    busy_from = datetime.combine(day, datetime.min.time(), tzinfo=IL).replace(hour=10)
    monkeypatch.setattr(
        gcal,
        "conflicts",
        lambda session, begins, ends: [(busy_from, busy_from + timedelta(hours=1))],
    )
    monkeypatch.setattr(
        gcal,
        "next_free",
        lambda session, after, minutes, days=7: busy_from + timedelta(hours=2),
    )
    outcome = book(db)
    assert made["created"] == []
    assert "תפוס" in outcome.reply
    assert "10:00–11:00" in outcome.reply
    assert "12:00" in outcome.reply


def test_a_clash_with_no_free_slot_says_so(db, connected, made, monkeypatch):
    day = datetime.now(tz=IL).date() + timedelta(days=1)
    busy_from = datetime.combine(day, datetime.min.time(), tzinfo=IL).replace(hour=10)
    monkeypatch.setattr(
        gcal,
        "conflicts",
        lambda session, begins, ends: [(busy_from, busy_from + timedelta(hours=1))],
    )
    outcome = book(db)
    assert made["created"] == []
    assert "לא מצאתי חלון פנוי" in outcome.reply


# --- זימון: הגבול היחיד כאן שאינו הפיך ---


def test_inviting_a_client_asks_first_and_books_nothing(db, connected, made):
    """⚠️⚠️ **רק כאן יש אישור מראש.** ההזמנה שגוגל שולחת אינה הפיכה."""
    db.add(Client(name="דני כהן", email="dani@example.com"))
    db.flush()
    outcome = book(db, event_with="דני")
    assert made["created"] == []
    assert outcome.pending is not None
    assert outcome.pending["kind"] == "add_event"
    assert outcome.pending["data"]["guest"] == "dani@example.com"
    assert "אי אפשר להחזיר" in outcome.reply
    db.rollback()


def test_the_invitation_goes_out_only_after_yes(db, connected, made):
    """⚠️⚠️ האישור נקרא מ-``pending_json`` של ההודעה הקודמת, לא מהמודל."""
    db.add(Client(name="דני כהן", email="dani@example.com"))
    db.flush()
    asked = book(db, event_with="דני")

    row = BotMessage(wa_message_id="wa-ev-1", body="תקבע פגישה עם דני מחר ב-10")
    row.pending_json = json.dumps(asked.pending)
    db.add(row)
    db.flush()
    after = BotMessage(wa_message_id="wa-ev-2", body="כן")
    db.add(after)
    db.flush()

    outcome = actions.execute(db, Intent(action="confirm"), before_id=after.id)
    assert len(made["created"]) == 1
    assert made["created"][0]["guests"] == ["dani@example.com"]
    assert "הזמנה נשלחה" in outcome.reply
    db.rollback()


def test_no_means_no_invitation_and_no_event(db, connected, made):
    db.add(Client(name="דני כהן", email="dani@example.com"))
    db.flush()
    asked = book(db, event_with="דני")
    row = BotMessage(wa_message_id="wa-ev-3", body="תקבע")
    row.pending_json = json.dumps(asked.pending)
    db.add(row)
    db.flush()
    after = BotMessage(wa_message_id="wa-ev-4", body="לא")
    db.add(after)
    db.flush()

    outcome = actions.execute(db, Intent(action="decline"), before_id=after.id)
    assert made["created"] == []
    assert "לא שלחתי הזמנה" in outcome.reply
    db.rollback()


def test_a_guest_with_no_card_is_not_invited_and_it_is_said(db, connected, made):
    """⚠️ אין התאמה בכרטיס — אין זימון, והבוט אומר זאת במקום לנחש כתובת."""
    outcome = book(db, event_with="מישהו שלא קיים")
    # הפגישה כן נקבעה: לא לקבוע בכלל היה מעניש על חוסר נתון
    assert len(made["created"]) == 1
    assert made["created"][0]["guests"] == []
    assert "לא זימנתי" in outcome.reply
    assert "אין לו כתובת מייל" in outcome.reply


def test_a_client_without_an_email_is_not_invited(db, connected, made):
    db.add(Client(name="דני כהן"))
    db.flush()
    outcome = book(db, event_with="דני כהן")
    assert made["created"][0]["guests"] == []
    assert "לא זימנתי" in outcome.reply
    db.rollback()


def test_several_matching_clients_are_asked_about_and_nothing_is_booked(db, connected, made):
    """⚠️ כמה התאמות — שואל ואינו בוחר, כמו ``update_task``.

    בחירה שקטה בין שניים הייתה שולחת הזמנה לאדם הלא נכון, וזה אינו הפיך.
    """
    db.add(Client(name="דני", email="dani1@example.com"))
    db.add(Client(name="דני כהן", email="dani2@example.com"))
    db.flush()
    outcome = book(db, event_with="דני")
    assert made["created"] == []
    assert outcome.pending is None
    assert "על מי מהם" in outcome.reply
    db.rollback()


# --- "בטל" ---


def test_cancel_removes_the_event_from_the_calendar(db, connected, made):
    outcome = book(db)
    row = BotMessage(wa_message_id="wa-ev-5", body="תקבע", intent="add_event")
    row.undo_json = json.dumps(outcome.undo)
    db.add(row)
    db.flush()

    cancelled = actions.execute(db, Intent(action="cancel_last"))
    assert made["deleted"] == [{"id": "ev-1", "invited": False}]
    assert "בוטלה" in cancelled.reply
    db.rollback()


def test_cancelling_an_invited_event_says_the_invitation_stays(db, connected, made):
    """⚠️ ההזמנה אינה נמחקת מהתיבה של הנמען, והתשובה אומרת זאת."""
    row = BotMessage(wa_message_id="wa-ev-6", body="כן", intent="confirm")
    row.undo_json = json.dumps(
        {"kind": "created_event", "event_id": "ev-9", "invited": True}
    )
    db.add(row)
    db.flush()

    cancelled = actions.execute(db, Intent(action="cancel_last"))
    assert made["deleted"] == [{"id": "ev-9", "invited": True}]
    assert "נשארת בתיבה של הנמען" in cancelled.reply
    db.rollback()


def test_a_second_cancel_does_not_go_further_back(db, connected, made):
    """⚠️ מסמנים ולא מרוקנים, כמו ב-entities: אחרת "בטל" שני היה מוחק
    משהו אחר לגמרי."""
    outcome = book(db)
    row = BotMessage(wa_message_id="wa-ev-7", body="תקבע", intent="add_event")
    row.undo_json = json.dumps(outcome.undo)
    db.add(row)
    db.flush()

    actions.execute(db, Intent(action="cancel_last"))
    again = actions.execute(db, Intent(action="cancel_last"))
    assert len(made["deleted"]) == 1
    assert "כבר בוטל" in again.reply
    db.rollback()


def test_cancelling_an_event_already_deleted_in_google_is_not_an_error(db, connected, made):
    made["exists"] = False
    row = BotMessage(wa_message_id="wa-ev-8", body="תקבע", intent="add_event")
    row.undo_json = json.dumps(
        {"kind": "created_event", "event_id": "ev-gone", "invited": False}
    )
    db.add(row)
    db.flush()

    cancelled = actions.execute(db, Intent(action="cancel_last"))
    assert "כבר לא ביומן" in cancelled.reply
    db.rollback()


# --- מה שהפעולה אינה עושה ---


def test_booking_a_meeting_creates_no_task(db, connected, made):
    """⚠️ פגישה היא ביומן, ולא משימה. אין שורה חדשה בטבלת המשימות."""
    book(db)
    db.flush()
    assert db.scalars(select(Task)).all() == []


def test_a_failure_in_google_does_not_claim_the_meeting_was_booked(db, connected, monkeypatch):
    """⚠️ "נקבע" שנאמר על פגישה שלא נקבעה הוא הכשל הגרוע כאן."""

    def broken(session, title, begins, ends, attendees=None):
        raise gcal.CalendarError("timeout")

    monkeypatch.setattr(gcal, "create", broken)
    monkeypatch.setattr(gcal, "conflicts", lambda session, begins, ends: [])
    outcome = book(db)
    assert "נקבע" not in outcome.reply
    assert "לא הצלחתי" in outcome.reply
    assert outcome.undo is None
