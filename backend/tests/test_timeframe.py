"""מסגרת הזמן: התיוג "מחר", החותמת שלו וההתגלגלות ל"היום"."""

from datetime import date, timedelta

from app import timeframe
from app.models import Task


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
