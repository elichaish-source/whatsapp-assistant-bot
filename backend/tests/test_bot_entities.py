"""בדיקות לשלב 2ג2ב: הבוט יוצר ומעדכן לקוחות ופרויקטים.

מה שנבדק כאן יותר מכל השאר:

1. לקוח בשם דומה לקיים לא נוצר בלי "כן", ומה שנוצר הוא מה שנשאל עליו.
2. "בטל" אחרי יצירה מוחק רק כל עוד לא שויך דבר, ואחרי עדכון מחזיר את
   המצב הקודם. "בטל" שני לא ממשיך אחורה לפעולה שלפניה.
3. עדכון לא דורס: שדה שלא הוזכר נשאר, הערה מתווספת, ושם לא משתנה רק כי
   המודל חזר עליו כדי לזהות את הלקוח.
"""

from datetime import date
from itertools import count
from typing import get_args

import pytest
from sqlalchemy import select

from app.bot import actions, entities
from app.bot.intent import INTENT_SCHEMA, Action, Intent, IntentResult
from app.models import BotMessage, Client, ClientFamily, Domain, Project, Task
from app.routers import bot as bot_router

_ids = count(1)


def domain_id(db, name: str) -> int:
    return db.scalars(select(Domain).where(Domain.name == name)).one().id


def new_client(db, name: str, **kwargs) -> Client:
    client = Client(name=name, **kwargs)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def new_project(db, name: str, **kwargs) -> Project:
    kwargs.setdefault("domain_id", domain_id(db, "כספים"))
    project = Project(name=name, **kwargs)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def new_task(db, title: str, **kwargs) -> Task:
    task = Task(title=title, status="open", **kwargs)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def family(db, name: str = "יעדים") -> ClientFamily:
    """משפחה מהרשימה שהמיגרציה זורעת. רשימות העזר לא מתנקות בין בדיקות,
    ולכן אין ליצור כאן משפחות חדשות."""
    return db.scalars(select(ClientFamily).where(ClientFamily.name == name)).one()


@pytest.fixture
def say(db, sent, monkeypatch):
    """שולח הודעה דרך המסלול האמיתי, עם כוונה מוכנה במקום קריאה למודל."""

    def _say(intent: Intent, body: str = "הודעה") -> BotMessage:
        message_id = f"ent-{next(_ids)}"
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


def clients(db) -> list[str]:
    return sorted(item.name for item in db.scalars(select(Client)).all())


def projects(db) -> list[str]:
    return sorted(item.name for item in db.scalars(select(Project)).all())


# --- שם דומה ---


def test_name_words_ignore_order_punctuation_and_company_suffix():
    assert entities.name_words('משה כהן בע"מ') == entities.name_words("כהן, משה")
    assert entities.name_words("טיפ-טופ") == entities.name_words("טיפ טופ")
    # שם שכולו "רעש" לא הופך לריק
    assert entities.name_words('בע"מ') == frozenset({"בעמ"})


def test_similar_means_one_name_contains_the_other(db):
    new_client(db, "דני כהן")
    new_client(db, "רונית לוי", is_active=False)
    assert [item.name for item in entities.similar_clients(db, "דני")] == ["דני כהן"]
    assert [item.name for item in entities.similar_clients(db, "כהן דני מהנדסים")] == ["דני כהן"]
    # גם לקוח לא פעיל נחשב: עדיף להחזיר אותו מלפתוח כפיל
    assert [item.name for item in entities.similar_clients(db, "רונית לוי")] == ["רונית לוי"]
    # שם משפחה משותף לבדו אינו דמיון
    assert entities.similar_clients(db, "משה כהן") == []


# --- יצירת לקוח ---


def test_add_client_saves_every_detail_that_was_said(db, say):
    fam = family(db)
    row = say(
        Intent(
            action="add_client",
            name="משה  כהן",
            phone="050-1234567",
            email="moshe@example.com",
            tax_id="512345678",
            address="הרצל 1, חיפה",
            notes="הגיע דרך רונית",
            family_id=fam.id,
        )
    )
    client = db.scalars(select(Client)).one()
    assert client.name == "משה כהן"
    assert (client.phone, client.email, client.tax_id) == ("050-1234567", "moshe@example.com", "512345678")
    assert client.address == "הרצל 1, חיפה"
    assert client.notes == "הגיע דרך רונית"
    assert client.is_active is True
    assert [item.id for item in client.families] == [fam.id]
    assert "נשמר לקוח: משה כהן" in row.reply
    assert "050-1234567" in row.reply
    assert '"בטל"' in row.reply


def test_add_client_with_only_a_name(db, say):
    row = say(Intent(action="add_client", name="משה כהן"))
    client = db.scalars(select(Client)).one()
    assert (client.phone, client.email, client.tax_id, client.address, client.notes) == (None,) * 5
    assert client.families == []
    assert row.reply.startswith("נשמר לקוח: משה כהן")


def test_add_client_without_a_name_saves_nothing(db, say):
    row = say(Intent(action="add_client", phone="050-1234567"))
    assert "שם הלקוח" in row.reply
    assert clients(db) == []


def test_a_family_that_does_not_exist_is_ignored(db, say):
    say(Intent(action="add_client", name="משה כהן", family_id=9999))
    assert db.scalars(select(Client)).one().families == []


def test_a_similar_name_asks_first_and_creates_nothing(db, say):
    """⚠️ הלב של השלב: לקוח כפול לא נוצר בשקט."""
    new_client(db, "דני כהן")
    row = say(Intent(action="add_client", name="דני", phone="050-1234567"))
    assert "כבר קיים לקוח בשם דומה: דני כהן" in row.reply
    assert "ליצור בכל זאת" in row.reply
    assert row.pending_json is not None
    assert clients(db) == ["דני כהן"]


def test_yes_creates_the_client_that_was_asked_about(db, say):
    """⚠️ מה שנוצר נקרא מהשאלה. מה שהמודל מצרף ל"כן" לא משנה."""
    new_client(db, "דני כהן")
    say(Intent(action="add_client", name="דני", phone="050-1234567"))
    row = say(Intent(action="confirm", name="מישהו אחר", phone="000"))
    assert "נשמר לקוח: דני" in row.reply
    assert clients(db) == ["דני", "דני כהן"]
    created = db.scalars(select(Client).where(Client.name == "דני")).one()
    assert created.phone == "050-1234567"


def test_no_creates_nothing(db, say):
    new_client(db, "דני כהן")
    say(Intent(action="add_client", name="דני"))
    row = say(Intent(action="decline"))
    assert "לא יצרתי" in row.reply
    assert clients(db) == ["דני כהן"]


def test_a_message_in_between_cancels_the_question(db, say):
    new_client(db, "דני כהן")
    say(Intent(action="add_client", name="דני"))
    say(Intent(action="list_tasks", list_filter="open"))
    row = say(Intent(action="confirm"))
    assert "אין פעולה שמחכה לאישור" in row.reply
    assert clients(db) == ["דני כהן"]


# --- "בטל" אחרי יצירת לקוח ---


def test_cancel_deletes_a_client_that_was_just_created(db, say):
    say(Intent(action="add_client", name="משה כהן"))
    row = say(Intent(action="cancel_last"))
    assert "הלקוח משה כהן נמחק" in row.reply
    assert clients(db) == []


def test_cancel_after_a_confirmed_creation_deletes_it_too(db, say):
    new_client(db, "דני כהן")
    say(Intent(action="add_client", name="דני"))
    say(Intent(action="confirm"))
    row = say(Intent(action="cancel_last"))
    assert "הלקוח דני נמחק" in row.reply
    assert clients(db) == ["דני כהן"]


def test_cancel_keeps_a_client_that_already_has_something_attached(db, say):
    say(Intent(action="add_client", name="משה כהן"))
    client = db.scalars(select(Client)).one()
    new_task(db, "להתקשר למשה", client_id=client.id)
    row = say(Intent(action="cancel_last"))
    assert "לא אמחק" in row.reply
    assert clients(db) == ["משה כהן"]


def test_a_second_cancel_does_not_go_back_to_the_action_before(db, say):
    """⚠️ בלי הסימון "כבר בוטל", "בטל" שני היה מוחק את המשימה שנשמרה קודם."""
    say(Intent(action="add_task", title="להתקשר לרואה החשבון"))
    say(Intent(action="add_client", name="משה כהן"))
    say(Intent(action="cancel_last"))
    row = say(Intent(action="cancel_last"))
    assert "כבר בוטל" in row.reply
    assert db.scalars(select(Task)).one().title == "להתקשר לרואה החשבון"


# --- עדכון לקוח ---


def test_update_client_changes_only_what_was_said(db, say):
    client = new_client(db, "דני כהן", phone="03-1111111", email="dani@example.com", notes="ותיק")
    row = say(Intent(action="update_client", client_id=client.id, phone="050-7654321"))
    db.refresh(client)
    assert client.phone == "050-7654321"
    assert (client.name, client.email, client.notes, client.is_active) == (
        "דני כהן",
        "dani@example.com",
        "ותיק",
        True,
    )
    assert "עודכן לקוח: דני כהן" in row.reply
    assert "טלפון: 050-7654321" in row.reply


def test_cancel_puts_the_client_back(db, say):
    fam = family(db)
    client = new_client(db, "דני כהן", phone="03-1111111")
    say(
        Intent(
            action="update_client",
            client_id=client.id,
            phone="050-7654321",
            email="new@example.com",
            family_id=fam.id,
        )
    )
    row = say(Intent(action="cancel_last"))
    db.refresh(client)
    assert "בוטל השינוי: דני כהן" in row.reply
    assert (client.phone, client.email) == ("03-1111111", None)
    assert client.families == []


def test_repeating_the_name_to_identify_the_client_does_not_rename_it(db, say):
    """⚠️ "הטלפון של דני הוא..." מגיע לפעמים עם name="דני"."""
    client = new_client(db, "דני כהן")
    say(Intent(action="update_client", client_id=client.id, name="דני", phone="050-7654321"))
    db.refresh(client)
    assert client.name == "דני כהן"
    assert client.phone == "050-7654321"


def test_a_real_rename_works(db, say):
    client = new_client(db, "דני כהן")
    row = say(Intent(action="update_client", client_id=client.id, name="דני כהן אדריכלים"))
    db.refresh(client)
    assert client.name == "דני כהן אדריכלים"
    assert "שם: דני כהן אדריכלים" in row.reply


def test_a_note_is_added_and_never_replaces_the_old_one(db, say):
    client = new_client(db, "דני כהן", notes="משלם באיחור")
    row = say(Intent(action="update_client", client_id=client.id, notes="מעדיף וואטסאפ"))
    db.refresh(client)
    assert client.notes == "משלם באיחור\nמעדיף וואטסאפ"
    assert "נוספה הערה" in row.reply


def test_marking_a_client_inactive_keeps_everything_and_says_what_is_open(db, say):
    client = new_client(db, "דני כהן")
    new_task(db, "לשלוח חשבונית", client_id=client.id)
    row = say(Intent(action="update_client", client_id=client.id, active="no"))
    db.refresh(client)
    assert client.is_active is False
    assert "סומן כלא פעיל" in row.reply
    assert "1 משימות פתוחות" in row.reply
    assert db.scalars(select(Task)).one().client_id == client.id

    say(Intent(action="cancel_last"))
    db.refresh(client)
    assert client.is_active is True


def test_an_inactive_client_can_be_brought_back(db, say):
    client = new_client(db, "דני כהן", is_active=False)
    # המודל חייב לראות אותו כדי לזהות אותו
    context = actions.build_context(db)
    assert "לקוחות לא פעילים" in context
    assert f"{client.id}: דני כהן" in context

    row = say(Intent(action="update_client", client_id=client.id, active="yes"))
    db.refresh(client)
    assert client.is_active is True
    assert "סומן כפעיל" in row.reply


def test_the_model_sees_the_client_families(db):
    fam = family(db, "עסק פרטי")
    assert f"{fam.id}: עסק פרטי" in actions.build_context(db)


def test_adding_a_family_keeps_the_ones_the_client_already_has(db, say):
    first, second = family(db, "יעדים"), family(db, "עסק פרטי")
    client = new_client(db, "דני כהן")
    client.families = [first]
    db.commit()
    say(Intent(action="update_client", client_id=client.id, family_id=second.id))
    db.refresh(client)
    assert sorted(item.name for item in client.families) == ["יעדים", "עסק פרטי"]


def test_update_client_that_cannot_be_found_or_has_nothing_to_change(db, say):
    client = new_client(db, "דני כהן", phone="050-7654321")
    assert "לאיזה לקוח" in say(Intent(action="update_client", phone="050")).reply
    assert "לאיזה לקוח" in say(Intent(action="update_client", client_id=9999, phone="050")).reply
    row = say(Intent(action="update_client", client_id=client.id, phone="050-7654321"))
    assert "לא הבנתי מה לשנות" in row.reply
    assert row.undo_json is None


# --- יצירת פרויקט ---


def test_add_project_with_a_client_a_domain_and_a_date(db, say):
    client = new_client(db, "דני כהן")
    due = date(2027, 1, 31)
    row = say(
        Intent(
            action="add_project",
            name="הקמת אתר",
            client_id=client.id,
            domain_id=domain_id(db, "לקוחות"),
            due_date=due.isoformat(),
            notes="אתר תדמית בשלושה עמודים",
        )
    )
    project = db.scalars(select(Project)).one()
    assert (project.name, project.client_id, project.due_date) == ("הקמת אתר", client.id, due)
    assert project.domain_id == domain_id(db, "לקוחות")
    assert project.description == "אתר תדמית בשלושה עמודים"
    assert project.status == "active"
    assert "נשמר פרויקט: הקמת אתר" in row.reply
    # המשתמש בחר "לבחור לבד ולדווח": התחום שנבחר נאמר בתשובה
    assert "תחום לקוחות" in row.reply
    assert "לקוח דני כהן" in row.reply
    assert "31/01/2027" in row.reply


def test_add_project_without_a_domain_asks_and_creates_nothing(db, say):
    row = say(Intent(action="add_project", name="הקמת אתר"))
    assert "באיזה תחום" in row.reply
    assert "כספים" in row.reply
    assert projects(db) == []


def test_add_project_never_drops_the_client_silently(db, say):
    """⚠️ מזהה לקוח שלא קיים. פרויקט בלי הלקוח שצוין הוא טעות שקטה."""
    row = say(
        Intent(
            action="add_project", name="הקמת אתר", client_id=9999, domain_id=domain_id(db, "כספים")
        )
    )
    assert "לא מצאתי את הלקוח" in row.reply
    assert projects(db) == []


def test_a_project_with_the_same_name_asks_first(db, say):
    new_project(db, "הקמת אתר")
    intent = Intent(action="add_project", name="אתר הקמת", domain_id=domain_id(db, "כספים"))
    row = say(intent)
    assert "כבר קיים פרויקט פעיל" in row.reply
    assert projects(db) == ["הקמת אתר"]

    row = say(Intent(action="confirm"))
    assert "נשמר פרויקט: אתר הקמת" in row.reply
    assert projects(db) == ["אתר הקמת", "הקמת אתר"]


def test_cancel_deletes_a_project_that_was_just_created(db, say):
    say(Intent(action="add_project", name="הקמת אתר", domain_id=domain_id(db, "כספים")))
    row = say(Intent(action="cancel_last"))
    assert "הפרויקט הקמת אתר נמחק" in row.reply
    assert projects(db) == []


def test_cancel_keeps_a_project_that_already_has_tasks(db, say):
    say(Intent(action="add_project", name="הקמת אתר", domain_id=domain_id(db, "כספים")))
    project = db.scalars(select(Project)).one()
    new_task(db, "לבחור תבנית", project_id=project.id)
    row = say(Intent(action="cancel_last"))
    assert "לא אמחק" in row.reply
    assert projects(db) == ["הקמת אתר"]


# --- עדכון פרויקט ---


def test_closing_a_project_says_what_is_still_open_and_cancel_reopens_it(db, say):
    project = new_project(db, "הקמת אתר")
    new_task(db, "לבחור תבנית", project_id=project.id)
    row = say(Intent(action="update_project", project_id=project.id, active="no"))
    db.refresh(project)
    assert project.status == "done"
    assert "נסגר" in row.reply
    assert "1 משימות פתוחות" in row.reply

    row = say(Intent(action="cancel_last"))
    db.refresh(project)
    assert project.status == "active"
    assert "בוטל השינוי: הקמת אתר" in row.reply


def test_update_project_changes_only_what_was_said(db, say):
    project = new_project(db, "הקמת אתר", description="אתר תדמית", due_date=date(2026, 12, 1))
    row = say(
        Intent(
            action="update_project",
            project_id=project.id,
            due_date="2027-01-31",
            notes="נוסף עמוד בלוג",
            domain_id=domain_id(db, "לקוחות"),
        )
    )
    db.refresh(project)
    assert project.due_date == date(2027, 1, 31)
    assert project.description == "אתר תדמית\nנוסף עמוד בלוג"
    assert project.domain_id == domain_id(db, "לקוחות")
    assert (project.name, project.status) == ("הקמת אתר", "active")
    assert "31/01/2027" in row.reply
    assert "תחום: לקוחות" in row.reply

    say(Intent(action="cancel_last"))
    db.refresh(project)
    assert project.due_date == date(2026, 12, 1)
    assert project.description == "אתר תדמית"
    assert project.domain_id == domain_id(db, "כספים")


def test_moving_a_project_moves_its_tasks_and_cancel_moves_them_back(db, say):
    """כלל של הדשבורד: משימות בפרויקט של לקוח שייכות לאותו לקוח."""
    old, new = new_client(db, "דני כהן"), new_client(db, "רונית לוי")
    project = new_project(db, "הקמת אתר", client_id=old.id)
    with_client = new_task(db, "לבחור תבנית", project_id=project.id, client_id=old.id)
    without = new_task(db, "לכתוב תוכן", project_id=project.id)

    row = say(Intent(action="update_project", project_id=project.id, client_id=new.id))
    for item in (project, with_client, without):
        db.refresh(item)
    assert project.client_id == new.id
    assert (with_client.client_id, without.client_id) == (new.id, new.id)
    assert "לקוח: רונית לוי" in row.reply
    assert "2 משימות" in row.reply

    say(Intent(action="cancel_last"))
    for item in (project, with_client, without):
        db.refresh(item)
    assert project.client_id == old.id
    assert (with_client.client_id, without.client_id) == (old.id, None)


def test_update_project_that_cannot_be_found_or_has_nothing_to_change(db, say):
    project = new_project(db, "הקמת אתר")
    assert "לאיזה פרויקט" in say(Intent(action="update_project", active="no")).reply
    row = say(Intent(action="update_project", project_id=project.id, name="אתר"))
    assert "לא הבנתי מה לשנות" in row.reply
    db.refresh(project)
    assert project.name == "הקמת אתר"


# --- מה שלא השתנה ---


def test_a_task_update_is_still_undone_the_old_way(db, say):
    """עדכון משימה שומר undo_json בלי kind, והמסלול שלו לא נפגע."""
    task = new_task(db, "לחדש את הביטוח", priority="week")
    say(Intent(action="update_task", task_text="ביטוח", priority="today"))
    row = say(Intent(action="cancel_last"))
    db.refresh(task)
    assert "בוטל השינוי: לחדש את הביטוח" in row.reply
    assert task.priority == "week"


def test_a_confirmed_delete_leaves_nothing_to_cancel(db, say):
    """מחיקה שאושרה לא ניתנת לביטול, ו"בטל" אחריה לא נופל על שורת האישור."""
    task_id = new_task(db, "לחדש את הביטוח").id
    say(Intent(action="delete_task", task_text="ביטוח"))
    say(Intent(action="confirm"))
    row = say(Intent(action="cancel_last"))
    assert "אין מה לבטל" in row.reply
    assert db.get(Task, task_id) is None


# --- הסכימה ---


def test_the_new_fields_are_plain_and_never_null():
    """⚠️ מגבלת 16 שדות האיחוד. שדה חדש עם null היה מפיל את הבוט על כל הודעה."""
    properties = INTENT_SCHEMA["properties"]
    for field in ("name", "phone", "email", "tax_id", "address"):
        assert properties[field] == {"type": "string"}
    assert properties["family_id"] == {"type": "integer"}
    assert properties["active"] == {"type": "string", "enum": ["", "yes", "no"]}
    assert set(INTENT_SCHEMA["required"]) == set(properties)

    blank = Intent(action="add_task", title="משהו")
    assert (blank.name, blank.phone, blank.email, blank.tax_id, blank.address) == ("",) * 5
    assert (blank.family_id, blank.active) == (0, "")


def test_every_action_is_in_the_schema_and_is_handled(db):
    listed = INTENT_SCHEMA["properties"]["action"]["enum"]
    assert sorted(listed) == sorted(get_args(Action))
    for action in ("add_client", "update_client", "add_project", "update_project"):
        assert action in listed
        # ריק מכל פרט: כל פעולה חייבת לענות משהו מובן ולא להתרסק
        assert actions.execute(db, Intent(action=action)).reply
