"""בדיקות לנתיבי מסך המיילים (שלב 4-3).

אין כאן אף פנייה לגוגל ואף קריאה למודל: ``gmail.list_screen``,
``gmail.triage`` ו-``gmail.fetch_full`` מוחלפות ב-``monkeypatch``, וחיבור
הגוגל נשמר במסד בלי לפנות לגוגל.

⚠️ **מה שהבדיקות כאן לא יכולות לכסות:** שהסיווג באמת מבדיל בין מייל
שדורש טיפול לפרסומת, ושהרשימה נראית נוח מול תיבה אמיתית. זה נבדק מול
התיבה אחרי הפריסה, וזאת גם הסיבה שהמסך נבנה קודם בקריאה בלבד.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app import gauth, gmail
from app.auth import now
from app.db import SessionLocal
from app.models import Client, Task

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


def mail(number: int, address: str = "dani@example.com", **extra):
    """⚠️ מייל של **היום**, ולא תאריך קבוע.

    הרשימה מציגה תאריך למייל שאינו מהיום, ובדיקה עם תאריך קבוע נשברת
    מעצמה למחרת. זה קרה כבר ב-23.11.2026 על בדיקה שנכתבה ב-19.11.
    """
    today = datetime.now(tz=IL).replace(hour=9, minute=number % 60, second=0, microsecond=0)
    base = dict(
        id=f"gid-{number}",
        thread_id=f"th-{number}",
        sender_name="דני כהן",
        sender_email=address,
        subject=f"נושא {number}",
        snippet=f"פתיחה {number}",
        received_at=today,
    )
    base.update(extra)
    return gmail.EmailSummary(**base)


def full(number: int = 1, body: str = "שלום, מצרף את החוזה.", **extra):
    base = dict(
        id=f"gid-{number}",
        thread_id=f"th-{number}",
        sender_name="דני כהן",
        sender_email="dani@example.com",
        to="me@gmail.com",
        subject=f"נושא {number}",
        received_at=datetime.now(tz=IL),
        body=body,
    )
    base.update(extra)
    return gmail.EmailFull(**base)


def listed(monkeypatch, items, verdicts=None):
    """מחליפה את הרשימה ואת הסיווג. ברירת המחדל: הכול חשוב."""
    monkeypatch.setattr(gmail, "list_screen", lambda *a, **k: items)
    decide = verdicts or {}
    monkeypatch.setattr(
        gmail,
        "triage",
        lambda emails, client_emails=None: [
            gmail.Triaged(
                email=item,
                relevant=decide.get(item.id, (True, ""))[0],
                line=decide.get(item.id, (True, ""))[1] or f"תיאור {item.id}",
                forced=item.sender_email.lower() in (client_emails or set()),
            )
            for item in emails
        ],
    )


# --- הרשימה ---


def test_the_list_returns_the_mails_with_both_counters(client, connected, monkeypatch):
    listed(
        monkeypatch,
        [mail(1), mail(2), mail(3)],
        {"gid-2": (False, "פרסומת"), "gid-3": (False, "ניוזלטר")},
    )
    body = client.get("/api/emails?scope=week").json()
    assert [item["id"] for item in body["items"]] == ["gid-1", "gid-2", "gid-3"]
    assert body["important"] == 1
    assert body["other"] == 2
    assert body["scope"] == "week"


def test_both_groups_come_back_in_one_response(client, connected, monkeypatch):
    """⚠️ הלשוניות מסננות בצד הלקוח, ולכן גם הלא-חשובים חוזרים.

    אחרת מעבר ללשונית "לא חשוב" היה פנייה נוספת לגוגל ולמודל, ועל זה
    בדיוק קיים המטמון בשכבת השירות.
    """
    listed(monkeypatch, [mail(1), mail(2)], {"gid-2": (False, "פרסומת")})
    items = client.get("/api/emails").json()["items"]
    assert [item["important"] for item in items] == [True, False]


def test_the_line_is_the_one_the_model_wrote(client, connected, monkeypatch):
    listed(monkeypatch, [mail(1)], {"gid-1": (True, "מבקש חתימה עד חמישי")})
    assert client.get("/api/emails").json()["items"][0]["line"] == "מבקש חתימה עד חמישי"


def test_a_mail_from_a_client_card_is_marked(client, connected, db, monkeypatch):
    db.add(Client(name="דני ובניו", email="dani@example.com"))
    db.commit()
    listed(monkeypatch, [mail(1, address="dani@example.com")])
    item = client.get("/api/emails").json()["items"][0]
    assert item["is_client"] is True
    assert item["important"] is True


def test_unread_and_attachment_flags_reach_the_screen(client, connected, monkeypatch):
    listed(monkeypatch, [mail(1, unread=True, has_attachments=True), mail(2)])
    items = client.get("/api/emails").json()["items"]
    assert (items[0]["unread"], items[0]["has_attachments"]) == (True, True)
    assert (items[1]["unread"], items[1]["has_attachments"]) == (False, False)


def test_an_empty_inbox_is_not_an_error(client, connected, monkeypatch):
    listed(monkeypatch, [])
    body = client.get("/api/emails").json()
    assert body["items"] == []
    assert (body["important"], body["other"], body["truncated"]) == (0, 0, False)


def test_the_scope_reaches_the_service_layer(client, connected, monkeypatch):
    seen = []

    def spy(db, scope, *a, **k):
        seen.append(scope)
        return []

    monkeypatch.setattr(gmail, "list_screen", spy)
    monkeypatch.setattr(gmail, "triage", lambda emails, client_emails=None: [])
    for scope in ("today", "week", "month"):
        assert client.get(f"/api/emails?scope={scope}").status_code == 200
    assert seen == ["today", "week", "month"]


def test_an_unknown_scope_is_rejected(client, connected, monkeypatch):
    listed(monkeypatch, [mail(1)])
    assert client.get("/api/emails?scope=year").status_code == 422


def test_the_default_scope_is_the_week(client, connected, monkeypatch):
    listed(monkeypatch, [mail(1)])
    assert client.get("/api/emails").json()["scope"] == "week"


def test_hitting_the_cap_is_reported_as_truncated(client, connected, monkeypatch):
    """המסך אומר למשתמש שיש עוד, ולא מציג רשימה חתוכה כאילו היא הכול."""
    listed(monkeypatch, [mail(number) for number in range(gmail.SCREEN_LIMIT)])
    assert client.get("/api/emails").json()["truncated"] is True


def test_a_short_list_is_not_truncated(client, connected, monkeypatch):
    listed(monkeypatch, [mail(1), mail(2)])
    assert client.get("/api/emails").json()["truncated"] is False


# --- המייל המלא ---


def test_opening_a_mail_returns_the_body(client, connected, monkeypatch):
    monkeypatch.setattr(gmail, "fetch_full", lambda db, mid: full(1, body="נא לחתום עד חמישי"))
    body = client.get("/api/emails/gid-1").json()
    assert body["body"] == "נא לחתום עד חמישי"
    assert body["subject"] == "נושא 1"
    assert body["sender"] == "דני כהן"


def test_attachment_names_and_the_quoted_note_reach_the_screen(client, connected, monkeypatch):
    monkeypatch.setattr(
        gmail,
        "fetch_full",
        lambda db, mid: full(1, attachments=["חוזה.pdf", "נספח.docx"], quoted_removed=True),
    )
    body = client.get("/api/emails/gid-1").json()
    assert body["attachments"] == ["חוזה.pdf", "נספח.docx"]
    assert body["quoted_removed"] is True


def test_reading_a_mail_does_not_call_the_triage(client, connected, monkeypatch):
    """⚠️ הסיווג הוא של הרשימה. קריאה למודל בכל פתיחה היא עלות בלי תועלת."""
    monkeypatch.setattr(gmail, "fetch_full", lambda db, mid: full(1))
    monkeypatch.setattr(gmail, "triage", lambda *a, **k: pytest.fail("אין לסווג מייל בודד"))
    assert client.get("/api/emails/gid-1").status_code == 200


def test_the_requested_id_is_the_one_fetched(client, connected, monkeypatch):
    seen = []

    def spy(db, mid):
        seen.append(mid)
        return full(1)

    monkeypatch.setattr(gmail, "fetch_full", spy)
    client.get("/api/emails/gid-42")
    assert seen == ["gid-42"]


# --- מה שנשמר, ומה שלא ---


def test_nothing_about_the_mail_content_is_stored(client, connected, monkeypatch, db):
    """⚠️ ההבטחה המרכזית: המסך קורא מגוגל ואינו כותב למסד.

    הבדיקה עוברת על **כל** העמודות הטקסטואליות בכל הטבלאות, ולא על רשימה
    שנכתבה ביד: טבלה חדשה שתישמור תוכן מייל תיתפס כאן בלי שאיש יזכור
    להוסיף אותה. אם הבדיקה נשברת, צריך לעדכן את
    ``frontend/public/privacy.html`` ואת ``terms.html`` — הם מוגשים
    ב-/privacy וב-/terms, וגוגל מצביעה עליהם.
    """
    listed(monkeypatch, [mail(1, subject="סודי לגמרי", snippet="תוכן שאסור שיישמר")])
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1, body="גוף סודי לגמרי"))
    assert client.get("/api/emails").status_code == 200
    assert client.get("/api/emails/gid-1").status_code == 200

    db.expire_all()
    with SessionLocal() as raw:
        columns = raw.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns"
                " WHERE table_schema = 'public'"
                " AND data_type IN ('text', 'character varying')"
            )
        ).all()
        assert columns, "לא נמצאו עמודות לבדוק — הבדיקה חייבת לכסות משהו"
        for table, column in columns:
            found = raw.execute(
                text(f'SELECT count(*) FROM "{table}" WHERE "{column}" LIKE :needle'),
                {"needle": "%סודי לגמרי%"},
            ).scalar_one()
            assert found == 0, f"תוכן מייל נשמר ב-{table}.{column}"
    # וגם לא נוצרה משימה: "הפוך למשימה" הוא 4-5
    assert db.scalars(select(Task)).all() == []


# --- כשאין חיבור ---


def test_without_a_google_row_the_list_says_to_connect(client, monkeypatch):
    listed(monkeypatch, [mail(1)])
    response = client.get("/api/emails")
    assert response.status_code == 503
    assert "הגדרות" in response.json()["detail"]


def test_a_revoked_connection_says_to_reconnect(client, connected, db, monkeypatch):
    connected.status = "disconnected"
    db.commit()
    listed(monkeypatch, [mail(1)])
    response = client.get("/api/emails")
    assert response.status_code == 503
    assert "לחבר מחדש" in response.json()["detail"]


def test_a_missing_server_configuration_is_reported(client, connected, monkeypatch):
    monkeypatch.setattr(gauth, "configured", lambda: False)
    response = client.get("/api/emails")
    assert response.status_code == 503
    assert ".env" in response.json()["detail"]


def test_a_connection_revoked_mid_request_is_a_503(client, connected, monkeypatch):
    def boom(*a, **k):
        raise gauth.GoogleDisconnected("invalid_grant")

    monkeypatch.setattr(gmail, "list_screen", boom)
    assert client.get("/api/emails").status_code == 503


def test_a_gmail_failure_is_a_502_with_try_again(client, connected, monkeypatch):
    def boom(*a, **k):
        raise gmail.GmailError("גוגל החזירה 500")

    monkeypatch.setattr(gmail, "list_screen", boom)
    response = client.get("/api/emails")
    assert response.status_code == 502
    assert "לנסות שוב" in response.json()["detail"]


def test_a_google_error_while_opening_a_mail_is_a_502(client, connected, monkeypatch):
    def boom(*a, **k):
        raise gauth.GoogleError("גוגל לא נענתה")

    monkeypatch.setattr(gmail, "fetch_full", boom)
    assert client.get("/api/emails/gid-1").status_code == 502


def test_opening_a_mail_without_a_connection_says_to_connect(client, monkeypatch):
    monkeypatch.setattr(gmail, "fetch_full", lambda db, mid: full(1))
    response = client.get("/api/emails/gid-1")
    assert response.status_code == 503
    assert "הגדרות" in response.json()["detail"]


# --- כניסה ---


def test_both_routes_require_a_login(anon, connected, monkeypatch):
    listed(monkeypatch, [mail(1)])
    monkeypatch.setattr(gmail, "fetch_full", lambda db, mid: full(1))
    assert anon.get("/api/emails").status_code == 401
    assert anon.get("/api/emails/gid-1").status_code == 401


# --- שרשורים במסך ---


def test_the_thread_count_reaches_the_screen(client, connected, monkeypatch):
    listed(monkeypatch, [mail(1, thread_count=3), mail(2)])
    items = client.get("/api/emails").json()["items"]
    assert items[0]["thread_count"] == 3
    assert items[1]["thread_count"] == 1


def test_truncation_counts_messages_and_not_rows(client, connected, monkeypatch):
    """⚠️ הרשימה מכווצת לשרשורים: 100 הודעות עשויות לחזור כ-50 שורות,
    ולכן ספירת שורות הייתה אומרת "לא נגענו בתקרה" בדיוק כשנגענו בה."""
    rows = gmail.SCREEN_LIMIT // 2
    listed(monkeypatch, [mail(number, thread_count=2) for number in range(rows)])
    body = client.get("/api/emails").json()
    assert len(body["items"]) == rows
    assert body["truncated"] is True


# --- חימום מסך המיילים ---
#
# נמדד מול התיבה האמיתית ב-24.11.2026: הסיווג הוא 9 מתוך 10 שניות
# הטעינה, וההמתנה היא זמן תגובה קבוע של המודל. עם מטמון חם: 1.5 שניות.


@pytest.fixture(autouse=True)
def clean_warm_clock():
    from app.bot import reminders

    reminders.reset_warm_clock()
    yield
    reminders.reset_warm_clock()


def test_the_warmup_classifies_the_inbox_ahead_of_time(db, connected, monkeypatch):
    from app.bot import reminders

    calls = []
    monkeypatch.setattr(gmail, "list_screen", lambda *a, **k: [mail(1), mail(2)])
    monkeypatch.setattr(
        gmail, "triage", lambda emails, client_emails=None: calls.append(len(emails)) or []
    )
    assert reminders.warm_mail_screen(db) is True
    assert calls == [2]


def test_the_warmup_does_not_run_on_every_tick(db, connected, monkeypatch):
    """⚠️ הלולאה רצה כל 30 שניות. בלי שעון, החימום היה קריאה בתשלום
    כל חצי דקה."""
    from app.bot import reminders

    calls = []
    monkeypatch.setattr(gmail, "list_screen", lambda *a, **k: [mail(1)])
    monkeypatch.setattr(
        gmail, "triage", lambda emails, client_emails=None: calls.append(1) or []
    )
    assert reminders.warm_mail_screen(db) is True
    assert reminders.warm_mail_screen(db) is False
    assert reminders.warm_mail_screen(db) is False
    assert len(calls) == 1


def test_the_warmup_runs_again_once_the_interval_passed(db, connected, monkeypatch):
    from app.bot import reminders

    calls = []
    monkeypatch.setattr(gmail, "list_screen", lambda *a, **k: [mail(1)])
    monkeypatch.setattr(
        gmail, "triage", lambda emails, client_emails=None: calls.append(1) or []
    )
    assert reminders.warm_mail_screen(db) is True
    later = now() + reminders.WARM_EVERY + timedelta(seconds=1)
    assert reminders.warm_mail_screen(db, later) is True
    assert len(calls) == 2


def test_the_warmup_interval_is_shorter_than_the_cache_ttl():
    """⚠️ אחרת נפתח חלון שבו המטמון פג והחימום עוד לא רץ — בדיוק המצב
    שהחימום נועד למנוע."""
    from app.bot import reminders

    assert reminders.WARM_EVERY < gmail.TRIAGE_TTL


def test_without_a_google_connection_nothing_is_warmed(db, monkeypatch):
    from app.bot import reminders

    monkeypatch.setattr(
        gmail, "list_screen", lambda *a, **k: pytest.fail("אין לפנות לגוגל בלי חיבור")
    )
    assert reminders.warm_mail_screen(db) is False


def test_an_empty_inbox_does_not_call_the_model(db, connected, monkeypatch):
    from app.bot import reminders

    monkeypatch.setattr(gmail, "list_screen", lambda *a, **k: [])
    monkeypatch.setattr(gmail, "triage", lambda *a, **k: pytest.fail("אין מה לסווג"))
    assert reminders.warm_mail_screen(db) is False


def test_a_failed_warmup_does_not_retry_immediately(db, connected, monkeypatch):
    """⚠️ בלי זה תקלה מתמשכת הייתה שורפת קריאה כל חצי דקה."""
    from app.bot import reminders

    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise gmail.GmailError("רשת")

    monkeypatch.setattr(gmail, "list_screen", boom)
    with pytest.raises(gmail.GmailError):
        reminders.warm_mail_screen(db)
    # הסבב הבא אינו מנסה שוב מיד
    assert reminders.warm_mail_screen(db) is False
    assert len(calls) == 1


def test_a_failed_warmup_never_touches_the_reminders(db, connected, monkeypatch, sent):
    """⚠️ החימום הוא נוחות ולא תלות: כשל שלו לא יעצור תזכורת."""
    from app.bot import reminders

    monkeypatch.setattr(
        gmail, "list_screen", lambda *a, **k: (_ for _ in ()).throw(gmail.GmailError("רשת"))
    )
    # ‏_tick בולע את הכשל ואינו מתפוצץ
    reminders._tick()


def test_the_warmed_scope_is_the_one_the_screen_opens_on(db, connected, monkeypatch):
    """חימום של חלון אחר לא היה עוזר למסך בכלל."""
    from app.bot import reminders

    seen = []

    def spy(db_, scope, *a, **k):
        seen.append(scope)
        return []

    monkeypatch.setattr(gmail, "list_screen", spy)
    reminders.warm_mail_screen(db)
    assert seen == ["week"]
