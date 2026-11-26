"""בדיקות למסך הוואטסאפ — הבוט בדשבורד.

⚠️⚠️ **מה שנבדק כאן הוא הבידוד בין הערוצים**, ולא רק שהנתיבים עונים.
המלכודת שהשלב הזה נבנה סביבה: וואטסאפ ממשיך להקליד מספרים, והמספור
נפתר מול "ההודעה הקודמת". הודעה שנכתבת במסך הופכת ל"קודמת", ואז
"סיימתי 2" בוואטסאפ סוגר את המשימה הלא נכונה — **בשקט**. אין כאן
שגיאה ואין חריגה, ולכן רק בדיקה יכולה לתפוס את זה.

⚠️ אין כאן אף קריאה למודל ואף פנייה לגוגל או ל-WAHA.
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app import waha
from app.bot import actions, briefs, outbox
from app.bot.intent import Intent
from app.db import SessionLocal
from app.models import BotMessage, Task


def task(db, title: str = "לבדוק משהו") -> Task:
    row = Task(title=title, status="open", source="whatsapp")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


_counter = iter(range(1, 10_000))


def message(db, channel: str, **fields) -> BotMessage:
    """שורה ביומן ההודעות, כאילו הגיעה מאותו ערוץ."""
    row = BotMessage(
        wa_message_id=fields.pop("wa_message_id", f"{channel}-{next(_counter)}"),
        channel=channel,
        **fields,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- המיגרציה ---


def test_an_existing_row_defaults_to_whatsapp(db):
    """⚠️ ברירת המחדל היא ``whatsapp``, אחרת כל ההיסטוריה שנצברה עד
    היום נראית כאילו נכתבה במסך."""
    db.execute(
        text("INSERT INTO bot_messages (wa_message_id, body) VALUES ('old-1', 'ישן')")
    )
    db.commit()
    row = db.scalars(select(BotMessage).where(BotMessage.wa_message_id == "old-1")).one()
    assert row.channel == "whatsapp"
    assert row.initiated is False
    assert row.handled_at is None


def test_the_channel_is_checked_by_the_database(db):
    """ערוץ שאינו אחד מהשניים נדחה במסד ולא רק בקוד."""
    from sqlalchemy.exc import IntegrityError

    db.add(BotMessage(wa_message_id="bad-1", channel="telegram"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- המלכודת: מספור מול הערוץ הנכון ---


def test_a_number_resolves_against_the_same_channel_only(db):
    """🚨 הבדיקה המרכזית של השלב.

    הבוט הציג רשימה בוואטסאפ, ואחר כך רשימה אחרת במסך. "סיימתי 1"
    שהוקלד בוואטסאפ חייב להצביע על הרשימה של וואטסאפ — אחרת הוא סוגר
    את המשימה שהוצגה במסך, בלי שאיש יראה.
    """
    first = task(db, "של וואטסאפ")
    second = task(db, "של המסך")
    message(db, "whatsapp", wa_message_id="wa-list", listed_task_ids=str(first.id))
    message(db, "screen", wa_message_id="screen-list", listed_task_ids=str(second.id))

    from_whatsapp = actions._resolve_by_number(db, 1, "whatsapp")
    from_screen = actions._resolve_by_number(db, 1, "screen")
    assert from_whatsapp is not None and from_whatsapp.id == first.id
    assert from_screen is not None and from_screen.id == second.id


def test_completing_by_number_closes_the_task_of_that_channel(db):
    """אותה מלכודת, מקצה לקצה דרך ``execute``."""
    mine = task(db, "משימה של וואטסאפ")
    other = task(db, "משימה של המסך")
    message(db, "whatsapp", wa_message_id="wa-list-2", listed_task_ids=str(mine.id))
    message(db, "screen", wa_message_id="screen-list-2", listed_task_ids=str(other.id))

    actions.execute(db, Intent(action="complete_task", task_number=1), None, "whatsapp")
    db.refresh(mine)
    db.refresh(other)
    assert mine.status == "done"
    assert other.status == "open", "נסגרה המשימה של הערוץ השני"


def test_an_email_number_resolves_against_the_same_channel_only(db):
    """אותו כלל למספור המיילים, שיושב בעמודה נפרדת."""
    from app.bot import emails

    message(db, "whatsapp", wa_message_id="wa-mail", listed_email_ids="gid-wa")
    message(db, "screen", wa_message_id="screen-mail", listed_email_ids="gid-screen")
    assert emails._resolve(db, 1, "whatsapp") == "gid-wa"
    assert emails._resolve(db, 1, "screen") == "gid-screen"


# --- המקור של המשימה ---


def test_a_task_from_the_screen_is_marked_as_coming_from_the_screen(db):
    """⚠️ ``source`` עונה על "מאיפה זה הגיע", ומשימה שנוצרה מול המסך
    לא הגיעה מהטלפון. עד התיקון היא נרשמה כ-``whatsapp``."""
    actions.execute(
        db, Intent(action="add_task", title="נוצרה מהמסך"), None, actions.SCREEN
    )
    row = db.scalars(select(Task).where(Task.title == "נוצרה מהמסך")).one()
    assert row.source == "screen"


def test_a_task_from_whatsapp_keeps_its_source(db):
    """⚠️ מה שעבד עד היום אינו משתנה בשקט."""
    actions.execute(
        db, Intent(action="add_task", title="נוצרה בוואטסאפ"), None, actions.WHATSAPP
    )
    row = db.scalars(select(Task).where(Task.title == "נוצרה בוואטסאפ")).one()
    assert row.source == "whatsapp"


def test_every_channel_maps_to_a_source_the_database_accepts(db):
    """⚠️⚠️ ``source`` מוגבל ב-CHECK במסד.

    ערוץ חדש שיתווסף בלי מיפוי היה הופך **כל יצירת משימה** בערוץ הזה
    לשגיאה, ולא לאייקון לא מדויק. לכן המיפוי מכסה את כל הערוצים, וכל
    ערך בו נבדק מול המסד.
    """
    assert set(actions.TASK_SOURCE) == {actions.WHATSAPP, actions.SCREEN}
    for index, source in enumerate(actions.TASK_SOURCE.values()):
        db.add(Task(title=f"בדיקת מקור {index}", status="open", source=source))
    db.commit()


def test_the_schema_doc_knows_the_new_source():
    """⚠️ ``SCHEMA_DOC`` הוא טקסט חופשי שהמודל כותב לפיו שאילתות, והוא
    התיישן כבר פעם אחת בלי ששום בדיקה נשברה."""
    from app import queries

    assert "'screen'" in queries.SCHEMA_DOC
    assert "screen" in queries.LABELS["source"]


# --- אישור מול הערוץ הנכון ---


def test_a_confirmation_does_not_cross_channels(db):
    """"כן" במסך אינו מאשר שאלה שנשאלה בוואטסאפ."""
    doomed = task(db, "למחוק אותי")
    message(
        db,
        "whatsapp",
        wa_message_id="wa-ask",
        reply="למחוק?",
        pending_json=json.dumps({"kind": "delete_task", "task_id": doomed.id}),
    )
    outcome = actions.execute(db, Intent(action="confirm"), None, "screen")
    assert "אין פעולה שמחכה לאישור" in outcome.reply
    assert db.get(Task, doomed.id) is not None


def test_an_initiated_message_does_not_break_a_confirmation(db):
    """🚨 ⚠️⚠️ תזכורת שנחתה בין השאלה לתשובה.

    מרגע שהודעות יוזמות נרשמות ביומן, הן עלולות להיות "ההודעה
    הקודמת" — ואז "כן" היה עונה "אין מה לאשר". זה באג שנולד מהשלב
    הזה עצמו, ולכן הוא נבדק.
    """
    doomed = task(db, "למחוק אותי")
    message(
        db,
        "whatsapp",
        wa_message_id="wa-ask-2",
        reply="למחוק?",
        pending_json=json.dumps({"kind": "delete_task", "task_id": doomed.id}),
    )
    message(db, "whatsapp", wa_message_id="sys:reminder:x", initiated=True, reply="תזכורת")

    outcome = actions.execute(db, Intent(action="confirm"), None, "whatsapp")
    assert "נמחק" in outcome.reply
    assert db.get(Task, doomed.id) is None


def test_undo_does_not_cross_channels(db):
    """"בטל" מבטל את מה שנעשה מול אותו ערוץ בלבד."""
    created = task(db, "נוצרה מהמסך")
    message(
        db,
        "screen",
        wa_message_id="screen-add",
        intent="add_task",
        task_id=created.id,
        reply="נשמר",
    )
    outcome = actions.execute(db, Intent(action="cancel_last"), None, "whatsapp")
    assert outcome.reply == "אין מה לבטל."
    assert db.get(Task, created.id) is not None


# --- ההיסטוריה שנשלחת למודל ---


def test_the_prompt_history_is_per_channel_and_without_initiated(db):
    """⚠️ מה שנכתב במסך אינו ההקשר של מה שנכתב בוואטסאפ, ותזכורת
    אינה דבר שהמשתמש אמר."""
    message(db, "screen", wa_message_id="s-1", body="שאלה במסך", reply="תשובה במסך")
    message(db, "whatsapp", wa_message_id="w-1", body="שאלה בוואטסאפ", reply="תשובה בוואטסאפ")
    message(db, "whatsapp", wa_message_id="sys:reminder:y", initiated=True, reply="תזכורת")

    history = actions.build_history(db, 10_000, "whatsapp")
    assert "שאלה בוואטסאפ" in history
    assert "שאלה במסך" not in history
    assert "תזכורת" not in history


# --- הודעות שהמערכת יוזמת ---


def test_an_initiated_message_is_recorded(db, sent):
    outbox.send("972500000000", "תזכורת: להתקשר לדני", outbox.REMINDER, "task-1-202611261000")
    assert sent == [("972500000000", "תזכורת: להתקשר לדני")]
    row = db.scalars(select(BotMessage).where(BotMessage.initiated.is_(True))).one()
    assert row.channel == "whatsapp"
    assert row.body is None
    assert row.reply == "תזכורת: להתקשר לדני"
    assert row.intent == outbox.REMINDER


def test_the_same_alert_is_recorded_once(db):
    """⚠️ מזהה מלאכותי ייחודי: אותה התראה אינה נרשמת פעמיים."""
    outbox.record("מישהו מחכה לך", outbox.MAIL_ALERT, "waiting-th-1")
    outbox.record("מישהו מחכה לך", outbox.MAIL_ALERT, "waiting-th-1")
    assert len(db.scalars(select(BotMessage)).all()) == 1


def test_recording_runs_in_its_own_transaction(db):
    """⚠️⚠️ הרישום אינו יכול לפגוע במה שהוא מתעד.

    ``reminders`` ו-``briefs`` מחזיקים שינויים לא שמורים בעסקה שלהם
    (``reminder_sent_at``, ``EventBrief``). מזהה כפול שעושה
    ``rollback`` בעסקה שלהם היה מוחק אותם.
    """
    open_task = task(db, "לא לאבד אותי")
    open_task.title = "שונה ולא נשמר"
    outbox.record("משהו", outbox.MAIL_DIGEST, "2026-11-26")
    assert open_task.title == "שונה ולא נשמר", "הרישום עשה rollback לעסקה של הקורא"


def test_the_brief_is_journalled_without_the_meeting_title():
    """⚠️⚠️ גבול פרטיות ולא קיצור.

    ``privacy.html`` מבטיח שהתדריך אינו שומר את הפגישה. השורה
    הראשונה היא השעה והכותרת, ולכן היא אינה נרשמת.
    """
    full = "לפני הפגישה 10:00 — סודי לגמרי\nלקוח: דני\nפתוח מולו: 1"
    journalled = briefs.journal_text(full)
    assert "סודי לגמרי" not in journalled
    assert "10:00" not in journalled
    assert "לקוח: דני" in journalled


# --- הנתיבים ---


def test_a_screen_message_is_saved_with_the_screen_channel(client, db):
    res = client.post("/api/whatsapp/messages", json={"body": "תזכיר לי מחר"})
    assert res.status_code == 201
    body = res.json()
    assert body["channel"] == "screen"
    assert body["body"] == "תזכיר לי מחר"
    row = db.scalars(select(BotMessage).where(BotMessage.channel == "screen")).one()
    assert row.wa_message_id.startswith("screen:")
    assert row.initiated is False


def test_a_screen_message_never_goes_out_on_whatsapp(client, sent):
    """⚠️⚠️ ההכרעה: הודעה שנכתבה במסך נענית במסך בלבד.

    אחרת וואטסאפ מתמלא בהדים של עבודה שנעשתה במסך.
    """
    # ⚠️ ההתחברות עצמה שולחת קוד בוואטסאפ, ולכן מתאפס כאן ולא בפתיחה
    sent.clear()
    client.post("/api/whatsapp/messages", json={"body": "מה יש לי היום"})
    assert sent == []


def test_the_screen_router_does_not_send_on_whatsapp():
    """אותה הכרעה, כשומרת ארכיטקטורה: הנתיב אינו שולח ואינו מייבא כך.

    ⚠️ בדיקה על **קוד המקור**, כמו זו שאוסרת ``httpx.put`` ב-``gcal``:
    היא תיפול על מי שיוסיף שליחה בעתיד, גם אם היא לא תתבטא בבדיקה
    התנהגותית אחת.

    ⚠️⚠️ **נבדקת הקריאה ולא אזכור השם.** בדיקה שחיפשה את המחרוזת
    ``waha.send_text`` הייתה נופלת על ההסבר של עצמה בראש הקובץ — זה
    בדיוק מה שקרה ב-4ב-5, ולכן הסוגר הפותח הוא חלק מהתבנית.
    """
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "app" / "routers" / "whatsapp.py"
    code = source.read_text(encoding="utf-8")
    assert "send_text(" not in code
    assert "outbox." not in code


def test_the_history_shows_both_channels_marked(client, db):
    message(db, "whatsapp", wa_message_id="h-1", body="בוואטסאפ", reply="טוב")
    message(db, "screen", wa_message_id="h-2", body="במסך", reply="טוב")
    rows = client.get("/api/whatsapp/messages").json()["messages"]
    assert [row["channel"] for row in rows] == ["whatsapp", "screen"]


def test_a_listed_task_comes_back_as_a_button(client, db):
    """כפתורים במקום מספרים — ⚠️ מתוך הנתון שכבר קיים."""
    item = task(db, "להתקשר לדני")
    message(db, "whatsapp", wa_message_id="h-3", reply="1. להתקשר לדני", listed_task_ids=str(item.id))
    row = client.get("/api/whatsapp/messages").json()["messages"][0]
    assert row["tasks"] == [
        {"number": 1, "id": item.id, "title": "להתקשר לדני", "status": "open"}
    ]


def test_the_status_route_reports_what_waha_says(client, monkeypatch):
    monkeypatch.setattr(
        waha, "session_status", lambda: {"status": "WORKING", "phone": "972500000000", "error": ""}
    )
    body = client.get("/api/whatsapp/status").json()
    assert body["state"] == "connected"
    assert body["phone"] == "972500000000"


def test_an_unreachable_waha_is_not_a_disconnection(client, monkeypatch):
    """⚠️ "לא הצלחתי להגיע ל-WAHA" שונה מ"וואטסאפ ניתקה אותנו"."""
    monkeypatch.setattr(
        waha, "session_status", lambda: {"status": "", "phone": "", "error": "timeout"}
    )
    assert client.get("/api/whatsapp/status").json()["state"] == "unreachable"


def test_a_failed_session_says_that_reminders_stopped(client, monkeypatch):
    monkeypatch.setattr(
        waha, "session_status", lambda: {"status": "FAILED", "phone": "", "error": ""}
    )
    body = client.get("/api/whatsapp/status").json()
    assert body["state"] == "failed"
    assert "תזכורות" in body["message"]


def test_alerts_list_what_was_initiated_until_it_is_marked(client, db):
    outbox.record("מישהו מחכה לך 4 ימים", outbox.MAIL_ALERT, "waiting-th-9")
    rows = client.get("/api/whatsapp/alerts").json()
    assert len(rows) == 1
    assert rows[0]["initiated"] is True

    assert client.post(f"/api/whatsapp/messages/{rows[0]['id']}/handled").status_code == 200
    assert client.get("/api/whatsapp/alerts").json() == []


def test_unclear_lists_what_the_bot_did_not_understand(client, db):
    message(db, "whatsapp", wa_message_id="u-1", body="בלבלתי", intent="clarify", reply="למה התכוונת?")
    message(db, "screen", wa_message_id="u-2", body="עוד אחת", reply="לא הבנתי. אפשר לנסח שוב?")
    message(db, "whatsapp", wa_message_id="u-3", body="תקין", intent="add_task", reply="נשמר")
    rows = client.get("/api/whatsapp/unclear").json()
    assert {row["body"] for row in rows} == {"בלבלתי", "עוד אחת"}


# --- פעולות שלא אושרו ---


def stale(db, doomed: Task) -> BotMessage:
    row = message(
        db,
        "whatsapp",
        wa_message_id=f"p-{doomed.id}",
        reply="למחוק את המשימה?",
        pending_json=json.dumps({"kind": "delete_task", "task_id": doomed.id}),
    )
    # ⚠️ הזזת השעה במסד: הרשימה היא של מה שעבר את חלון רבע השעה
    row.created_at = row.created_at - timedelta(hours=2)
    db.commit()
    return row


def test_pending_lists_what_expired_without_an_answer(client, db):
    """⚠️⚠️ היום זה מתאדה בשקט: ביקשת למחוק, לא ענית בזמן, ושום דבר
    לא נמחק ושום דבר לא אמר לך."""
    doomed = task(db, "למחוק אותי")
    stale(db, doomed)
    rows = client.get("/api/whatsapp/pending").json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "delete_task"
    assert "למחוק אותי" in rows[0]["summary"]
    assert rows[0]["executable"] is True


def test_an_answered_question_is_not_listed(client, db):
    """שאלה שנענתה בזמן אינה "לא אושרה"."""
    doomed = task(db, "למחוק אותי")
    stale(db, doomed)
    message(db, "whatsapp", wa_message_id="p-answer", intent="decline", body="לא", reply="בסדר")
    assert client.get("/api/whatsapp/pending").json() == []


def test_a_fresh_question_is_not_listed_yet(client, db):
    """⚠️ בתוך רבע השעה עדיין אפשר לענות "כן" בוואטסאפ."""
    doomed = task(db, "למחוק אותי")
    message(
        db,
        "whatsapp",
        wa_message_id="p-fresh",
        reply="למחוק?",
        pending_json=json.dumps({"kind": "delete_task", "task_id": doomed.id}),
    )
    assert client.get("/api/whatsapp/pending").json() == []


def test_confirming_late_executes_and_records_it(client, db):
    """⚠️ מה שמבוצע נקרא מהשורה ולא מהלקוח, והביצוע נרשם כהודעה."""
    doomed = task(db, "למחוק אותי")
    row = stale(db, doomed)
    res = client.post(f"/api/whatsapp/pending/{row.id}/confirm")
    assert res.status_code == 201
    assert "נמחק" in res.json()["reply"]
    assert res.json()["channel"] == "screen"
    # ⚠️ המחיקה קרתה בעסקה של הנתיב; בלי ניתוק האובייקט מהסשן הוא חוזר
    # מהמטמון שלו, ו-``expire_all`` לבדו היה זורק ObjectDeletedError
    db.expunge_all()
    assert db.get(Task, doomed.id) is None
    assert client.get("/api/whatsapp/pending").json() == []


def test_confirming_twice_is_refused(client, db):
    doomed = task(db, "למחוק אותי")
    row = stale(db, doomed)
    assert client.post(f"/api/whatsapp/pending/{row.id}/confirm").status_code == 201
    assert client.post(f"/api/whatsapp/pending/{row.id}/confirm").status_code == 409


def test_a_pending_whose_task_is_gone_cannot_be_executed(client, db):
    """⚠️ התיאור נבנה מהנתונים מחדש, ולכן משימה שנמחקה בינתיים יורדת."""
    doomed = task(db, "למחוק אותי")
    row = stale(db, doomed)
    db.delete(db.get(Task, doomed.id))
    db.commit()
    assert client.get("/api/whatsapp/pending").json()[0]["executable"] is False
    assert client.post(f"/api/whatsapp/pending/{row.id}/confirm").status_code == 409


def test_dismissing_removes_without_executing(client, db):
    doomed = task(db, "למחוק אותי")
    row = stale(db, doomed)
    assert client.post(f"/api/whatsapp/pending/{row.id}/dismiss").status_code == 200
    assert client.get("/api/whatsapp/pending").json() == []
    db.expire_all()
    assert db.get(Task, doomed.id) is not None, "«הסר» ביצע את הפעולה"


def test_the_screen_needs_a_login(anon):
    assert anon.get("/api/whatsapp/messages").status_code == 401
    assert anon.post("/api/whatsapp/messages", json={"body": "היי"}).status_code == 401


def test_nothing_from_the_screen_is_written_outside_the_journal(client, db):
    """⚠️ הודעה במסך אינה יוצרת משימה בדרך — רק שורה ביומן."""
    client.post("/api/whatsapp/messages", json={"body": "תזכיר לי מחר להתקשר"})
    with SessionLocal() as raw:
        assert raw.scalars(select(Task)).all() == []
