"""מסגרת הזמן: התיוג "מחר", החותמת שלו וההתגלגלות ל"היום"."""

from datetime import date, timedelta

from sqlalchemy import select

from app import timeframe
from app.models import Observation, Task


def _task(db, title: str, **kwargs) -> Task:
    kwargs.setdefault("status", "open")
    kwargs.setdefault("source", "dashboard")
    task = Task(title=title, **kwargs)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_dashboard_task_is_marked_as_coming_from_the_system(client):
    r = client.post("/api/tasks", json={"title": "לבדוק את הדוח", "priority": "tomorrow"})
    assert r.status_code == 201
    assert r.json()["source"] == "dashboard"
    assert r.json()["priority"] == "tomorrow"


def test_quick_tag_stamps_the_day_it_was_set(client, db):
    task_id = client.post("/api/tasks", json={"title": "להתקשר לדני"}).json()["id"]
    assert client.patch(f"/api/tasks/{task_id}/priority", json={"priority": "tomorrow"}).status_code == 200
    db.expire_all()
    task = db.get(Task, task_id)
    assert task.priority == "tomorrow"
    assert task.priority_set_on == timeframe.local_today()


def test_tomorrow_set_yesterday_becomes_today(db):
    today = date(2026, 11, 5)
    stale = _task(db, "מאתמול", priority="tomorrow", priority_set_on=today - timedelta(days=1))
    fresh = _task(db, "מהיום", priority="tomorrow", priority_set_on=today)

    assert timeframe.roll_tomorrow(db, today) == 1

    db.expire_all()
    assert db.get(Task, stale.id).priority == "today"
    # החותמת זזה יחד עם התיוג, אחרת ההתגלגלות הייתה חוזרת עליה כל סבב
    assert db.get(Task, stale.id).priority_set_on == today
    assert db.get(Task, fresh.id).priority == "tomorrow"


def test_rollover_leaves_the_other_timeframes_alone(db):
    today = date(2026, 11, 5)
    old = today - timedelta(days=30)
    week = _task(db, "השבוע", priority="week", priority_set_on=old)
    later = _task(db, "בהמשך", priority="later", priority_set_on=old)
    # משימה שבוצעה לא צריכה לעלות לראש הרשימה
    done = _task(db, "בוצעה", priority="tomorrow", priority_set_on=old, status="done")

    assert timeframe.roll_tomorrow(db, today) == 0

    db.expire_all()
    assert db.get(Task, week.id).priority == "week"
    assert db.get(Task, later.id).priority == "later"
    assert db.get(Task, done.id).priority == "tomorrow"


def test_tomorrow_without_a_stamp_is_treated_as_stale(db):
    today = date(2026, 11, 5)
    orphan = _task(db, "בלי חותמת", priority="tomorrow")
    assert timeframe.roll_tomorrow(db, today) == 1
    db.expire_all()
    assert db.get(Task, orphan.id).priority == "today"


def test_resaving_the_form_does_not_reset_the_rollover_clock(client, db):
    task_id = client.post("/api/tasks", json={"title": "דוח מע\"מ", "priority": "tomorrow"}).json()["id"]
    yesterday = timeframe.local_today() - timedelta(days=1)
    db.get(Task, task_id).priority_set_on = yesterday
    db.commit()

    # שמירה שלא נגעה במסגרת הזמן — החותמת נשארת, והמשימה תתגלגל מחר
    r = client.put(f"/api/tasks/{task_id}", json={"title": "דוח מע\"מ מעודכן", "priority": "tomorrow"})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Task, task_id).priority_set_on == yesterday

    # שינוי אמיתי של מסגרת הזמן כן מאפס אותה
    r = client.put(f"/api/tasks/{task_id}", json={"title": "דוח מע\"מ מעודכן", "priority": "week"})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Task, task_id).priority_set_on == timeframe.local_today()


def test_today_sorts_before_tomorrow_before_week(client):
    for title, priority in (("בהמשך", "later"), ("השבוע", "week"), ("מחר", "tomorrow"), ("היום", "today")):
        client.post("/api/tasks", json={"title": title, "priority": priority})
    titles = [t["title"] for t in client.get("/api/tasks").json()]
    assert titles == ["היום", "מחר", "השבוע", "בהמשך"]


def test_rollover_leaves_a_trace_in_the_observation_log(db):
    today = date(2026, 11, 5)
    task = _task(db, "להחזיר טלפון", priority="tomorrow", priority_set_on=today - timedelta(days=1))

    assert timeframe.roll_tomorrow(db, today) == 1

    # observe פותח חיבור משלו, ולכן צריך לקרוא מחדש
    db.expire_all()
    rows = db.scalars(
        select(Observation).where(Observation.task_id == task.id, Observation.kind == "task_reprioritized")
    ).all()
    assert len(rows) == 1
    assert rows[0].source == "system"
    assert "tomorrow → today" in rows[0].detail
    assert "התגלגלות אוטומטית" in rows[0].detail


def test_nothing_is_logged_when_nothing_rolls(db):
    today = date(2026, 11, 5)
    _task(db, "נקבע היום", priority="tomorrow", priority_set_on=today)

    assert timeframe.roll_tomorrow(db, today) == 0

    db.expire_all()
    assert db.scalars(select(Observation)).all() == []


# --- התקדמות לפי תאריך היעד ---


def test_the_timeframe_that_follows_from_a_date():
    today = date(2026, 11, 15)
    assert timeframe.for_due(today - timedelta(days=3), today) == "today"
    assert timeframe.for_due(today, today) == "today"
    assert timeframe.for_due(today + timedelta(days=1), today) == "tomorrow"
    assert timeframe.for_due(today + timedelta(days=2), today) == "week"
    assert timeframe.for_due(today + timedelta(days=7), today) == "week"
    assert timeframe.for_due(today + timedelta(days=8), today) == "later"


def test_a_postponed_task_climbs_back_as_its_date_gets_close(db):
    """המסלול המלא: בהמשך → השבוע → מחר → היום, בלי שאף אחד נוגע במשימה."""
    start = date(2026, 11, 15)
    due = start + timedelta(days=10)
    task = _task(db, "לחדש את הביטוח", priority="later", priority_set_on=start, due_date=due)

    seen = {}
    for offset in range(1, 11):
        day = start + timedelta(days=offset)
        timeframe.roll_tomorrow(db, day)
        timeframe.roll_due(db, day)
        db.expire_all()
        seen[offset] = db.get(Task, task.id).priority

    assert seen[2] == "later"
    assert seen[3] == "week"
    assert seen[8] == "week"
    assert seen[9] == "tomorrow"
    assert seen[10] == "today"


def test_the_date_only_ever_raises_the_timeframe(db):
    """⚠️ "היום" על משימה עם תאריך רחוק הוא החלטה של המשתמש, ולא מורד."""
    today = date(2026, 11, 15)
    old = today - timedelta(days=5)
    urgent = _task(db, "דחוף", priority="today", priority_set_on=old, due_date=today + timedelta(days=30))
    soon = _task(db, "מחר", priority="tomorrow", priority_set_on=today, due_date=today + timedelta(days=5))
    far = _task(db, "רחוק", priority="week", priority_set_on=old, due_date=today + timedelta(days=30))

    assert timeframe.roll_due(db, today) == 0

    db.expire_all()
    assert db.get(Task, urgent.id).priority == "today"
    assert db.get(Task, soon.id).priority == "tomorrow"
    assert db.get(Task, far.id).priority == "week"


def test_an_overdue_task_moves_to_today(db):
    today = date(2026, 11, 15)
    task = _task(
        db, "באיחור", priority="later", priority_set_on=today - timedelta(days=9),
        due_date=today - timedelta(days=4),
    )
    assert timeframe.roll_due(db, today) == 1
    db.expire_all()
    assert db.get(Task, task.id).priority == "today"
    assert db.get(Task, task.id).priority_set_on == today


def test_a_tag_set_today_holds_until_tomorrow(db):
    """בלי זה כפתור התיוג בדשבורד היה נראה שבור: התאריך היה דורס אותו תוך דקה."""
    today = date(2026, 11, 15)
    task = _task(db, "תויג עכשיו", priority="later", priority_set_on=today, due_date=today + timedelta(days=1))

    assert timeframe.roll_due(db, today) == 0
    db.expire_all()
    assert db.get(Task, task.id).priority == "later"

    assert timeframe.roll_due(db, today + timedelta(days=1)) == 1
    db.expire_all()
    assert db.get(Task, task.id).priority == "today"


def test_tasks_without_a_date_and_closed_tasks_are_left_alone(db):
    today = date(2026, 11, 15)
    old = today - timedelta(days=5)
    no_date = _task(db, "בלי תאריך", priority="later", priority_set_on=old)
    done = _task(db, "בוצעה", priority="later", priority_set_on=old, due_date=today, status="done")

    assert timeframe.roll_due(db, today) == 0
    db.expire_all()
    assert db.get(Task, no_date.id).priority == "later"
    assert db.get(Task, done.id).priority == "later"


def test_the_climb_is_written_to_the_journal(db):
    today = date(2026, 11, 15)
    task = _task(
        db, "לחדש את הביטוח", priority="later", priority_set_on=today - timedelta(days=5),
        due_date=today + timedelta(days=4),
    )
    assert timeframe.roll_due(db, today) == 1

    db.expire_all()
    rows = db.scalars(
        select(Observation).where(Observation.task_id == task.id, Observation.kind == "task_reprioritized")
    ).all()
    assert len(rows) == 1
    assert rows[0].source == "system"
    assert "later → week" in rows[0].detail
    assert "לפי תאריך היעד" in rows[0].detail
