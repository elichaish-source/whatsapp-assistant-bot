"""בדיקות לשלב 2ג2ג: תחומים, סוגי משימה, והשהיה של התחייבות חוזרת דרך הבוט.

‏⚠️ רשימות העזר (תחומים, סוגי משימה) לא מתנקות בין בדיקות, כי המיגרציה
זורעת אותן. לכן כל מה שבדיקה כאן יוצרת נמחק בסופה, אחרת test_seeded_lists
וכל בדיקה שמונה תחומים היו נשברים.
"""

from datetime import date, timedelta
from itertools import count

import pytest
from sqlalchemy import select, text

from app import recurring
from app.bot import actions, lists, pipeline
from app.bot.intent import INTENT_SCHEMA, Intent, IntentResult
from app.db import engine
from app.models import BotMessage, Domain, Recurrence, Task, TaskType
from app.routers import bot as bot_router

_ids = count(1)


@pytest.fixture(autouse=True)
def drop_new_lookups(db):
    """מוחק בסוף כל בדיקה את התחומים וסוגי המשימה שהיא יצרה."""
    domains = set(db.scalars(select(Domain.id)).all())
    types = set(db.scalars(select(TaskType.id)).all())
    yield
    # ‏⚠️ הסשן של הבדיקה מחזיק נעילת קריאה על הטבלאות, ו-TRUNCATE היה מחכה
    # לו לנצח
    db.rollback()
    db.close()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE tasks, recurrences, projects RESTART IDENTITY CASCADE"))
        if domains:
            conn.execute(
                Domain.__table__.delete().where(Domain.id.not_in(domains))
            )
        if types:
            conn.execute(
                TaskType.__table__.delete().where(TaskType.id.not_in(types))
            )


@pytest.fixture
def say(db, sent, monkeypatch):
    """שולח הודעה דרך המסלול האמיתי, עם כוונה מוכנה במקום קריאה למודל."""

    def _say(intent: Intent, body: str = "הודעה") -> BotMessage:
        message_id = f"lst-{next(_ids)}"
        db.add(BotMessage(wa_message_id=message_id, body=body))
        db.commit()
        monkeypatch.setattr(
            pipeline, "extract", lambda *args, **kwargs: IntentResult(intent=intent)
        )
        bot_router.handle_message(message_id, body)
        db.expire_all()
        return db.scalars(
            select(BotMessage).where(BotMessage.wa_message_id == message_id)
        ).one()

    return _say


def domain_names(db) -> list[str]:
    return [item.name for item in db.scalars(select(Domain).order_by(Domain.sort_order)).all()]


def type_names(db) -> list[str]:
    return [item.name for item in db.scalars(select(TaskType).order_by(TaskType.sort_order)).all()]


def recurrence(db, title: str = "דוח מע״מ", **kwargs) -> Recurrence:
    data = {
        "title": title,
        "interval_unit": "month",
        "interval_count": 1,
        "start_date": recurring.today_local() + timedelta(days=10),
        "cycle": 0,
        "lead_days": 0,
        "priority": "week",
        "active": True,
        "from_bot": False,
    }
    data.update(kwargs)
    rec = Recurrence(**data)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


# --- תחומים ---


def test_add_domain_goes_to_the_end_of_the_list(db, say):
    before = domain_names(db)
    row = say(Intent(action="add_domain", name="הפקות"))
    assert domain_names(db) == before + ["הפקות"]
    created = db.scalars(select(Domain).where(Domain.name == "הפקות")).one()
    assert created.requires_client is False
    assert "נשמר תחום: הפקות" in row.reply
    assert "מחייב לקוח" not in row.reply
    assert '"בטל"' in row.reply


def test_requires_client_only_when_it_was_said(db, say):
    row = say(Intent(action="add_domain", name="הפקות", requires_client=True))
    created = db.scalars(select(Domain).where(Domain.name == "הפקות")).one()
    assert created.requires_client is True
    assert "תחייב לקוח" in row.reply


def test_the_new_domain_reaches_the_model(db, say):
    say(Intent(action="add_domain", name="הפקות"))
    assert "הפקות" in actions.build_context(db)


def test_an_existing_domain_is_not_created_again(db, say):
    before = domain_names(db)
    row = say(Intent(action="add_domain", name="כספים"))
    assert "כבר קיים תחום בשם כספים" in row.reply
    assert domain_names(db) == before


def test_a_similar_domain_asks_first(db, say):
    """"שיווק" מול "שיווק ומכירות" הוא כמעט תמיד אותו תחום."""
    before = domain_names(db)
    row = say(Intent(action="add_domain", name="שיווק"))
    assert "כבר קיים תחום בשם דומה: שיווק ומכירות" in row.reply
    assert domain_names(db) == before

    row = say(Intent(action="confirm", name="משהו אחר"))
    assert "נשמר תחום: שיווק" in row.reply
    assert domain_names(db) == before + ["שיווק"]


def test_no_to_a_similar_domain_creates_nothing(db, say):
    before = domain_names(db)
    say(Intent(action="add_domain", name="שיווק"))
    row = say(Intent(action="decline"))
    assert "לא יצרתי" in row.reply
    assert domain_names(db) == before


def test_cancel_deletes_a_domain_that_was_just_created(db, say):
    before = domain_names(db)
    say(Intent(action="add_domain", name="הפקות"))
    row = say(Intent(action="cancel_last"))
    assert "התחום הפקות נמחק" in row.reply
    assert domain_names(db) == before


def test_cancel_keeps_a_domain_that_is_already_in_use(db, say):
    say(Intent(action="add_domain", name="הפקות"))
    created = db.scalars(select(Domain).where(Domain.name == "הפקות")).one()
    db.add(Task(title="לתאם צילום", status="open", domain_id=created.id))
    db.commit()
    row = say(Intent(action="cancel_last"))
    assert "לא אמחק" in row.reply
    assert "הפקות" in domain_names(db)


def test_add_domain_without_a_name(db, say):
    before = domain_names(db)
    row = say(Intent(action="add_domain"))
    assert "שם התחום" in row.reply
    assert domain_names(db) == before


# --- סוגי משימה ---


def test_add_task_type_and_cancel_it(db, say):
    before = type_names(db)
    row = say(Intent(action="add_task_type", name="נסיעה"))
    assert type_names(db) == before + ["נסיעה"]
    assert "נשמר סוג משימה: נסיעה" in row.reply

    row = say(Intent(action="cancel_last"))
    assert "סוג המשימה נסיעה נמחק" in row.reply
    assert type_names(db) == before


def test_an_existing_task_type_is_not_created_again(db, say):
    existing = type_names(db)[0]
    row = say(Intent(action="add_task_type", name=existing))
    assert "כבר קיים סוג משימה" in row.reply
    assert type_names(db).count(existing) == 1


def test_cancel_keeps_a_task_type_that_is_already_in_use(db, say):
    say(Intent(action="add_task_type", name="נסיעה"))
    created = db.scalars(select(TaskType).where(TaskType.name == "נסיעה")).one()
    recurrence(db, task_type_id=created.id)
    row = say(Intent(action="cancel_last"))
    assert "לא אמחק" in row.reply
    assert "נסיעה" in type_names(db)


def test_a_second_cancel_does_not_go_back_to_the_action_before(db, say):
    say(Intent(action="add_task", title="להתקשר לרואה החשבון"))
    say(Intent(action="add_task_type", name="נסיעה"))
    say(Intent(action="cancel_last"))
    row = say(Intent(action="cancel_last"))
    assert "כבר בוטל" in row.reply
    assert db.scalars(select(Task)).one().title == "להתקשר לרואה החשבון"


# --- השהיית התחייבות חוזרת ---


def test_pause_stops_new_cycles(db, say):
    rec = recurrence(db, start_date=recurring.today_local())
    row = say(Intent(action="pause_recurrence", task_text="מע״מ"))
    db.refresh(rec)
    assert rec.active is False
    assert "הושהתה: דוח מע״מ (כל חודש)" in row.reply
    # הלולאה לא מייצרת משימה להתחייבות מושהית, גם כשהגיע זמנה
    recurring.materialize(db, actions.now_local())
    assert db.scalars(select(Task)).all() == []


def test_pause_keeps_the_task_of_the_current_cycle(db, say):
    rec = recurrence(db, start_date=recurring.today_local())
    recurring.materialize(db, actions.now_local())
    row = say(Intent(action="pause_recurrence", task_text="מע״מ"))
    assert "המשימה של המחזור הנוכחי כבר נוצרה" in row.reply
    task = db.scalars(select(Task)).one()
    assert (task.recurrence_id, task.status) == (rec.id, "open")


def test_resume_skips_the_cycles_that_passed_while_paused(db, say):
    """⚠️ הוכרע על ידי המשתמש: בלי משימות על מחזורים שהוחמצו."""
    today = recurring.today_local()
    rec = recurrence(db, start_date=today - timedelta(days=200), active=False)
    row = say(Intent(action="resume_recurrence", task_text="מע״מ"))
    db.refresh(rec)
    assert rec.active is True
    assert recurring.next_due(rec) >= today
    assert f"המחזור הבא: {recurring.next_due(rec):%d/%m/%Y}" in row.reply
    recurring.materialize(db, actions.now_local())
    for task in db.scalars(select(Task)).all():
        assert task.due_date >= today


def test_cancel_after_resume_puts_back_the_pause_and_the_count(db, say):
    today = recurring.today_local()
    rec = recurrence(db, start_date=today - timedelta(days=200), active=False, cycle=2)
    say(Intent(action="resume_recurrence", task_text="מע״מ"))
    row = say(Intent(action="cancel_last"))
    db.refresh(rec)
    assert "שוב מושהית" in row.reply
    assert (rec.active, rec.cycle) == (False, 2)


def test_cancel_after_pause_brings_it_back(db, say):
    rec = recurrence(db)
    say(Intent(action="pause_recurrence", task_text="מע״מ"))
    row = say(Intent(action="cancel_last"))
    db.refresh(rec)
    assert rec.active is True
    assert "שוב פעילה" in row.reply


def test_several_matches_ask_and_change_nothing(db, say):
    """⚠️ לא בוחר לבד מבין כמה התחייבויות."""
    first = recurrence(db, "דוח מע״מ חודשי")
    second = recurrence(db, "דוח מע״מ לחברה")
    row = say(Intent(action="pause_recurrence", task_text="מע״מ"))
    assert "לאיזו התכוונת" in row.reply
    assert "דוח מע״מ חודשי" in row.reply and "דוח מע״מ לחברה" in row.reply
    for rec in (first, second):
        db.refresh(rec)
        assert rec.active is True
    assert row.undo_json is None


def test_pausing_what_is_already_paused_says_so(db, say):
    recurrence(db, active=False)
    row = say(Intent(action="pause_recurrence", task_text="מע״מ"))
    assert "כבר מושהית" in row.reply
    row = say(Intent(action="resume_recurrence", task_text="ביטוח"))
    assert "לא מצאתי התחייבות" in row.reply


def test_search_uses_the_word_without_its_prefix(db, say):
    rec = recurrence(db, "חידוש ביטוח רכב", interval_unit="year")
    say(Intent(action="pause_recurrence", task_text="הביטוח"))
    db.refresh(rec)
    assert rec.active is False


def test_pause_without_saying_which(db, say):
    row = say(Intent(action="pause_recurrence"))
    assert "לאיזו התחייבות" in row.reply


# --- הדשבורד ---


def test_dashboard_resume_skips_missed_cycles_too(client, db):
    """אותו כלל בדשבורד: עד עכשיו הפעלה מחדש ייצרה משימה על מחזור ישן."""
    today = recurring.today_local()
    start = today - timedelta(days=200)
    body = {
        "title": "דוח מע״מ",
        "interval_unit": "month",
        "interval_count": 1,
        "start_date": start.isoformat(),
        "active": False,
    }
    created = client.post("/api/recurrences", json=body).json()
    rec = db.get(Recurrence, created["id"])
    rec.cycle = 0
    db.commit()

    row = client.put(f"/api/recurrences/{created['id']}", json={**body, "active": True}).json()
    assert date.fromisoformat(row["next_due"]) >= today


# --- הסכימה ---


def test_requires_client_is_a_plain_boolean():
    """⚠️ מגבלת 16 שדות האיחוד."""
    assert INTENT_SCHEMA["properties"]["requires_client"] == {"type": "boolean"}
    assert "requires_client" in INTENT_SCHEMA["required"]
    assert Intent(action="add_task", title="משהו").requires_client is False


def test_every_new_action_answers_something(db):
    for action in ("add_domain", "add_task_type", "pause_recurrence", "resume_recurrence"):
        assert action in INTENT_SCHEMA["properties"]["action"]["enum"]
        assert actions.execute(db, Intent(action=action)).reply
    assert set(lists.CONFIRMABLE) == {"add_domain", "add_task_type"}


# --- מרכאות ---


def test_a_typed_quote_finds_a_stored_gershayim(db, say):
    """⚠️ נמצא בבדיקה מול המודל: הוא כותב "המע"מ" במרכאות רגילות, והכותרת
    שמורה עם ״. בלי ההשוואה הזאת שום התחייבות של מע״מ לא הייתה נמצאת."""
    rec = recurrence(db, "דוח מע״מ")
    say(Intent(action="pause_recurrence", task_text='דוח המע"מ'))
    db.refresh(rec)
    assert rec.active is False


def test_the_same_holds_for_tasks(db, say):
    task = Task(title="להגיש דוח מע״מ", status="open")
    db.add(task)
    db.commit()
    say(Intent(action="update_task", task_text='מע"מ', priority="today"))
    db.refresh(task)
    assert task.priority == "today"
