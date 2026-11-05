"""בדיקות לבוט וואטסאפ. אין בהן אף קריאה אמיתית ל-Claude API.

הפענוח נבדק בנפרד מהביצוע: לכל הבדיקות שמדמות הודעה אנחנו בונים Intent ביד,
בדיוק כמו שהמודל היה מחזיר, ובודקים מה המערכת עושה איתו.
"""

import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.bot import actions, intent as intent_module, reminders
from app.bot.intent import (
    INTENT_SCHEMA,
    SYSTEM_PROMPT,
    Intent,
    IntentError,
    _system_blocks,
    build_user_message,
    extract,
)
from app import memory, recurring
from app.models import BotMessage, Client, Domain, MemoryFact, Observation, Recurrence, Task
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


def test_the_schema_stays_under_the_union_limit():
    """‏ה-API מגביל ל-16 שדות עם טיפוס איחוד, ומחזיר 400 על **כל** הודעה מעבר לזה.

    ב-5.11.2026 שלושה שדות חדשים העלו את המספר ל-18, והבוט ענה "לא הצלחתי
    לפענח" על כל דבר. הבדיקות לא תפסו את זה כי הן לא קוראות ל-API, ולכן
    הגבול נשמר כאן — בספירה, בלי קריאה.
    """
    unions = [
        name
        for name, prop in INTENT_SCHEMA["properties"].items()
        if "anyOf" in prop or isinstance(prop.get("type"), list)
    ]
    assert len(unions) <= intent_module.MAX_UNION_FIELDS, unions


def test_the_recurring_fields_have_an_empty_value_instead_of_null():
    """הם היוצאים מן הכלל שקונים את המקום מתחת לגבול, וצריכים להישאר כאלה."""
    for name in ("repeat_unit", "repeat_count", "lead_days"):
        prop = INTENT_SCHEMA["properties"][name]
        assert "anyOf" not in prop, name
        assert prop["type"] in ("string", "integer"), name
    assert Intent(action="add_task", title="x").repeat_unit == "none"
    assert "none" in SYSTEM_PROMPT


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
    assert task.source == "whatsapp"
    assert "נשמר: להתקשר לדני" in outcome.reply
    assert outcome.task_id == task.id


def test_add_task_saves_even_without_a_domain(db):
    """הבוט לא עוצר כדי לשאול על תחום. זה היה הדבר הכי מעצבן בשימוש הראשון."""
    outcome = actions.execute(db, Intent(action="add_task", title="להתקשר לזיצר"))
    task = db.scalars(select(Task)).one()
    assert task.domain_id is None
    assert task.source == "whatsapp"
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
    task = new_task(db, "להתקשר לדני", source="whatsapp")
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


# --- זיכרון שיחה ---


def logged(db, message_id: str, body: str, reply: str, **kwargs) -> BotMessage:
    row = BotMessage(wa_message_id=message_id, body=body, reply=reply, **kwargs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_history_is_empty_when_nothing_was_said(db):
    assert actions.build_history(db, 1) == ""


def test_history_shows_both_sides_oldest_first(db):
    logged(db, "h-1", "תזכיר לי להתקשר לזיצר", "נשמר: להתקשר לזיצר")
    last = logged(db, "h-2", "מה יש לי היום", "אין משימות פתוחות.")
    text = actions.build_history(db, last.id + 1)
    assert text.index("להתקשר לזיצר") < text.index("מה יש לי היום")
    assert "אני:" in text
    assert "העוזר:" in text


def test_history_leaves_out_the_message_being_handled(db):
    """ההודעה הנוכחית כבר רשומה ביומן כשהטיפול מתחיל, והיא לא חלק מהעבר."""
    logged(db, "h-3", "ההודעה הקודמת", "התשובה הקודמת")
    current = BotMessage(wa_message_id="h-4", body="ההודעה עכשיו")
    db.add(current)
    db.commit()
    db.refresh(current)

    text = actions.build_history(db, current.id)
    assert "ההודעה הקודמת" in text
    assert "ההודעה עכשיו" not in text


def test_history_forgets_what_is_older_than_the_window(db):
    old = datetime.now(timezone.utc) - actions.HISTORY_WINDOW - timedelta(minutes=1)
    logged(db, "h-5", "שיחה מלפני שעה", "תשובה מלפני שעה", created_at=old)
    assert actions.build_history(db, 10_000) == ""


def test_history_keeps_at_most_a_handful_of_exchanges(db):
    for index in range(actions.HISTORY_EXCHANGES + 3):
        logged(db, f"h-many-{index}", f"הודעה {index}", f"תשובה {index}")
    text = actions.build_history(db, 10_000)
    assert text.count("אני:") == actions.HISTORY_EXCHANGES
    assert "הודעה 0" not in text


def test_history_squeezes_a_reply_into_one_line(db):
    row = logged(db, "h-6", "תזכיר לי", 'נשמר: להתקשר\nעד 04/11\nלביטול כתוב "בטל".')
    text = actions.build_history(db, row.id + 1)
    assert 'נשמר: להתקשר עד 04/11 לביטול כתוב "בטל".' in text


def test_the_history_reaches_the_model_before_the_message():
    text = build_user_message(
        "בעצם ביום חמישי",
        "תחומים:\n  1: לקוחות",
        datetime(2026, 11, 3, 20, 0),
        "השיחה עד עכשיו (ישן → חדש):\n[20:41] אני: תזכיר לי מחר להתקשר לזיצר",
    )
    assert text.index("השיחה עד עכשיו") < text.index("ההודעה:")
    assert text.rstrip().endswith("בעצם ביום חמישי")


def test_without_history_the_message_looks_exactly_as_before():
    stamp = datetime(2026, 11, 3, 20, 0)
    assert build_user_message("רשימה", "תחומים:", stamp, "") == build_user_message(
        "רשימה", "תחומים:", stamp
    )


# --- תיקון המשימה האחרונה ---


def saved_by_bot(db, title: str, **kwargs) -> Task:
    task = new_task(db, title, source="whatsapp", **kwargs)
    db.add(BotMessage(wa_message_id=f"saved-{task.id}", intent="add_task", task_id=task.id))
    db.commit()
    return task


def test_update_last_changes_only_what_was_said(db):
    task = saved_by_bot(db, "להתקשר לזיצר", due_date=date(2026, 11, 4))
    outcome = actions.execute(db, Intent(action="update_last", due_date="2026-11-05"))
    db.refresh(task)
    assert task.title == "להתקשר לזיצר"
    assert task.due_date == date(2026, 11, 5)
    assert "עודכן: להתקשר לזיצר" in outcome.reply
    assert outcome.task_id == task.id


def test_update_last_lets_the_new_reminder_go_out(db):
    stamp = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
    task = saved_by_bot(db, "להתקשר לזיצר", reminder_at=stamp, reminder_sent_at=stamp)
    actions.execute(db, Intent(action="update_last", reminder_at="2026-12-01T10:00"))
    db.refresh(task)
    assert task.reminder_sent_at is None


def test_update_last_ignores_an_id_that_does_not_exist(db):
    """מזהה מומצא היה מפיל את העדכון על מפתח זר, והמשתמש לא היה מקבל תשובה."""
    task = saved_by_bot(db, "להתקשר לזיצר")
    outcome = actions.execute(db, Intent(action="update_last", client_id=9999))
    db.refresh(task)
    assert task.client_id is None
    assert "לא הבנתי מה לשנות" in outcome.reply


def test_update_last_moves_the_task_to_a_real_client(db):
    task = saved_by_bot(db, "להתקשר לזיצר")
    client = Client(name="זיצר")
    db.add(client)
    db.commit()
    db.refresh(client)

    actions.execute(db, Intent(action="update_last", client_id=client.id))
    db.refresh(task)
    assert task.client_id == client.id


def test_update_last_with_nothing_saved(db):
    outcome = actions.execute(db, Intent(action="update_last", priority="today"))
    assert "אין משימה אחרונה" in outcome.reply


def test_update_last_does_not_touch_dashboard_tasks(db):
    task = new_task(db, "משימה מהדשבורד")
    db.add(BotMessage(wa_message_id="dash-1", intent="add_task", task_id=task.id))
    db.commit()

    outcome = actions.execute(db, Intent(action="update_last", priority="today"))
    db.refresh(task)
    assert task.priority == "week"
    assert "לא נוצרה מהבוט" in outcome.reply


def test_cancel_also_undoes_a_task_that_was_updated(db):
    task = saved_by_bot(db, "להתקשר לזיצר")
    db.add(BotMessage(wa_message_id="upd-1", intent="update_last", task_id=task.id))
    db.commit()

    assert "בוטל" in actions.execute(db, Intent(action="cancel_last")).reply
    assert db.scalars(select(Task)).all() == []


# --- זיכרון ארוך-טווח ---


def facts(db) -> list[MemoryFact]:
    return list(db.scalars(select(MemoryFact).order_by(MemoryFact.id)).all())


def kinds(db) -> list[str]:
    return [row.kind for row in db.scalars(select(Observation).order_by(Observation.id)).all()]


def test_remember_saves_the_fact_with_its_dimension(db):
    outcome = actions.execute(db, Intent(action="remember", fact="דני הוא דני כהן מיעדים", dimension=1))
    fact = facts(db)[0]
    assert fact.content == "דני הוא דני כהן מיעדים"
    assert fact.dimension == 1
    assert fact.source == "bot"
    assert "נרשם בזיכרון" in outcome.reply
    assert "אנשים" in outcome.reply
    assert outcome.fact_id == fact.id


def test_remember_without_content_asks_again(db):
    outcome = actions.execute(db, Intent(action="remember", fact="   ", dimension=2))
    assert facts(db) == []
    assert "לא הבנתי מה לזכור" in outcome.reply


def test_remember_falls_back_to_a_real_dimension(db):
    """ממד שהמודל המציא לא אמור להפיל את השמירה, רק לקבל תווית ברירת מחדל."""
    actions.execute(db, Intent(action="remember", fact="משהו", dimension=99))
    assert facts(db)[0].dimension == memory.FALLBACK_DIMENSION


def test_remember_ignores_a_client_that_does_not_exist(db):
    actions.execute(db, Intent(action="remember", fact="משהו", dimension=1, client_id=4321))
    assert facts(db)[0].client_id is None


def test_remember_attaches_a_real_client(db):
    client_row = Client(name="יעדים")
    db.add(client_row)
    db.commit()
    actions.execute(db, Intent(action="remember", fact="מעדיף מייל", dimension=2, client_id=client_row.id))
    assert facts(db)[0].client_id == client_row.id


def test_remember_does_not_save_the_same_fact_twice(db):
    actions.execute(db, Intent(action="remember", fact="לא אחרי שבע", dimension=2))
    outcome = actions.execute(db, Intent(action="remember", fact="לא אחרי שבע", dimension=2))
    assert len(facts(db)) == 1
    assert "כבר רשום" in outcome.reply


def test_cancel_removes_the_fact_that_was_just_saved(db):
    outcome = actions.execute(db, Intent(action="remember", fact="לא בשישי", dimension=5))
    db.add(BotMessage(wa_message_id="fact-1", intent="remember", fact_id=outcome.fact_id))
    db.commit()
    assert "נמחק מהזיכרון" in actions.execute(db, Intent(action="cancel_last")).reply
    assert facts(db) == []


def test_cancel_undoes_the_newest_action_and_not_an_older_one(db):
    task = saved_by_bot(db, "להתקשר לזיצר")
    outcome = actions.execute(db, Intent(action="remember", fact="לא בשישי", dimension=5))
    db.add(BotMessage(wa_message_id="fact-2", intent="remember", fact_id=outcome.fact_id))
    db.commit()
    actions.execute(db, Intent(action="cancel_last"))
    assert facts(db) == []
    assert db.get(Task, task.id) is not None


def test_cancel_looks_past_a_message_where_nothing_was_saved(db):
    """הודעה שנכשלה לא אמורה לחסום את הביטול של מה שנשמר לפניה."""
    task = saved_by_bot(db, "להתקשר לזיצר")
    logged(db, "failed-1", "תזכיר לי", "לא הבנתי מה המשימה", intent="add_task")
    assert "בוטל: להתקשר לזיצר" in actions.execute(db, Intent(action="cancel_last")).reply
    assert db.get(Task, task.id) is None


# --- הבלוק שנשלח למודל ---


def fact(db, content: str, dimension: int = 2, **kwargs) -> MemoryFact:
    row = MemoryFact(content=content, dimension=dimension, source="dashboard", **kwargs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_block_is_empty_without_facts(db):
    assert memory.build_block(db) == ""


def test_block_holds_only_the_dimensions_the_bot_needs(db):
    fact(db, "לא עונה לטלפון אחרי שבע", dimension=2)
    fact(db, "ללקוחות נדל\"ן כותב רשמי", dimension=9)
    block = memory.build_block(db)
    assert "לא עונה לטלפון אחרי שבע" in block
    assert "רשמי" not in block


def test_block_names_the_client_the_fact_is_about(db):
    client_row = Client(name="יעדים")
    db.add(client_row)
    db.commit()
    fact(db, "מעדיף מייל", dimension=1, client_id=client_row.id)
    assert "לקוח יעדים" in memory.build_block(db)


def test_block_squeezes_a_fact_into_one_line(db):
    fact(db, "שורה\nושורה")
    assert "שורה ושורה" in memory.build_block(db)


def test_the_memory_is_sent_as_a_cached_system_block():
    blocks = _system_blocks("מה שאני יודע עליך:\n[אנשים] דני כהן")
    assert len(blocks) == 2
    assert blocks[1]["text"].startswith("מה שאני יודע עליך")
    assert all(block["cache_control"] == {"type": "ephemeral"} for block in blocks)


def test_without_memory_the_prompt_looks_exactly_as_before():
    assert len(_system_blocks("")) == 1


# --- יומן האירועים ---


def test_a_new_fact_is_written_to_the_journal(db):
    actions.execute(db, Intent(action="remember", fact="לא בשישי", dimension=5))
    assert "fact_added" in kinds(db)


def test_a_task_from_the_bot_is_written_to_the_journal(db):
    actions.execute(
        db, Intent(action="add_task", title="להתקשר לדני", domain_id=domain_id(db, "כספים"))
    )
    assert "task_created" in kinds(db)


def test_the_journal_tells_a_postponed_date_from_any_other_change(client, db):
    created = client.post("/api/tasks", json={"title": "להתקשר לדני"}).json()
    body = {"title": "להתקשר לדני", "due_date": "2026-12-01", "priority": "week", "status": "open"}
    client.put(f"/api/tasks/{created['id']}", json=body)
    client.put(f"/api/tasks/{created['id']}", json={**body, "due_date": "2026-12-10"})
    client.put(f"/api/tasks/{created['id']}", json={**body, "due_date": "2026-11-20"})
    assert kinds(db).count("task_postponed") == 1
    assert kinds(db).count("task_rescheduled") == 2


def test_the_journal_records_a_change_of_domain(client, db):
    created = client.post("/api/tasks", json={"title": "להתקשר לדני"}).json()
    client.put(
        f"/api/tasks/{created['id']}",
        json={"title": "להתקשר לדני", "domain_id": domain_id(db, "כספים"), "status": "open"},
    )
    assert "task_reclassified" in kinds(db)


def test_a_broken_journal_does_not_break_the_action(monkeypatch):
    """כלל הברזל: הזיכרון הוא העשרה ולא תלות. כשל ברישום נבלע ולא מטפס."""

    def boom():
        raise RuntimeError("בסיס הנתונים לא זמין")

    monkeypatch.setattr(memory, "SessionLocal", boom)
    memory.observe("task_created", "bot")


def test_a_broken_memory_leaves_the_block_empty():
    class Broken:
        def scalars(self, *args, **kwargs):
            raise RuntimeError("בסיס הנתונים לא זמין")

    assert memory.build_block(Broken()) == ""


# --- התחייבויות חוזרות ---


def recurrences(db) -> list[Recurrence]:
    return list(db.scalars(select(Recurrence).order_by(Recurrence.id)).all())


def test_the_bot_saves_a_recurring_commitment(db):
    outcome = actions.execute(
        db,
        Intent(
            action="add_recurring",
            title="להגיש דוח מע״מ",
            repeat_unit="month",
            repeat_count=2,
            due_date="2027-01-15",
            lead_days=7,
        ),
    )
    rec = recurrences(db)[0]
    assert rec.title == "להגיש דוח מע״מ"
    assert (rec.interval_unit, rec.interval_count) == ("month", 2)
    assert rec.start_date == date(2027, 1, 15)
    assert rec.lead_days == 7
    assert rec.from_bot is True
    assert outcome.recurrence_id == rec.id

    assert "נשמר כהתחייבות חוזרת" in outcome.reply
    assert "כל חודשיים" in outcome.reply
    assert "15/01/2027" in outcome.reply
    assert "התראה 7 ימים לפני" in outcome.reply
    # מחזור עתידי: ההתחייבות נשמרה, אבל משימה עוד לא נוצרה
    assert db.scalars(select(Task)).all() == []
    assert kinds(db) == ["recurrence_created"]


def test_a_commitment_that_starts_today_creates_its_task_at_once(db):
    today = actions.now_local().date()
    actions.execute(
        db,
        Intent(
            action="add_recurring",
            title="לעבור על הגבייה",
            repeat_unit="week",
            repeat_count=1,
            due_date=today.isoformat(),
        ),
    )
    task = db.scalars(select(Task)).one()
    assert task.title == "לעבור על הגבייה"
    assert task.due_date == today
    assert task.recurrence_id == recurrences(db)[0].id


def test_a_commitment_without_a_frequency_asks_again(db):
    outcome = actions.execute(
        db, Intent(action="add_recurring", title="משהו", due_date="2027-01-01")
    )
    assert "כל כמה זמן" in outcome.reply
    assert recurrences(db) == []


def test_a_commitment_without_a_date_asks_again(db):
    outcome = actions.execute(
        db, Intent(action="add_recurring", title="משהו", repeat_unit="month", repeat_count=1)
    )
    assert "ממתי" in outcome.reply
    assert recurrences(db) == []


def test_a_commitment_that_started_in_the_past_jumps_to_the_next_cycle(db):
    """תאריך התחלה מלפני שנה לא מייצר משימה שהתאריך שלה עבר מזמן."""
    today = actions.now_local().date()
    actions.execute(
        db,
        Intent(
            action="add_recurring",
            title="חידוש ביטוח",
            repeat_unit="year",
            repeat_count=1,
            due_date=(today - timedelta(days=400)).isoformat(),
        ),
    )
    rec = recurrences(db)[0]
    assert rec.cycle >= 1
    assert recurring.next_due(rec) >= today


def test_cancel_removes_the_commitment_and_the_task_it_created(db):
    today = actions.now_local().date()
    outcome = actions.execute(
        db,
        Intent(
            action="add_recurring",
            title="לעבור על הגבייה",
            repeat_unit="week",
            repeat_count=1,
            due_date=today.isoformat(),
        ),
    )
    db.add(
        BotMessage(
            wa_message_id="rec-1", intent="add_recurring", recurrence_id=outcome.recurrence_id
        )
    )
    db.commit()

    reply = actions.execute(db, Intent(action="cancel_last")).reply
    assert "בוטלה ההתחייבות החוזרת" in reply
    assert recurrences(db) == []
    # המשימה שנוצרה נמחקת איתה, אחרת היא נשארת בלי שיהיה ברור מאיפה היא באה
    assert db.scalars(select(Task)).all() == []


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
