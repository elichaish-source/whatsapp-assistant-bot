"""בדיקות לבוט וואטסאפ. אין בהן אף קריאה אמיתית ל-Claude API.

הפענוח נבדק בנפרד מהביצוע: לכל הבדיקות שמדמות הודעה אנחנו בונים Intent ביד,
בדיוק כמו שהמודל היה מחזיר, ובודקים מה המערכת עושה איתו.
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.bot import actions, reminders
from app.bot.intent import INTENT_SCHEMA, Intent, IntentError, build_user_message, extract
from app.models import BotMessage, Client, Domain, Task
from app.routers import bot as bot_router

OWNER = "972501234567"
OWNER_LID = "111222333444555"
HMAC_KEY = "test-hmac-key"


def sign(raw: bytes) -> str:
    return hmac.new(HMAC_KEY.encode(), raw, hashlib.sha512).hexdigest()


def event(body: str, message_id: str = "msg-1", **overrides) -> dict:
    payload = {
        "id": message_id,
        "from": f"{OWNER}@c.us",
        "to": f"{OWNER}@c.us",
        "fromMe": True,
        "source": "app",
        "body": body,
    }
    payload.update(overrides)
    return {"event": "message", "session": "default", "payload": payload}


def post(client, data: dict, signature: str | None = None):
    raw = json.dumps(data).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Hmac": signature if signature is not None else sign(raw),
    }
    return client.post("/api/bot/webhook", content=raw, headers=headers)


def domain_id(db, name: str) -> int:
    return db.scalars(select(Domain).where(Domain.name == name)).one().id


# --- ה-webhook ---


def test_rejects_wrong_signature(anon):
    assert post(anon, event("שלום"), signature="00").status_code == 401


def test_rejects_missing_signature(anon):
    raw = json.dumps(event("שלום")).encode()
    resp = anon.post("/api/bot/webhook", content=raw, headers={"Content-Type": "application/json"})
    assert resp.status_code == 401


def test_ignores_other_chats(anon, db):
    other = event("שלום", **{"from": "972500000000@c.us", "fromMe": False})
    assert post(anon, other).json()["skipped"] == "chat"
    assert db.scalars(select(BotMessage)).all() == []


def test_ignores_messages_the_bot_itself_sent(anon, db):
    """בלי הסינון הזה כל תשובה של הבוט הייתה חוזרת אליו כהודעה חדשה."""
    assert post(anon, event("נשמר: משהו", source="api")).json()["skipped"] == "chat"
    assert db.scalars(select(BotMessage)).all() == []


def test_ignores_other_events(anon):
    data = event("שלום")
    data["event"] = "message.ack"
    assert post(anon, data).json()["skipped"] == "event"


def test_ignores_empty_body(anon):
    assert post(anon, event("   ")).json()["skipped"] == "empty"


def test_same_message_handled_once(anon, db):
    first = post(anon, event("תזכיר לי להתקשר", "msg-dup"))
    second = post(anon, event("תזכיר לי להתקשר", "msg-dup"))
    assert first.json() == {"ok": True}
    assert second.json()["skipped"] == "duplicate"
    assert len(db.scalars(select(BotMessage)).all()) == 1


def test_without_api_key_the_user_gets_an_answer(anon, db, sent):
    """בלי ANTHROPIC_API_KEY הפענוח נכשל, והמשתמש חייב לקבל הודעה ולא שתיקה."""
    post(anon, event("תזכיר לי משהו", "msg-nokey"))
    row = db.scalars(select(BotMessage).where(BotMessage.wa_message_id == "msg-nokey")).one()
    assert "ANTHROPIC_API_KEY" in (row.error or "")
    assert sent and "לא הצלחתי לפענח" in sent[-1][1]


# --- חילוץ הכוונה ---


def test_extract_without_key_raises():
    with pytest.raises(IntentError):
        extract("שלום", "", datetime(2026, 11, 2, 9, 0))


def test_schema_matches_the_model():
    """הסכימה נכתבת ביד, ולכן צריכה להישאר מסונכרנת עם Intent."""
    assert set(INTENT_SCHEMA["properties"]) == set(Intent.model_fields)
    assert set(INTENT_SCHEMA["required"]) == set(Intent.model_fields)


def test_no_enum_sits_next_to_a_list_of_types():
    """‏structured outputs מחזיר 400 על enum יחד עם ["string", "null"].

    זה מה שהפיל את הבוט בבדיקה הראשונה מקצה לקצה, ולא נתפס בבדיקות כי
    הן לא קוראות ל-API. שדה שמותר בו null וגם מוגבל לערכים — דרך anyOf.
    """
    for name, prop in INTENT_SCHEMA["properties"].items():
        if "enum" in prop:
            assert isinstance(prop.get("type"), str), f"{name}: enum עם רשימת טיפוסים"
            assert None not in prop["enum"], f"{name}: null בתוך enum"
        for option in prop.get("anyOf", []):
            if "enum" in option:
                assert isinstance(option.get("type"), str), name
                assert None not in option["enum"], name


def test_nullable_enums_are_written_as_anyof():
    for name in ("priority", "list_filter"):
        options = INTENT_SCHEMA["properties"][name]["anyOf"]
        assert {"type": "null"} in options, name
        assert any("enum" in option for option in options), name


def test_user_message_states_the_time_and_puts_the_message_last():
    text = build_user_message("רשימה", "תחומים:\n  1: לקוחות", datetime(2026, 11, 2, 9, 30))
    assert "2026-11-02 09:30" in text
    assert text.rstrip().endswith("רשימה")


# --- הוספת משימה ---


def test_add_task_saves_and_reports(db):
    outcome = actions.execute(
        db,
        Intent(action="add_task", title="להתקשר לדני", domain_id=domain_id(db, "כספים")),
    )
    task = db.scalars(select(Task)).one()
    assert task.title == "להתקשר לדני"
    assert task.status == "open"
    assert task.from_bot is True
    assert "נשמר: להתקשר לדני" in outcome.reply
    assert outcome.task_id == task.id


def test_add_task_saves_even_without_a_domain(db):
    """הבוט לא עוצר כדי לשאול על תחום. זה היה הדבר הכי מעצבן בשימוש הראשון."""
    outcome = actions.execute(db, Intent(action="add_task", title="להתקשר לזיצר"))
    task = db.scalars(select(Task)).one()
    assert task.domain_id is None
    assert task.from_bot is True
    assert "נשמר: להתקשר לזיצר" in outcome.reply
    assert "לא שמרתי" not in outcome.reply


def test_add_task_keeps_the_reminder_in_local_time(db):
    actions.execute(
        db,
        Intent(
            action="add_task",
            title="להתקשר לדני",
            domain_id=domain_id(db, "כספים"),
            reminder_at="2026-11-03T10:00",
        ),
    )
    task = db.scalars(select(Task)).one()
    # 10:00 בישראל בנובמבר = 08:00 UTC
    assert task.reminder_at.astimezone(timezone.utc).hour == 8


def test_add_task_obeys_the_dashboard_rules(db):
    """תחום שמחייב לקוח לא נשמר בלי לקוח — אותו כלל בדיוק כמו בדשבורד."""
    outcome = actions.execute(
        db, Intent(action="add_task", title="לשלוח חוזה", domain_id=domain_id(db, "לקוחות"))
    )
    assert db.scalars(select(Task)).all() == []
    assert "לא שמרתי" in outcome.reply
    assert "לקוח" in outcome.reply


def test_add_task_without_a_title(db):
    outcome = actions.execute(db, Intent(action="add_task"))
    assert db.scalars(select(Task)).all() == []
    assert "לא הבנתי" in outcome.reply


# --- רשימה וסימון בוצע ---


def new_task(db, title: str, **kwargs) -> Task:
    task = Task(title=title, domain_id=domain_id(db, "כספים"), status="open", **kwargs)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_list_numbers_the_tasks_and_remembers_the_order(db):
    first = new_task(db, "ראשונה")
    second = new_task(db, "שנייה")
    outcome = actions.execute(db, Intent(action="list_tasks", list_filter="open"))
    assert "1. ראשונה" in outcome.reply
    assert "2. שנייה" in outcome.reply
    assert outcome.listed_task_ids == [first.id, second.id]


def test_empty_list(db):
    assert "אין משימות פתוחות" in actions.execute(db, Intent(action="list_tasks")).reply


def test_complete_by_number_from_the_last_list(db):
    task = new_task(db, "להתקשר לדני")
    db.add(BotMessage(wa_message_id="list-1", listed_task_ids=str(task.id)))
    db.commit()

    outcome = actions.execute(db, Intent(action="complete_task", task_number=1))
    db.refresh(task)
    assert task.status == "done"
    assert task.done_at is not None
    assert "סומן כבוצע" in outcome.reply


def test_complete_by_number_without_a_list(db):
    new_task(db, "להתקשר לדני")
    outcome = actions.execute(db, Intent(action="complete_task", task_number=2))
    assert "לא מצאתי" in outcome.reply


def test_complete_by_text(db):
    task = new_task(db, "לשלוח חוזה לאיתן")
    actions.execute(db, Intent(action="complete_task", task_text="חוזה"))
    db.refresh(task)
    assert task.status == "done"


def test_complete_by_text_asks_when_ambiguous(db):
    new_task(db, "להתקשר לדני")
    new_task(db, "להתקשר לדנה")
    outcome = actions.execute(db, Intent(action="complete_task", task_text="להתקשר"))
    assert "לאיזו התכוונת" in outcome.reply
    assert len(outcome.listed_task_ids) == 2
    assert db.scalars(select(Task).where(Task.status == "done")).all() == []


def test_complete_task_not_found(db):
    outcome = actions.execute(db, Intent(action="complete_task", task_text="אין כזה"))
    assert "לא מצאתי" in outcome.reply


# --- ביטול ---


def test_cancel_removes_the_task_the_bot_just_created(db):
    task = new_task(db, "להתקשר לדני", from_bot=True)
    db.add(BotMessage(wa_message_id="add-1", intent="add_task", task_id=task.id))
    db.commit()

    outcome = actions.execute(db, Intent(action="cancel_last"))
    assert "בוטל" in outcome.reply
    assert db.scalars(select(Task)).all() == []


def test_cancel_does_not_touch_dashboard_tasks(db):
    task = new_task(db, "משימה מהדשבורד")
    db.add(BotMessage(wa_message_id="add-2", intent="add_task", task_id=task.id))
    db.commit()

    outcome = actions.execute(db, Intent(action="cancel_last"))
    assert "לא נוצרה מהבוט" in outcome.reply
    assert db.scalars(select(Task)).one().id == task.id


def test_cancel_with_nothing_to_cancel(db):
    assert "אין מה לבטל" in actions.execute(db, Intent(action="cancel_last")).reply


# --- כוונות שאינן פעולה ---


def test_clarify_passes_the_question_through(db):
    outcome = actions.execute(db, Intent(action="clarify", question="לאיזה לקוח?"))
    assert outcome.reply == "לאיזה לקוח?"


def test_unknown_explains_what_to_write(db):
    assert "תזכיר לי" in actions.execute(db, Intent(action="unknown")).reply


# --- תזכורות ---


def test_due_reminder_is_sent_once(db, sent):
    moment = datetime.now(timezone.utc)
    task = new_task(db, "להתקשר לדני", reminder_at=moment - timedelta(minutes=1))

    assert reminders.send_due_reminders(db, moment) == 1
    assert "תזכורת: להתקשר לדני" in sent[-1][1]
    db.refresh(task)
    assert task.reminder_sent_at is not None
    # סבב נוסף לא שולח שוב
    assert reminders.send_due_reminders(db, moment) == 0


def test_future_reminder_is_not_sent(db, sent):
    moment = datetime.now(timezone.utc)
    new_task(db, "מחר", reminder_at=moment + timedelta(hours=2))
    assert reminders.send_due_reminders(db, moment) == 0
    assert sent == []


def test_done_task_gets_no_reminder(db, sent):
    moment = datetime.now(timezone.utc)
    task = new_task(db, "כבר סיימתי", reminder_at=moment - timedelta(minutes=5))
    task.status = "done"
    db.commit()
    assert reminders.send_due_reminders(db, moment) == 0


def test_old_reminder_is_skipped_not_flooded(db, sent):
    """אחרי שהשרת היה כבוי, תזכורות מהעבר הרחוק לא נשלחות."""
    moment = datetime.now(timezone.utc)
    task = new_task(db, "מלפני יומיים", reminder_at=moment - timedelta(days=2))

    assert reminders.send_due_reminders(db, moment) == 0
    assert sent == []
    db.refresh(task)
    assert task.reminder_sent_at is not None


def test_reminder_text_includes_the_client(db):
    client = Client(name="דני כהן")
    db.add(client)
    db.commit()
    task = new_task(db, "להתקשר", client_id=client.id)
    assert "דני כהן" in reminders.reminder_text(db, task)


# --- סינון הודעות ---


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"fromMe": True, "source": "app", "from": f"{OWNER}@c.us", "to": f"{OWNER}@c.us"}, True),
        ({"fromMe": True, "source": "api", "from": f"{OWNER}@c.us", "to": f"{OWNER}@c.us"}, False),
        ({"fromMe": False, "source": "app", "from": f"{OWNER}@c.us", "to": f"{OWNER}@c.us"}, False),
        ({"fromMe": True, "source": "app", "from": f"{OWNER}@c.us", "to": "972500000000@c.us"}, False),
        ({"fromMe": True, "source": "app", "from": "972500000000@c.us", "to": f"{OWNER}@c.us"}, False),
        ({}, False),
        # מבנה GOWS: אין שדה to, והשדה from הוא הצ'אט עצמו
        ({"fromMe": True, "source": "app", "from": f"{OWNER}@c.us", "to": None}, True),
        ({"fromMe": True, "source": "app", "from": "972500000000@c.us", "to": None}, False),
        ({"fromMe": True, "source": "api", "from": f"{OWNER}@c.us", "to": None}, False),
        # ‏GOWS מזהה חלק מהצ'אטים ב-LID ולא במספר
        ({"fromMe": True, "source": "app", "from": f"{OWNER_LID}@lid"}, True),
        ({"fromMe": True, "source": "app", "from": "999888777666@lid"}, False),
    ],
)
def test_only_the_self_chat_is_accepted(payload, expected):
    assert bot_router.is_owner_self_chat(payload) is expected
