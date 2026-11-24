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
    assert reminders.warm_mail_screen(db) is not None
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
    assert reminders.warm_mail_screen(db) is not None
    assert reminders.warm_mail_screen(db) is None
    assert reminders.warm_mail_screen(db) is None
    assert len(calls) == 1


def test_the_warmup_runs_again_once_the_interval_passed(db, connected, monkeypatch):
    from app.bot import reminders

    calls = []
    monkeypatch.setattr(gmail, "list_screen", lambda *a, **k: [mail(1)])
    monkeypatch.setattr(
        gmail, "triage", lambda emails, client_emails=None: calls.append(1) or []
    )
    assert reminders.warm_mail_screen(db) is not None
    later = now() + reminders.WARM_EVERY + timedelta(seconds=1)
    assert reminders.warm_mail_screen(db, later) is not None
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
    assert reminders.warm_mail_screen(db) is None


def test_an_empty_inbox_does_not_call_the_model(db, connected, monkeypatch):
    from app.bot import reminders

    monkeypatch.setattr(gmail, "list_screen", lambda *a, **k: [])
    monkeypatch.setattr(gmail, "triage", lambda *a, **k: pytest.fail("אין מה לסווג"))
    # ⚠️ רשימה ריקה ולא None: הסבב **כן** רץ, פשוט אין מה לסווג.
    # ‏None שמור ל"לא רץ הפעם", ועליו הלולאה מדלגת
    assert reminders.warm_mail_screen(db) == []


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
    assert reminders.warm_mail_screen(db) is None
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


# --- ארכוב (שלב 4-4) ---


@pytest.fixture
def modified(monkeypatch):
    """תופס את מה שנשלח לגוגל, בלי לפנות אליה."""
    calls = []

    def spy(db_, ids, payload):
        calls.append((list(ids), payload))
        return list(ids)

    monkeypatch.setattr(gmail, "_batch_modify", spy)
    return calls


def post_ids(client, path, ids):
    return client.post(f"/api/emails/{path}", json={"ids": ids})


def test_archiving_removes_the_mails_from_the_inbox(client, connected, modified):
    assert post_ids(client, "archive", ["gid-1"]).status_code == 200
    assert modified == [(["gid-1"], {"removeLabelIds": ["INBOX"]})]


def test_undo_puts_the_mails_back_in_the_inbox(client, connected, modified):
    assert post_ids(client, "unarchive", ["gid-1"]).status_code == 200
    assert modified == [(["gid-1"], {"addLabelIds": ["INBOX"]})]


def test_archiving_never_deletes_anything(client, connected, modified):
    """⚠️⚠️ ההבטחה המרכזית של 4-4: ארכוב מזיז, ולא מוחק.

    המייל נשאר בתיבה ונמצא בחיפוש, וזה מה שמצדיק פעולה שקורית מיד בלי
    שאלת אישור. אם מישהו יחליף את זה ב-trash או ב-delete, הבדיקה תיפול.
    """
    post_ids(client, "archive", ["gid-1", "gid-2"])
    post_ids(client, "unarchive", ["gid-1", "gid-2"])
    for _, payload in modified:
        touched = payload.get("removeLabelIds", []) + payload.get("addLabelIds", [])
        assert touched == ["INBOX"], "רק תווית הדואר הנכנס מותרת"
        assert "TRASH" not in touched
        assert "SPAM" not in touched


# --- 🚨 הבאג: ארכוב של שרשור, ולא של הודעה אחת ---


def test_the_whole_thread_is_archived_and_not_just_the_newest(client, connected, monkeypatch, modified):
    """🚨 הבאג שנמצא 24.11.2026 ותוקן כאן.

    הרשימה מציגה שורה לכל שרשור. ארכוב ההודעה האחרונה בלבד השאיר את
    הישנה עם INBOX, **והשורה חזרה ברענון הבא**. האימות מקצה לקצה לא
    תפס את זה כי הוא רץ על מייל בודד.
    """
    row = mail(1)
    row.thread_ids = ["gid-1", "gid-9"]
    row.thread_count = 2
    listed(monkeypatch, [row])
    item = client.get("/api/emails").json()["items"][0]
    assert item["thread_ids"] == ["gid-1", "gid-9"]

    post_ids(client, "archive", item["thread_ids"])
    assert modified == [(["gid-1", "gid-9"], {"removeLabelIds": ["INBOX"]})]


def test_the_list_reports_every_inbox_message_of_the_thread(client, connected, monkeypatch):
    """בלי זה המסך אינו יודע מה לשלוח לארכוב."""
    first, second = mail(1), mail(2)
    first.thread_id = second.thread_id = "th-same"
    rows = gmail.collapse_threads([first, second])
    listed(monkeypatch, rows)
    item = client.get("/api/emails").json()["items"][0]
    assert sorted(item["thread_ids"]) == ["gid-1", "gid-2"]
    assert item["thread_count"] == 2


def test_a_single_mail_still_reports_itself(client, connected, monkeypatch):
    listed(monkeypatch, gmail.collapse_threads([mail(1)]))
    assert client.get("/api/emails").json()["items"][0]["thread_ids"] == ["gid-1"]


def test_undo_returns_exactly_what_was_archived(client, connected, modified):
    """⚠️⚠️ ולא את כל השרשור: אחרת הביטול היה מחזיר לדואר הנכנס הודעה
    שהייתה מארוכבת עוד קודם, והמשתמש היה מקבל בחזרה משהו שלא ארכב."""
    archived = post_ids(client, "archive", ["gid-1", "gid-9"]).json()["ids"]
    assert archived == ["gid-1", "gid-9"]
    post_ids(client, "unarchive", archived)
    assert modified[-1] == (["gid-1", "gid-9"], {"addLabelIds": ["INBOX"]})


# --- ארכוב קבוצתי ---


def test_many_mails_go_in_one_call(client, connected, modified):
    """⚠️ אצווה ולא לולאה: קריאת רשת אחת, לא אחת לכל מייל."""
    ids = [f"gid-{number}" for number in range(30)]
    assert post_ids(client, "archive", ids).status_code == 200
    assert len(modified) == 1
    assert modified[0][0] == ids


def test_an_empty_list_is_rejected(client, connected, modified):
    assert post_ids(client, "archive", []).status_code == 422
    assert modified == []


def test_an_absurd_batch_is_rejected(client, connected, modified):
    assert post_ids(client, "archive", [f"g{n}" for n in range(1001)]).status_code == 422
    assert modified == []


def test_the_batch_endpoint_is_used_and_not_a_loop(db, connected, monkeypatch):
    """⚠️ גם שכבת השירות: כתובת אחת, batchModify, ולא modify לכל מייל."""
    seen = []
    monkeypatch.setattr(
        gmail.httpx, "post", lambda url, **kw: seen.append((url, kw.get("json"))) or _ok_response()
    )
    gmail.archive(db, ["gid-1", "gid-2"])
    assert len(seen) == 1
    url, body = seen[0]
    assert url.endswith("/messages/batchModify")
    assert body["ids"] == ["gid-1", "gid-2"]
    assert not any("trash" in url.lower() or "delete" in url.lower() for url, _ in seen)


def test_nothing_is_sent_for_an_empty_list(db, connected, monkeypatch):
    monkeypatch.setattr(
        gmail.httpx, "post", lambda *a, **k: pytest.fail("אין לפנות לגוגל על רשימה ריקה")
    )
    assert gmail.archive(db, []) == []


class _ok_response:
    status_code = 204

    def json(self):
        return {}


def test_archiving_without_a_connection_says_to_connect(client, modified):
    response = post_ids(client, "archive", ["gid-1"])
    assert response.status_code == 503
    assert "הגדרות" in response.json()["detail"]
    assert modified == []


def test_a_failed_archive_is_a_502(client, connected, monkeypatch):
    def boom(*a, **k):
        raise gmail.GmailError("גוגל החזירה 500")

    monkeypatch.setattr(gmail, "_batch_modify", boom)
    response = post_ids(client, "archive", ["gid-1"])
    assert response.status_code == 502
    assert "לנסות שוב" in response.json()["detail"]


def test_a_revoked_connection_during_an_archive_is_a_503(client, connected, monkeypatch):
    def boom(*a, **k):
        raise gauth.GoogleDisconnected("invalid_grant")

    monkeypatch.setattr(gmail, "_batch_modify", boom)
    assert post_ids(client, "archive", ["gid-1"]).status_code == 503


def test_archiving_requires_a_login(anon, connected, modified):
    assert anon.post("/api/emails/archive", json={"ids": ["gid-1"]}).status_code == 401
    assert anon.post("/api/emails/unarchive", json={"ids": ["gid-1"]}).status_code == 401
    assert modified == []


def test_an_archived_mail_is_gone_from_the_next_list(client, connected, monkeypatch, modified):
    """הרשימה נשענת על in:inbox, ולכן מייל שאורכב פשוט אינו חוזר בה.

    זה מה שמייתר מצב מקומי בשרת: אין "רשימת מאורכבים" לתחזק.
    """
    listed(monkeypatch, [mail(1), mail(2)])
    assert len(client.get("/api/emails").json()["items"]) == 2
    post_ids(client, "archive", ["gid-1"])
    listed(monkeypatch, [mail(2)])
    assert [item["id"] for item in client.get("/api/emails").json()["items"]] == ["gid-2"]


# --- הפוך למשימה (שלב 4-5) ---


@pytest.fixture
def drafted(monkeypatch):
    """הצעה קבועה, בלי לקרוא למודל."""
    monkeypatch.setattr(
        gmail,
        "task_draft",
        lambda mail: gmail.TaskDraft(
            title="לחתום על ההסכם", due_date="2026-12-01", summary="דני מבקש חתימה"
        ),
    )


def test_the_draft_says_what_to_do_and_not_the_subject(client, connected, monkeypatch, drafted):
    """⚠️ נושא המייל אינו כותרת משימה. אומת מול התיבה ב-23.11.2026."""
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1))
    body = client.get("/api/emails/gid-1/task-draft").json()
    assert body["title"] == "לחתום על ההסכם"
    assert body["due_date"] == "2026-12-01"


def test_the_draft_attaches_the_client_by_the_sender_address(client, connected, db, monkeypatch, drafted):
    """⚠️ בקוד ולא במודל: שיוך הוא עובדה שיש עליה נתונים."""
    db.add(Client(name="דני ובניו", email="Dani@Example.com"))
    db.commit()
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1))
    assert client.get("/api/emails/gid-1/task-draft").json()["client_id"] is not None


def test_an_unknown_sender_leaves_the_client_empty(client, connected, monkeypatch, drafted):
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1))
    assert client.get("/api/emails/gid-1/task-draft").json()["client_id"] is None


def test_the_notes_carry_a_link_back_to_gmail(client, connected, monkeypatch, drafted):
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1))
    notes = client.get("/api/emails/gid-1/task-draft").json()["notes"]
    assert "https://mail.google.com/" in notes
    assert "gid-1" in notes


def test_the_draft_saves_nothing(client, connected, db, monkeypatch, drafted):
    """⚠️⚠️ ההבטחה של 4-5: עד "שמור" לא נוצר כלום.

    זה היתרון המרכזי של המסך על הבוט — הפיכת מייל למשימה כמעט תמיד
    דורשת עריכה.
    """
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1))
    assert client.get("/api/emails/gid-1/task-draft").status_code == 200
    db.expire_all()
    assert db.scalars(select(Task)).all() == []


def test_a_task_from_a_mail_remembers_which_mail(client, connected, db):
    """המזהה נשמר, ולכן אפשר לחזור למייל מתוך המשימה."""
    created = client.post(
        "/api/tasks", json={"title": "לחתום", "email_message_id": "gid-1"}
    ).json()
    assert created["email_message_id"] == "gid-1"
    assert created["source"] == "email"


def test_a_task_without_a_mail_stays_a_dashboard_task(client, connected):
    """⚠️ המקור נגזר מהנוכחות של המזהה ולא משדה שהלקוח מצהיר."""
    created = client.post("/api/tasks", json={"title": "משימה רגילה"}).json()
    assert created["email_message_id"] is None
    assert created["source"] == "dashboard"


def test_the_draft_without_a_connection_says_to_connect(client, monkeypatch, drafted):
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1))
    response = client.get("/api/emails/gid-1/task-draft")
    assert response.status_code == 503
    assert "הגדרות" in response.json()["detail"]


def test_a_gmail_failure_during_the_draft_is_a_502(client, connected, monkeypatch, drafted):
    def boom(*a, **k):
        raise gmail.GmailError("רשת")

    monkeypatch.setattr(gmail, "fetch_full", boom)
    assert client.get("/api/emails/gid-1/task-draft").status_code == 502


def test_the_draft_requires_a_login(anon, connected, monkeypatch, drafted):
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1))
    assert anon.get("/api/emails/gid-1/task-draft").status_code == 401


# --- נתיבי המענה (שלב 4-4) ---


@pytest.fixture
def no_send(monkeypatch):
    """⚠️ שום בדיקה אינה שולחת מייל. תופס את השליחה ומדווח מה יצא."""
    calls = []

    def spy(db_, mid, body):
        calls.append((mid, body))
        return gmail.ReplyTarget(to="dani@example.com", subject="Re: נושא", thread_id="th-1")

    monkeypatch.setattr(gmail, "send_reply", spy)
    return calls


def test_the_draft_says_where_the_reply_will_go(client, connected, monkeypatch):
    monkeypatch.setattr(
        gmail,
        "reply_target",
        lambda db_, mid: gmail.ReplyTarget(to="dani@example.com", subject="Re: נושא", thread_id="t"),
    )
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1))
    monkeypatch.setattr(
        gmail,
        "reply_suggestions",
        lambda mail, block="": [gmail.ReplyOption(label="מאשר", text="בסדר גמור")],
    )
    body = client.get("/api/emails/gid-1/reply-draft").json()
    assert body["to"] == "dani@example.com"
    assert body["options"][0]["label"] == "מאשר"


def test_asking_for_a_draft_sends_nothing(client, connected, monkeypatch, no_send):
    """⚠️⚠️ הכנת תשובה אינה שליחה."""
    monkeypatch.setattr(
        gmail,
        "reply_target",
        lambda db_, mid: gmail.ReplyTarget(to="a@b.com", subject="Re: x", thread_id="t"),
    )
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1))
    monkeypatch.setattr(gmail, "reply_suggestions", lambda mail, block="": [])
    assert client.get("/api/emails/gid-1/reply-draft").status_code == 200
    assert no_send == []


def test_sending_passes_only_the_body_and_the_mail_id(client, connected, no_send, modified):
    """⚠️⚠️ הנמען אינו מגיע מהלקוח — הוא נקרא בשרת מהמייל המקורי."""
    response = client.post("/api/emails/gid-1/reply", json={"body": "בסדר גמור"})
    assert response.status_code == 200
    assert no_send == [("gid-1", "בסדר גמור")]
    assert response.json()["to"] == "dani@example.com"


def test_an_empty_reply_is_rejected_before_it_reaches_google(client, connected, no_send):
    assert client.post("/api/emails/gid-1/reply", json={"body": ""}).status_code == 422
    assert no_send == []


def test_the_mail_is_archived_after_a_successful_send(client, connected, no_send, modified):
    assert client.post("/api/emails/gid-1/reply", json={"body": "טקסט"}).json()["archived"] is True
    assert modified == [(["gid-1"], {"removeLabelIds": ["INBOX"]})]


def test_a_failed_archive_does_not_fail_the_send(client, connected, no_send, monkeypatch):
    """⚠️⚠️ המייל כבר יצא ואי אפשר להחזיר אותו. התשובה מדווחת שהארכוב
    נכשל, והמסך אומר את זה — אבל השליחה הצליחה."""

    def boom(*a, **k):
        raise gmail.GmailError("רשת")

    monkeypatch.setattr(gmail, "archive", boom)
    body = client.post("/api/emails/gid-1/reply", json={"body": "טקסט"}).json()
    assert body["archived"] is False
    assert body["to"] == "dani@example.com"
    assert no_send != []


def test_a_failed_send_is_a_502_and_archives_nothing(client, connected, monkeypatch, modified):
    def boom(*a, **k):
        raise gmail.GmailError("גוגל החזירה 500")

    monkeypatch.setattr(gmail, "send_reply", boom)
    assert client.post("/api/emails/gid-1/reply", json={"body": "טקסט"}).status_code == 502
    # ⚠️ לא נשלח, ולכן גם לא מארכבים
    assert modified == []


def test_replying_without_a_connection_says_to_connect(client, no_send):
    response = client.post("/api/emails/gid-1/reply", json={"body": "טקסט"})
    assert response.status_code == 503
    assert no_send == []


def test_replying_requires_a_login(anon, connected, no_send):
    assert anon.post("/api/emails/gid-1/reply", json={"body": "טקסט"}).status_code == 401
    assert anon.get("/api/emails/gid-1/reply-draft").status_code == 401
    assert no_send == []


# --- הכנת טיוטות מראש ---
#
# ⚠️⚠️ הבדיקות כאן שומרות על מה שמגביל את העלות. בלי "טיוטה אחת לכל
# מייל, אי פעם", המנגנון הזה מייצר מחדש טיוטת Opus לכל מייל בתיבה בכל
# סבב — מאות פעמים ביום.


@pytest.fixture(autouse=True)
def clean_prepared():
    gmail.clear_prepared()
    yield
    gmail.clear_prepared()


@pytest.fixture
def no_models(monkeypatch):
    """סופר קריאות למודל, בלי לקרוא לו."""
    calls = {"task": 0, "reply": 0}

    def task(mail):
        calls["task"] += 1
        return gmail.TaskDraft(title="לעשות", due_date="", summary="")

    def reply(mail, block=""):
        calls["reply"] += 1
        return [gmail.ReplyOption(label="מאשר", text="בסדר")]

    monkeypatch.setattr(gmail, "task_draft", task)
    monkeypatch.setattr(gmail, "reply_suggestions", reply)
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(1))
    return calls


def triaged_as(monkeypatch, rows, needs_reply_ids=()):
    monkeypatch.setattr(gmail, "list_screen", lambda *a, **k: rows)
    monkeypatch.setattr(
        gmail,
        "triage",
        lambda emails, client_emails=None: [
            gmail.Triaged(
                email=item,
                relevant=True,
                line="שורה",
                needs_reply=item.id in needs_reply_ids,
            )
            for item in emails
        ],
    )


def test_a_task_draft_is_prepared_for_a_new_mail(db, connected, monkeypatch, no_models):
    from app.bot import reminders

    triaged_as(monkeypatch, [mail(1)])
    assert reminders.prepare_drafts(db)[0] == 1
    assert no_models["task"] == 1


def test_the_same_mail_is_never_prepared_twice(db, connected, monkeypatch, no_models):
    """⚠️⚠️ זה מה שמגביל את העלות. בלי זה כל סבב מכין הכול מחדש."""
    from app.bot import reminders

    triaged_as(monkeypatch, [mail(1)])
    reminders.prepare_drafts(db)
    reminders.prepare_drafts(db)
    reminders.prepare_drafts(db)
    assert no_models["task"] == 1


def test_a_restart_does_not_cause_a_second_preparation(db, connected, monkeypatch, no_models):
    """⚠️⚠️ המטמון בזיכרון נמחק בכל פריסה, והחותמת במסד שורדת.

    בלי החותמת, כל הפעלה מחדש הייתה מכינה מחדש טיוטה לכל מייל בתיבה —
    ועל מענה זה מודל יקר.
    """
    from app.bot import reminders

    triaged_as(monkeypatch, [mail(1)])
    reminders.prepare_drafts(db)
    # הפעלה מחדש: הזיכרון נמחק, המסד נשאר
    gmail.clear_prepared()
    reminders.prepare_drafts(db)
    assert no_models["task"] == 1


def test_a_mail_that_arrived_after_the_stamp_is_prepared(db, connected, monkeypatch, no_models):
    from app.bot import reminders

    triaged_as(monkeypatch, [mail(1)])
    reminders.prepare_drafts(db)
    # מייל חדש יותר מהחותמת
    later = mail(2)
    later.received_at = now().astimezone(IL) + timedelta(minutes=5)
    triaged_as(monkeypatch, [later])
    assert reminders.prepare_drafts(db)[0] == 1
    assert no_models["task"] == 2


def test_replies_are_prepared_only_at_the_chosen_hours(db, connected, monkeypatch, no_models):
    """⚠️ המענה יקר פי חמישים מהמשימה, ולכן אינו רץ בכל סבב."""
    from app.bot import reminders

    triaged_as(monkeypatch, [mail(1)], needs_reply_ids={"gid-1"})
    monkeypatch.setattr(reminders, "_prepare_hours", lambda: {7})

    at_nine = now().astimezone(IL).replace(hour=9, minute=0)
    assert reminders.prepare_drafts(db, moment=at_nine)[1] == 0
    assert no_models["reply"] == 0

    gmail.clear_prepared()
    at_seven = now().astimezone(IL).replace(hour=7, minute=0)
    assert reminders.prepare_drafts(db, moment=at_seven)[1] == 1
    assert no_models["reply"] == 1


def test_a_mail_that_needs_no_reply_gets_no_reply_draft(db, connected, monkeypatch, no_models):
    """⚠️ חשבונית חשובה, אבל עונים עליה בתשלום ולא במילים."""
    from app.bot import reminders

    triaged_as(monkeypatch, [mail(1)], needs_reply_ids=set())
    monkeypatch.setattr(reminders, "_prepare_hours", lambda: {7})
    at_seven = now().astimezone(IL).replace(hour=7, minute=0)
    reminders.prepare_drafts(db, moment=at_seven)
    assert no_models["reply"] == 0
    # אבל טיוטת המשימה כן הוכנה
    assert no_models["task"] == 1


def test_without_a_google_connection_nothing_is_prepared(db, monkeypatch, no_models):
    from app.bot import reminders

    monkeypatch.setattr(
        gmail, "list_screen", lambda *a, **k: pytest.fail("אין לפנות לגוגל בלי חיבור")
    )
    assert reminders.prepare_drafts(db) == (0, 0)


def test_a_failed_preparation_never_touches_the_reminders(db, connected, monkeypatch):
    """⚠️ ההכנה היא נוחות ולא תלות."""
    from app.bot import reminders

    monkeypatch.setattr(
        gmail, "list_screen", lambda *a, **k: (_ for _ in ()).throw(gmail.GmailError("רשת"))
    )
    reminders._tick()


def test_the_prepared_draft_is_served_without_calling_the_model(
    client, connected, monkeypatch, no_models
):
    """הלחיצה מגישה את מה שהוכן, ולא מכינה מחדש."""
    from app.bot import reminders

    triaged_as(monkeypatch, [mail(1)])
    reminders.prepare_drafts(db=SessionLocal())
    before = no_models["task"]
    assert client.get("/api/emails/gid-1/task-draft").status_code == 200
    assert no_models["task"] == before


def test_a_mail_without_a_prepared_draft_still_works(client, connected, monkeypatch, no_models):
    """⚠️ נוחות ולא תנאי: בלי הכנה, הלחיצה מכינה בזמן אמת."""
    assert client.get("/api/emails/gid-9/task-draft").status_code == 200
    assert no_models["task"] == 1


def test_the_reply_draft_reports_when_it_was_prepared(client, connected, monkeypatch, no_models):
    """המשתמש צריך לדעת שהוא קורא טקסט שנכתב לפני כמה שעות."""
    monkeypatch.setattr(
        gmail,
        "reply_target",
        lambda db_, mid: gmail.ReplyTarget(to="a@b.com", subject="Re: x", thread_id="t"),
    )
    gmail.remember_prepared(
        "gid-1", now(), replies=[gmail.ReplyOption(label="מאשר", text="בסדר")]
    )
    body = client.get("/api/emails/gid-1/reply-draft").json()
    assert body["prepared_at"] is not None
    assert no_models["reply"] == 0


def test_a_fresh_reply_draft_has_no_prepared_at(client, connected, monkeypatch, no_models):
    monkeypatch.setattr(
        gmail,
        "reply_target",
        lambda db_, mid: gmail.ReplyTarget(to="a@b.com", subject="Re: x", thread_id="t"),
    )
    body = client.get("/api/emails/gid-1/reply-draft").json()
    assert body["prepared_at"] is None
    assert no_models["reply"] == 1


def test_the_configured_hours_are_read_from_settings(monkeypatch):
    from app.bot import reminders

    monkeypatch.setattr(gmail.get_settings(), "reply_prepare_hours", "7,12,17")
    assert reminders._prepare_hours() == {7, 12, 17}
    monkeypatch.setattr(gmail.get_settings(), "reply_prepare_hours", "6, 18 ,99,לא")
    assert reminders._prepare_hours() == {6, 18}


def test_the_preparation_does_not_fetch_the_mailbox_on_every_tick(db, connected, monkeypatch, no_models):
    """⚠️⚠️ באג שנתפס לפני שהגיע לשימוש: ההכנה רצה בכל טיק (כל 30
    שניות) ושלפה את התיבה מגוגל בעצמה — שליפה מלאה פעמיים בדקה.

    עכשיו החימום מחזיר את השורות המסווגות וההכנה רוכבת עליהן, ולכן
    הלולאה פונה לגוגל רק כשהחימום באמת רץ (פעם ב-20 דקות).
    """
    from app.bot import reminders

    fetches = []

    def counted(db_, scope, *a, **k):
        fetches.append(scope)
        return [mail(1)]

    monkeypatch.setattr(gmail, "list_screen", counted)
    monkeypatch.setattr(
        gmail,
        "triage",
        lambda emails, client_emails=None: [
            gmail.Triaged(email=item, relevant=True, line="שורה") for item in emails
        ],
    )
    reminders.reset_warm_clock()
    reminders._tick()
    reminders._tick()
    reminders._tick()
    # שלושה טיקים, שליפה אחת
    assert len(fetches) == 1


def test_the_warmup_hands_its_rows_to_the_preparation(db, connected, monkeypatch, no_models):
    """⚠️ שליפה אחת לשניהם, ולא אחת לכל אחד."""
    from app.bot import reminders

    triaged_as(monkeypatch, [mail(1)])
    reminders.reset_warm_clock()
    rows = reminders.warm_mail_screen(db)
    assert rows and len(rows) == 1
    # ההכנה מקבלת אותן ואינה שולפת שוב
    monkeypatch.setattr(
        gmail, "list_screen", lambda *a, **k: pytest.fail("אין לשלוף שוב")
    )
    assert reminders.prepare_drafts(db, rows)[0] == 1


# --- סיכום והתראות (שלב 4-6) ---
#
# ⚠️ ההודעות האלה יוזמות, ולכן מגיעות בלי צליל עד שהבוט יעבור למספר
# משלו. המשתמש בחר במודע לבנות בכל זאת (24.11.2026).


def counts(week=29, today=4, important=2):
    return gmail.InboxCounts(week=week, today=today, important_today=important)


def waiting(thread="th-1", who="dani@example.com", days=4):
    return gmail.Waiting(thread_id=thread, who=who, days=days)


@pytest.fixture
def digest_ready(monkeypatch, connected):
    """הכול מוכן לסיכום, בלי לפנות לגוגל."""
    from app.bot import reminders

    monkeypatch.setattr(gmail, "inbox_counts", lambda db_: counts())
    monkeypatch.setattr(gmail, "waiting_for_you", lambda db_, me, days=3: [])
    monkeypatch.setattr(gmail, "awaiting_reply", lambda db_, me, days=3: [])
    monkeypatch.setattr(reminders, "_digest_hour", lambda: 7)


def at_seven():
    return now().astimezone(IL).replace(hour=7, minute=0, second=0, microsecond=0)


def test_the_digest_is_numbers_only(db, digest_ready, sent):
    """⚠️⚠️ ההכרעה של 4-6: סיכום = מספרים, בלי נושא ובלי שולח.

    מי שרוצה פירוט פותח את המסך.
    """
    from app.bot import reminders

    assert reminders.send_mail_digest(db, at_seven()) == 1
    body = sent[-1][1]
    assert "29" in body and "4" in body
    # שום שם, שום נושא
    assert "@" not in body


def test_the_digest_goes_out_once_a_day(db, digest_ready, sent):
    """⚠️ הלולאה רצה כל 30 שניות. בלי חותמת, הסיכום היה יוצא 120 פעמים."""
    from app.bot import reminders

    assert reminders.send_mail_digest(db, at_seven()) == 1
    assert reminders.send_mail_digest(db, at_seven()) == 0
    assert reminders.send_mail_digest(db, at_seven().replace(minute=59)) == 0
    assert len(sent) == 1


def test_the_digest_does_not_go_out_at_other_hours(db, digest_ready, sent):
    from app.bot import reminders

    assert reminders.send_mail_digest(db, at_seven().replace(hour=11)) == 0
    assert sent == []


def test_an_alert_names_who_and_how_long(db, connected, monkeypatch, sent):
    from app.bot import reminders

    monkeypatch.setattr(gmail, "inbox_counts", lambda db_: counts())
    monkeypatch.setattr(gmail, "waiting_for_you", lambda db_, me, days=3: [waiting()])
    monkeypatch.setattr(gmail, "awaiting_reply", lambda db_, me, days=3: [])
    monkeypatch.setattr(reminders, "_digest_hour", lambda: 7)

    reminders.send_mail_digest(db, at_seven())
    alert = sent[-1][1]
    assert "dani@example.com" in alert
    assert "4" in alert
    assert "מחכה לתשובה ממך" in alert


def test_the_same_thread_is_alerted_once_and_never_again(db, connected, monkeypatch, sent):
    """⚠️⚠️ בלי זה הבוט מתריע על אותו שרשור כל יום לנצח, והמשתמש
    מפסיק לקרוא את ההתראות — וזה הכשל שהורג את כל היכולת."""
    from app.bot import reminders

    monkeypatch.setattr(gmail, "inbox_counts", lambda db_: counts())
    monkeypatch.setattr(gmail, "waiting_for_you", lambda db_, me, days=3: [waiting()])
    monkeypatch.setattr(gmail, "awaiting_reply", lambda db_, me, days=3: [])
    monkeypatch.setattr(reminders, "_digest_hour", lambda: 7)

    assert reminders.send_mail_digest(db, at_seven()) == 2
    # למחרת: הסיכום יוצא שוב, ההתראה לא
    tomorrow = at_seven() + timedelta(days=1)
    assert reminders.send_mail_digest(db, tomorrow) == 1


def test_the_two_directions_are_tracked_separately(db, connected, monkeypatch, sent):
    """אותו שרשור יכול להיות גם "מחכה לך" וגם "לא ענו לך" בזמנים שונים."""
    from app.bot import reminders

    monkeypatch.setattr(gmail, "inbox_counts", lambda db_: counts())
    monkeypatch.setattr(gmail, "waiting_for_you", lambda db_, me, days=3: [waiting("th-9")])
    monkeypatch.setattr(gmail, "awaiting_reply", lambda db_, me, days=3: [waiting("th-9")])
    monkeypatch.setattr(reminders, "_digest_hour", lambda: 7)
    # סיכום + שתי התראות על אותו שרשור, בשני כיוונים
    assert reminders.send_mail_digest(db, at_seven()) == 3


def test_without_a_google_connection_no_digest(db, monkeypatch, sent):
    from app.bot import reminders

    monkeypatch.setattr(
        gmail, "inbox_counts", lambda db_: pytest.fail("אין לפנות לגוגל בלי חיבור")
    )
    assert reminders.send_mail_digest(db, at_seven()) == 0


def test_a_failed_digest_never_touches_the_reminders(db, connected, monkeypatch):
    """⚠️ הסיכום הוא נוחות ולא תלות."""
    from app.bot import reminders

    monkeypatch.setattr(reminders, "_digest_hour", lambda: now().astimezone(IL).hour)
    monkeypatch.setattr(
        gmail, "inbox_counts", lambda db_: (_ for _ in ()).throw(gmail.GmailError("רשת"))
    )
    reminders._tick()


def test_the_alert_window_is_three_days_both_ways():
    """⚠️ שלושה ימים לשני הכיוונים — הוכרע 23.11.2026, ושינה את
    מה שנקבע ב-17.11 (יומיים לכיוון אחד, ארבעה לשני)."""
    assert gmail.ALERT_DAYS == 3


def test_the_digest_text_says_where_the_detail_is():
    """הבוט מצטמצם: הוא נותן מספר ומפנה למסך."""
    body = reminders_digest_text()
    assert "מסך" in body


def reminders_digest_text():
    from app.bot import reminders

    return reminders.digest_text(counts(), [], [])
