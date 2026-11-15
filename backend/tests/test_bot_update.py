"""בדיקות לשלב 2ג2א: הבוט משנה ומוחק משימות קיימות.

שלושה דברים נבדקים כאן יותר מכל השאר, כי הם המקומות שבהם טעות שקטה
פוגעת בנתונים:

1. הבוט לא בוחר לבד מבין כמה משימות שמתאימות.
2. "כן" מוחק רק את מה שנשאל עליו בהודעה שמיד לפני, ולא את מה שהמודל אומר.
3. "בטל" מחזיר שינוי, ואף פעם לא מוחק משימה שלא הבוט יצר.

רוב הבדיקות עוברות דרך handle_message עצמו ולא רק דרך execute, כי המצב
הקודם והפעולה הממתינה נשמרים שם — והחיבור הזה הוא בדיוק מה שנבדק.
"""

from datetime import datetime, timedelta, timezone
from itertools import count

import pytest
from sqlalchemy import select

from app import timeframe
from app.bot import actions
from app.bot.intent import INTENT_SCHEMA, SYSTEM_PROMPT, Intent, IntentResult
from app.models import BotMessage, Client, Domain, Observation, Project, Task
from app.routers import bot as bot_router

_ids = count(1)


def domain_id(db, name: str) -> int:
    return db.scalars(select(Domain).where(Domain.name == name)).one().id


def new_task(db, title: str, **kwargs) -> Task:
    task = Task(title=title, domain_id=domain_id(db, "כספים"), status="open", **kwargs)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@pytest.fixture
def say(db, sent, monkeypatch):
    """שולח הודעה דרך המסלול האמיתי, עם כוונה מוכנה במקום קריאה למודל."""

    def _say(intent: Intent, body: str = "הודעה") -> BotMessage:
        message_id = f"upd-{next(_ids)}"
        db.add(BotMessage(wa_message_id=message_id, body=body))
        db.commit()
        monkeypatch.setattr(
            bot_router, "extract", lambda *args, **kwargs: IntentResult(intent=intent)
        )
        bot_router.handle_message(message_id, body)
        db.expire_all()
        return db.scalars(
            select(BotMessage).where(BotMessage.wa_message_id == message_id)
        ).one()

    return _say


def today():
    return timeframe.local_today()


def next_week() -> str:
    return (today() + timedelta(days=7)).isoformat()


def kinds(db) -> list[str]:
    return [row.kind for row in db.scalars(select(Observation).order_by(Observation.id)).all()]


# --- איתור המשימה ---


def test_update_finds_a_dashboard_task_by_a_word_from_its_title(db, say):
    """בניגוד ל-update_last: גם משימה מהדשבורד, וגם בלי שהבוט יצר אותה."""
    task = new_task(db, "לחדש את הביטוח", due_date=today())
    row = say(Intent(action="update_task", task_text="ביטוח", due_date=next_week()))
    db.refresh(task)
    assert task.due_date == today() + timedelta(days=7)
    assert "עודכן: לחדש את הביטוח" in row.reply
    assert row.task_id == task.id


def test_the_search_drops_the_prefix_letter_of_a_hebrew_word(db, say):
    """המשתמש אומר "הביטוח", והכותרת היא "ביטוח רכב"."""
    task = new_task(db, "לחדש ביטוח רכב")
    say(Intent(action="update_task", task_text="הביטוח", priority="today"))
    db.refresh(task)
    assert task.priority == "today"


def test_the_search_matches_word_by_word_and_not_as_one_phrase(db, say):
    """⚠️ מהודעה אמיתית: המשתמש לא מצטט את הכותרת כלשונה."""
    task = new_task(db, "לטפל בדוח של טיפ טופ")
    new_task(db, "דוח מע״מ")
    say(Intent(action="update_task", task_text="הדוח של טיפ טופ", priority="today"))
    db.refresh(task)
    assert task.priority == "today"


def test_a_percent_sign_is_a_character_and_not_a_wildcard(db):
    new_task(db, "משימה אחת")
    new_task(db, "משימה שתיים")
    assert actions._find_open(db, "%") == []
    assert actions._find_open(db, "_") == []


def test_update_asks_when_several_tasks_match(db, say):
    """⚠️ הלב של השלב: שינוי שקט במשימה הלא נכונה הוא מה שלא שמים לב אליו."""
    first = new_task(db, "להתקשר לדני")
    second = new_task(db, "להתקשר לדנה")
    row = say(Intent(action="update_task", task_text="להתקשר", priority="today"))
    assert "לאיזו התכוונת" in row.reply
    assert sorted(int(part) for part in row.listed_task_ids.split(",")) == [first.id, second.id]
    assert row.undo_json is None
    for task in (first, second):
        db.refresh(task)
        assert task.priority == "week"


def test_update_says_so_when_nothing_matches(db, say):
    new_task(db, "להתקשר לדני")
    row = say(Intent(action="update_task", task_text="ביטוח", priority="today"))
    assert "לא מצאתי" in row.reply


def test_update_by_number_from_the_last_list(db, say):
    first = new_task(db, "ראשונה")
    second = new_task(db, "שנייה")
    say(Intent(action="list_tasks", list_filter="open"))
    say(Intent(action="update_task", task_number=2, priority="today"))
    db.refresh(first)
    db.refresh(second)
    assert first.priority == "week"
    assert second.priority == "today"


def test_update_refuses_a_number_that_points_at_a_closed_task(db, say):
    task = new_task(db, "כבר נעשה")
    say(Intent(action="list_tasks", list_filter="open"))
    task.status = "done"
    db.commit()
    row = say(Intent(action="update_task", task_number=1, priority="today"))
    assert "כבר סגורה" in row.reply


def test_update_without_any_way_to_find_the_task(db, say):
    new_task(db, "משהו")
    row = say(Intent(action="update_task", priority="today"))
    assert "לאיזו משימה" in row.reply


def test_completing_a_task_uses_the_same_search(db, say):
    task = new_task(db, "לחדש ביטוח רכב")
    say(Intent(action="complete_task", task_text="הביטוח"))
    db.refresh(task)
    assert task.status == "done"


# --- מה משתנה ---


def test_update_with_nothing_to_change_changes_nothing(db, say):
    task = new_task(db, "לחדש את הביטוח")
    row = say(Intent(action="update_task", task_text="ביטוח"))
    assert "לא הבנתי מה לשנות" in row.reply
    assert row.undo_json is None
    assert row.task_id is None
    db.refresh(task)
    assert task.priority == "week"


def test_postponing_takes_the_task_off_todays_list(db, say):
    """⚠️ "להיום" כולל כל מה שמתויג היום. בלי זה "תדחה" לא היה דוחה כלום."""
    task = new_task(db, "לחדש את הביטוח", priority="today", due_date=today())
    say(Intent(action="update_task", task_text="ביטוח", due_date=next_week()))
    db.refresh(task)
    assert task.priority == "week"
    listed = actions.execute(db, Intent(action="list_tasks", list_filter="today"))
    assert "ביטוח" not in listed.reply


def test_an_explicit_timeframe_wins_over_the_postponing_rule(db, say):
    task = new_task(db, "לחדש את הביטוח", priority="today")
    say(
        Intent(
            action="update_task", task_text="ביטוח", due_date=next_week(), priority="today"
        )
    )
    db.refresh(task)
    assert task.priority == "today"


def test_a_date_that_is_not_in_the_future_keeps_the_timeframe(db, say):
    task = new_task(db, "לחדש את הביטוח", priority="today")
    say(Intent(action="update_task", task_text="ביטוח", due_date=today().isoformat()))
    db.refresh(task)
    assert task.priority == "today"


def test_update_obeys_the_dashboard_rules(db, say):
    """תחום שמחייב לקוח לא נשמר בלי לקוח — גם לא דרך עדכון."""
    task = new_task(db, "לשלוח חוזה")
    row = say(
        Intent(action="update_task", task_text="חוזה", domain_id=domain_id(db, "לקוחות"))
    )
    assert "לא עדכנתי" in row.reply
    db.refresh(task)
    assert task.domain_id == domain_id(db, "כספים")


def test_update_ignores_a_client_that_does_not_exist(db, say):
    task = new_task(db, "לשלוח חוזה")
    row = say(Intent(action="update_task", task_text="חוזה", client_id=9999))
    assert "לא עדכנתי" in row.reply
    db.refresh(task)
    assert task.client_id is None


def test_moving_a_task_to_a_clients_project_moves_it_to_that_client(db, say):
    client = Client(name="זיצר")
    db.add(client)
    db.commit()
    project = Project(name="אתר חדש", domain_id=domain_id(db, "כספים"), client_id=client.id)
    db.add(project)
    db.commit()
    task = new_task(db, "לשלוח חוזה")

    say(Intent(action="update_task", task_text="חוזה", project_id=project.id))
    db.refresh(task)
    assert task.project_id == project.id
    assert task.client_id == client.id


def test_a_new_reminder_goes_out_even_if_the_old_one_was_sent(db, say):
    stamp = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
    task = new_task(db, "להתקשר לזיצר", reminder_at=stamp, reminder_sent_at=stamp)
    say(Intent(action="update_task", task_text="זיצר", reminder_at="2026-12-01T10:00"))
    db.refresh(task)
    assert task.reminder_sent_at is None
    assert task.reminder_at != stamp


def test_an_update_is_written_to_the_journal_with_what_changed(db, say):
    new_task(db, "לחדש את הביטוח")
    say(Intent(action="update_task", task_text="ביטוח", priority="today"))
    row = db.scalars(select(Observation).where(Observation.kind == "task_updated")).one()
    assert row.source == "bot"
    assert "priority: week → today" in row.detail


# --- "בטל" מחזיר שינוי ---


def test_cancel_puts_the_task_back_the_way_it_was(db, say):
    task = new_task(db, "לחדש את הביטוח", priority="today", due_date=today())
    say(Intent(action="update_task", task_text="ביטוח", due_date=next_week()))
    row = say(Intent(action="cancel_last"))
    db.refresh(task)
    assert "בוטל השינוי" in row.reply
    assert task.due_date == today()
    assert task.priority == "today"


def test_cancel_never_deletes_a_task_it_only_changed(db, say):
    """⚠️ משימה מהדשבורד שהבוט רק שינה. "בטל" מחזיר, ולא מוחק."""
    task = new_task(db, "לחדש את הביטוח")
    say(Intent(action="update_task", task_text="ביטוח", priority="today"))
    say(Intent(action="cancel_last"))
    assert db.get(Task, task.id) is not None


def test_a_second_cancel_does_not_delete_the_task(db, say):
    """⚠️ משימה שהבוט יצר ואחר כך שינה. אחרי שהשינוי בוטל, "בטל" נוסף היה
    נופל למסלול המחיקה של משימות מהבוט, ומוחק אותה."""
    task = new_task(db, "לחדש את הביטוח", source="whatsapp")
    say(Intent(action="update_task", task_text="ביטוח", priority="today"))
    say(Intent(action="cancel_last"))
    row = say(Intent(action="cancel_last"))
    assert "כבר בוטל" in row.reply
    db.expire_all()
    assert db.get(Task, task.id) is not None
    assert db.get(Task, task.id).priority == "week"


def test_cancel_restores_the_reminder_and_that_it_was_sent(db, say):
    stamp = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
    task = new_task(db, "להתקשר לזיצר", reminder_at=stamp, reminder_sent_at=stamp)
    say(Intent(action="update_task", task_text="זיצר", reminder_at="2026-12-01T10:00"))
    say(Intent(action="cancel_last"))
    db.refresh(task)
    assert task.reminder_at == stamp
    # בלי זה התזכורת הישנה, שכבר נשלחה, הייתה יוצאת שוב
    assert task.reminder_sent_at == stamp


# --- מחיקה באישור ---


def test_delete_only_asks(db, say):
    task = new_task(db, "לחדש את הביטוח")
    row = say(Intent(action="delete_task", task_text="ביטוח"))
    assert "למחוק את המשימה: לחדש את הביטוח" in row.reply
    assert row.pending_json is not None
    assert db.get(Task, task.id) is not None


def test_yes_right_after_the_question_deletes(db, say):
    # המזהה נשמר מראש: אחרי המחיקה אי אפשר לקרוא אותו מהאובייקט
    task_id = new_task(db, "לחדש את הביטוח").id
    say(Intent(action="delete_task", task_text="ביטוח"))
    row = say(Intent(action="confirm"))
    assert "נמחק: לחדש את הביטוח" in row.reply
    assert db.get(Task, task_id) is None
    assert "task_deleted" in kinds(db)


def test_yes_with_nothing_asked_does_nothing(db, say):
    task = new_task(db, "לחדש את הביטוח")
    row = say(Intent(action="confirm"))
    assert "אין פעולה שמחכה" in row.reply
    assert db.get(Task, task.id) is not None


def test_any_message_in_between_cancels_the_question(db, say):
    """⚠️ "כן" שנאמר אחר כך, על משהו אחר, לא מוחק כלום."""
    task = new_task(db, "לחדש את הביטוח")
    say(Intent(action="delete_task", task_text="ביטוח"))
    say(Intent(action="list_tasks", list_filter="open"))
    row = say(Intent(action="confirm"))
    assert "אין פעולה שמחכה" in row.reply
    assert db.get(Task, task.id) is not None


def test_yes_that_comes_too_late_does_nothing(db, say):
    task = new_task(db, "לחדש את הביטוח")
    asked = say(Intent(action="delete_task", task_text="ביטוח"))
    asked.created_at = datetime.now(timezone.utc) - actions.CONFIRM_WINDOW - timedelta(minutes=1)
    db.commit()
    row = say(Intent(action="confirm"))
    assert "עבר יותר מדי זמן" in row.reply
    assert db.get(Task, task.id) is not None


def test_no_leaves_the_task_and_closes_the_question(db, say):
    task = new_task(db, "לחדש את הביטוח")
    say(Intent(action="delete_task", task_text="ביטוח"))
    assert "לא נגעתי" in say(Intent(action="decline")).reply
    # ו"כן" אחרי ה"לא" כבר לא מתייחס לשאלה ההיא
    say(Intent(action="confirm"))
    assert db.get(Task, task.id) is not None


def test_a_second_yes_deletes_nothing_more(db, say):
    new_task(db, "לחדש את הביטוח")
    other = new_task(db, "ביטוח דירה — לברר")
    say(Intent(action="delete_task", task_text="לחדש"))
    say(Intent(action="confirm"))
    row = say(Intent(action="confirm"))
    assert "אין פעולה שמחכה" in row.reply
    assert db.get(Task, other.id) is not None


def test_the_model_cannot_choose_what_gets_deleted(db, say):
    """⚠️ האישור נאכף בשרת. גם אם המודל מצרף ל"כן" משימה אחרת, נמחקת רק
    זאת שנשאל עליה."""
    asked_id = new_task(db, "לחדש את הביטוח").id
    other_id = new_task(db, "להתקשר לדני").id
    say(Intent(action="list_tasks", list_filter="open"))
    say(Intent(action="delete_task", task_text="ביטוח"))
    say(Intent(action="confirm", task_text="דני", task_number=2))
    assert db.get(Task, asked_id) is None
    assert db.get(Task, other_id) is not None


def test_delete_asks_which_one_when_several_match(db, say):
    new_task(db, "להתקשר לדני")
    new_task(db, "להתקשר לדנה")
    row = say(Intent(action="delete_task", task_text="להתקשר"))
    assert "לאיזו התכוונת" in row.reply
    assert row.pending_json is None
    # ולכן "כן" אחרי שאלת ההבהרה לא מוחק אף אחת
    say(Intent(action="confirm"))
    assert len(db.scalars(select(Task)).all()) == 2


def test_yes_about_a_task_that_is_already_gone(db, say):
    task = new_task(db, "לחדש את הביטוח")
    say(Intent(action="delete_task", task_text="ביטוח"))
    db.delete(db.get(Task, task.id))
    db.commit()
    assert "כבר לא קיימת" in say(Intent(action="confirm")).reply


# --- "להיום", הגדרה אחת ---


def test_todays_list_holds_what_is_tagged_today_and_what_is_due(db):
    """⚠️ עד 15.11.2026 הרשימה הסתכלה רק על התאריך, ומשימה שתויגה "היום"
    בלי תאריך לא הופיעה בה בכלל."""
    new_task(db, "מתויגת היום", priority="today")
    new_task(db, "התאריך שלה היום", due_date=today())
    new_task(db, "באיחור ולא מתויגת", due_date=today() - timedelta(days=3))
    new_task(db, "לשבוע הבא", due_date=today() + timedelta(days=7))
    new_task(db, "בלי תאריך ובלי תיוג")

    reply = actions.execute(db, Intent(action="list_tasks", list_filter="today")).reply
    assert "להיום (3)" in reply
    for title in ("מתויגת היום", "התאריך שלה היום", "באיחור ולא מתויגת"):
        assert title in reply
    assert "לשבוע הבא" not in reply
    assert "בלי תאריך ובלי תיוג" not in reply


def test_the_model_is_told_the_same_definition_of_today():
    """השאילתה החופשית והרשימה המובנית חייבות לענות אותו דבר על "להיום"."""
    assert "priority = 'today'" in SYSTEM_PROMPT
    assert "due_date <= התאריך של היום" in SYSTEM_PROMPT


# --- הסכימה ---


def test_the_new_actions_reached_the_schema():
    actions_in_schema = INTENT_SCHEMA["properties"]["action"]["enum"]
    for name in ("update_task", "delete_task", "confirm", "decline"):
        assert name in actions_in_schema
        Intent(action=name)
