"""בדיקות לשליפה החופשית: מה נחסם, מה רץ, ואיך התוצאה נראית.

שלוש החומות נבדקות בנפרד. בדיקת הטקסט היא היחידה שאפשר לבדוק בלי מסד,
ולכן יש לה הכי הרבה מקרים — אבל היא גם השכבה החלשה מבין השלוש, וזאת
הסיבה שיש כאן גם בדיקה שהמסד עצמו מסרב לכתוב.
"""

import re
from datetime import date, datetime
from typing import get_args

import pytest
from sqlalchemy import select

from app import queries, schemas
from app.bot import actions
from app.bot.intent import Intent
from app.models import Client, Task


def task(db, title: str = "להתקשר לדני", **kwargs) -> Task:
    row = Task(title=title, status="open", **kwargs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- בדיקת הטקסט ---


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "delete from tasks",
        "update tasks set status = 'done'",
        "insert into tasks (title) values ('x')",
        "drop table tasks",
        "select 1; drop table tasks",
        "select * from tasks -- הערה",
        "select * from tasks /* הערה */",
        "with x as (insert into tasks (title) values ('a') returning id) select * from x",
        "select * from login_codes",
        "select code_hash from login_codes",
        "select * from memory_facts",
        "select * from pg_roles",
        "select * from information_schema.tables",
    ],
)
def test_a_query_that_is_not_a_plain_read_is_refused(sql):
    with pytest.raises(queries.QueryRefused):
        queries.gate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "select id, title from tasks",
        "SELECT COUNT(*) FROM tasks WHERE status = 'open'",
        "with open_tasks as (select * from tasks where status = 'open')"
        " select count(*) from open_tasks",
        "select c.name, count(t.id) from clients c left join tasks t"
        " on t.client_id = c.id group by c.name",
        "select * from tasks order by due_date offset 5",
    ],
)
def test_a_plain_read_passes(sql):
    assert "bot_query" in queries.gate(sql)


def test_the_row_limit_is_ours_and_not_the_models():
    """גם כשהמודל כותב LIMIT משלו, התקרה שלנו עוטפת אותו ומנצחת."""
    wrapped = queries.gate("select * from tasks limit 100000")
    assert wrapped.strip().endswith(f"LIMIT {queries.ROW_LIMIT}")
    assert "limit 100000" in wrapped  # הפנימי נשאר, והחיצוני גובר


def test_a_trailing_semicolon_is_fine():
    assert queries.gate("select 1;")


# --- החומה של המסד ---


def test_the_database_itself_refuses_to_write(db):
    """העסקה היא לקריאה בלבד, ולכן כתיבה נכשלת גם בלי בדיקת הטקסט.

    כאן עוקפים את gate בכוונה: זאת הנקודה — שגם אם מישהו ימצא ניסוח
    שעובר את הביטוי הרגולרי, הוא עדיין לא יוכל לשנות שורה.
    """
    with pytest.raises(queries.QueryFailed):
        queries.run("INSERT INTO tasks (title, status, priority) VALUES ('x', 'open', 'week')")


def test_a_broken_query_comes_back_as_a_failure(db):
    with pytest.raises(queries.QueryFailed) as exc:
        queries.run("SELECT nothing_here FROM tasks")
    assert "nothing_here" in str(exc.value)


def test_a_real_query_returns_rows(db):
    task(db, "לשלם ארנונה", due_date=date(2026, 12, 1))
    columns, rows = queries.run(queries.gate("select id, title from tasks"))
    assert columns == ["id", "title"]
    assert [row[1] for row in rows] == ["לשלם ארנונה"]


def test_the_schema_the_model_sees_matches_the_real_tables(db):
    """⚠️ כל עמודה שהמודל שומע עליה חייבת להתקיים במסד.

    התיאור הוא טקסט חופשי ולא נגזר מהמודלים, ולכן מיגרציה ששינתה עמודה
    לא שוברת שום בדיקה אחרת: בשלב 2ג1 התיאור המשיך להזכיר את from_bot
    בטבלת המשימות אחרי שהוחלפה ב-source, והמודל היה כותב שאילתה שנכשלת.
    הבדיקות לא קוראות ל-API, ולכן רק השוואה כזאת תופסת את זה.
    """
    entries = re.findall(r"^- (\w+): (.+?)(?=^- |^\S)", queries.SCHEMA_DOC, re.M | re.S)
    assert len(entries) >= 6
    for table, body in entries:
        columns = [c.strip() for c in re.sub(r"\([^)]*\)", "", body).split(",")]
        assert all(columns), (table, columns)
        # ‏LIMIT 0 בודק שמות בלי להחזיר שורות, ודרך אותה חומה של שאילתה אמיתית
        found, _ = queries.run(queries.gate(f"select {', '.join(columns)} from {table}"))
        assert found == columns


# --- ניסוח התשובה ---


def test_an_empty_result_says_so():
    assert queries.render(["id"], [], "פתוח אצל דני") == "פתוח אצל דני: אין תוצאות."


def test_the_id_column_numbers_the_rows_instead_of_showing():
    text = queries.render(["id", "title"], [(7, "לשלם ארנונה"), (9, "להתקשר")], "פתוח")
    assert text.splitlines() == ["פתוח (2):", "1. לשלם ארנונה", "2. להתקשר"]


def test_a_long_result_is_cut_and_says_how_many_are_left():
    rows = [(index, f"משימה {index}") for index in range(queries.ROWS_SHOWN + 5)]
    text = queries.render(["id", "title"], rows, "הכול")
    assert text.endswith("...ועוד 5")


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "—"),
        (True, "כן"),
        (False, "לא"),
        (date(2026, 12, 1), "01/12/2026"),
        (datetime(2026, 12, 1, 9, 30), "01/12/2026 09:30"),
        (5, "5"),
    ],
)
def test_values_read_like_hebrew_and_not_like_a_database(value, expected):
    assert queries.cell(value) == expected


def test_a_single_value_is_an_answer_and_not_a_list_of_one():
    """⚠️ מהודעה אמיתית: "כמה פתוחות להיום" ענה "(1):" ומתחתיו "1. 13"."""
    text = queries.render(["open_today"], [(13,)], "משימות פתוחות להיום")
    assert text == "משימות פתוחות להיום: 13"


def test_a_single_row_of_totals_is_one_line_too():
    text = queries.render(["open", "done"], [(13, 40)], "סיכום")
    assert text == "סיכום: 13 · 40"


def test_a_single_task_stays_numbered_so_it_can_be_closed():
    """שורה יחידה עם id היא משימה שאפשר לומר עליה "סיימתי 1"."""
    text = queries.render(["id", "title"], [(7, "לשלם ארנונה")], "פתוח")
    assert text.splitlines() == ["פתוח (1):", "1. לשלם ארנונה"]


def test_stored_values_come_out_in_the_dashboards_hebrew():
    """⚠️ מהודעה אמיתית: מסגרת הזמן הופיעה כ-today וכ-week."""
    rows = [(1, "א", "today", "open", "whatsapp"), (2, "ב", "week", "done", "dashboard")]
    text = queries.render(["id", "title", "priority", "status", "source"], rows, "הכול")
    assert text.splitlines()[1:] == [
        "1. א · היום · פתוח · מוואטסאפ",
        "2. ב · השבוע · הסתיים · מהמערכת",
    ]


def test_a_title_that_looks_like_a_stored_value_is_left_alone():
    """התרגום הוא לפי שם העמודה. כותרת שהיא במקרה "week" נשארת כותרת."""
    text = queries.render(["id", "title"], [(1, "week"), (2, "today")], "פתוח")
    assert text.splitlines()[1:] == ["1. week", "2. today"]


def test_an_unknown_value_passes_through():
    assert queries.cell("someday", "priority") == "someday"


def test_every_stored_value_has_a_label():
    """ערך חדש במודל בלי תווית היה יוצא למשתמש באנגלית, בלי ששום דבר נשבר."""
    expected = {
        "priority": schemas.Priority,
        "source": schemas.TaskSource,
        "interval_unit": schemas.RepeatUnit,
    }
    for column, literal in expected.items():
        assert set(queries.LABELS[column]) == set(get_args(literal)), column
    statuses = set(get_args(schemas.TaskStatus)) | set(get_args(schemas.ProjectStatus))
    assert set(queries.LABELS["status"]) == statuses


# --- המספור, ולמי הוא שייך ---


def test_numbers_point_at_tasks_only_when_the_question_was_about_tasks():
    columns, rows = ["id", "title"], [(3, "א"), (4, "ב")]
    assert queries.task_ids("select id, title from tasks", columns, rows) == [3, 4]
    # ‏⚠️ הלב של הבדיקה: "סיימתי 2" אחרי שאילתה על לקוחות היה סוגר
    # משימה אקראית שמספרה 4
    assert queries.task_ids("select id, name from clients", columns, rows) == []
    assert queries.task_ids("select count(*) from tasks", ["count"], [(2,)]) == []


# --- דרך הבוט ---


def test_the_bot_answers_a_question_and_the_numbers_work(db):
    first = task(db, "לשלם ארנונה")
    second = task(db, "להתקשר לדני")

    outcome = actions.execute(
        db,
        Intent(
            action="query_data",
            title="מה פתוח",
            sql="select id, title from tasks where status = 'open' order by id",
        ),
    )
    assert outcome.reply.startswith("מה פתוח (2):")
    assert "לשלם ארנונה" in outcome.reply
    assert outcome.listed_task_ids == [first.id, second.id]
    assert outcome.query_sql.startswith("select id, title")


def test_a_refused_query_tells_the_user_and_runs_nothing(db):
    task(db, "לשלם ארנונה")
    outcome = actions.execute(
        db, Intent(action="query_data", title="הכול", sql="delete from tasks")
    )
    assert "לא הרצתי" in outcome.reply
    assert db.scalars(select(Task)).all()  # המשימה עדיין שם
    assert outcome.query_sql == "delete from tasks"
    assert outcome.listed_task_ids == []


def test_a_failed_query_asks_to_rephrase_and_keeps_the_error(db):
    outcome = actions.execute(
        db, Intent(action="query_data", title="הכול", sql="select oops from tasks")
    )
    assert "לנסח את השאלה אחרת" in outcome.reply
    assert "oops" in outcome.query_error


def test_a_query_clears_the_numbering_of_the_previous_list(db):
    """אחרת "סיימתי 2" אחרי שאילתה היה חוזר לרשימה שהוצגה לפניה."""
    outcome = actions.execute(
        db, Intent(action="query_data", title="לקוחות", sql="select name from clients")
    )
    assert outcome.clear_list is True
    assert outcome.listed_task_ids == []


def test_a_question_about_clients_answers_without_touching_tasks(db):
    db.add(Client(name="קניון ליין", is_active=True))
    db.commit()
    outcome = actions.execute(
        db,
        Intent(action="query_data", title="לקוחות פעילים", sql="select name from clients"),
    )
    assert "קניון ליין" in outcome.reply


# --- חיבור משתמש הקריאה ---


def test_the_readonly_user_is_used_only_when_a_password_is_set(monkeypatch):
    settings = queries.get_settings()
    monkeypatch.setattr(settings, "bot_readonly_password", "")
    assert queries.readonly_url() == settings.database_url

    monkeypatch.setattr(settings, "bot_readonly_password", "s3cret")
    url = queries.readonly_url()
    assert f"//{queries.READONLY_ROLE}:" in url
    assert settings.database_url.rsplit("@", 1)[1] in url
