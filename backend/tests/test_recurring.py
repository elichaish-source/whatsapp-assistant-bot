"""בדיקות להתחייבויות חוזרות: חישוב המחזורים, יצירת המשימה, והנדנוד.

כל הבדיקות עובדות עם רגע מפורש ולא עם "עכשיו", כדי שהתוצאה לא תשתנה לפי
היום שבו הן רצות.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app import recurring
from app.bot import reminders
from app.models import Observation, Recurrence, Task

TZ = ZoneInfo("Asia/Jerusalem")


def moment(day: str, hour: int = 10) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00").replace(tzinfo=TZ)


def recurrence(db, **kwargs) -> Recurrence:
    data = {
        "title": "דוח מע״מ",
        "interval_unit": "month",
        "interval_count": 2,
        "start_date": date(2026, 1, 15),
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


def tasks(db) -> list[Task]:
    return list(db.scalars(select(Task).order_by(Task.id)).all())


def kinds(db) -> list[str]:
    return [row.kind for row in db.scalars(select(Observation).order_by(Observation.id)).all()]


# --- חישוב התאריך הבא ---


def test_a_short_month_does_not_steal_the_day_for_good():
    # ‏31.1 בתוספת חודש הוא 28.2, אבל בתוספת שניים חוזר ל-31.3. שדה מתגלגל
    # היה נשאר על 28 לנצח, אחרי פברואר אחד
    start = date(2026, 1, 31)
    assert recurring.shift(start, "month", 1) == date(2026, 2, 28)
    assert recurring.shift(start, "month", 2) == date(2026, 3, 31)


def test_a_leap_day_comes_back_every_four_years():
    assert recurring.shift(date(2028, 2, 29), "year", 1) == date(2029, 2, 28)
    assert recurring.shift(date(2028, 2, 29), "year", 4) == date(2032, 2, 29)


def test_weeks_and_years_move_as_expected():
    assert recurring.shift(date(2026, 11, 2), "week", 3) == date(2026, 11, 23)
    assert recurring.shift(date(2026, 11, 2), "year", 1) == date(2027, 11, 2)


def test_the_frequency_reads_in_hebrew():
    assert recurring.describe_interval("month", 1) == "כל חודש"
    assert recurring.describe_interval("month", 2) == "כל חודשיים"
    assert recurring.describe_interval("week", 3) == "כל 3 שבועות"
    assert recurring.describe_interval("year", 1) == "כל שנה"


def test_a_start_date_in_the_past_skips_to_the_next_cycle(db):
    rec = recurrence(db, start_date=date(2026, 1, 15))
    recurring.catch_up(rec, date(2026, 11, 4))
    # כל חודשיים מ-15.1 נופל ב-15 בחודשים אי-זוגיים, והקרוב שלא עבר הוא 15.11
    assert recurring.next_due(rec) == date(2026, 11, 15)
    assert rec.cycle == 5


# --- המחזור הופך למשימה ---


def test_the_cycle_becomes_a_real_task(db):
    rec = recurrence(db, start_date=date(2026, 11, 4), priority="today", notes="דרך האתר")
    assert recurring.materialize(db, moment("2026-11-04")) == 1

    task = tasks(db)[0]
    assert task.title == "דוח מע״מ"
    assert task.due_date == date(2026, 11, 4)
    assert task.priority == "today"
    assert task.notes == "דרך האתר"
    assert task.recurrence_id == rec.id
    assert task.status == "open"
    # התזכורת יוצאת מיד: יום ההתראה הוא היום, והשעה הקבועה כבר עברה
    assert task.reminder_at == moment("2026-11-04")

    db.refresh(rec)
    assert rec.cycle == 1
    assert kinds(db) == ["recurrence_due"]


def test_the_lead_time_puts_the_reminder_before_the_date(db):
    recurrence(db, start_date=date(2026, 11, 20), interval_unit="year", lead_days=14)
    assert recurring.materialize(db, moment("2026-11-06", 7)) == 1

    task = tasks(db)[0]
    assert task.due_date == date(2026, 11, 20)
    assert task.reminder_at == moment("2026-11-06", 9)


def test_nothing_is_created_before_the_window_opens(db):
    recurrence(db, start_date=date(2026, 11, 20), lead_days=3)
    assert recurring.materialize(db, moment("2026-11-16")) == 0
    assert tasks(db) == []
    assert recurring.materialize(db, moment("2026-11-17")) == 1


def test_only_one_cycle_is_open_at_a_time(db):
    recurrence(db, start_date=date(2026, 11, 4), interval_unit="week", interval_count=1)
    assert recurring.materialize(db, moment("2026-11-04")) == 1
    # שבוע אחרי, והמשימה הקודמת עוד פתוחה: לא נוצרת שנייה
    assert recurring.materialize(db, moment("2026-11-11")) == 0
    assert len(tasks(db)) == 1


def test_closing_the_cycle_opens_the_next_one(db):
    recurrence(db, start_date=date(2026, 11, 4), interval_unit="week", interval_count=1)
    recurring.materialize(db, moment("2026-11-04"))
    done = tasks(db)[0]
    done.status = "done"
    db.commit()

    assert recurring.materialize(db, moment("2026-11-11")) == 1
    assert [task.due_date for task in tasks(db)] == [date(2026, 11, 4), date(2026, 11, 11)]


def test_a_paused_recurrence_creates_nothing(db):
    recurrence(db, start_date=date(2026, 11, 4), active=False)
    assert recurring.materialize(db, moment("2026-11-04")) == 0
    assert tasks(db) == []


# --- הנדנוד ---


def test_the_reminder_comes_back_every_day_until_it_is_done(db, sent):
    recurrence(db, start_date=date(2026, 11, 4), interval_unit="year")
    recurring.materialize(db, moment("2026-11-04"))

    assert reminders.send_due_reminders(db, moment("2026-11-04")) == 1
    task = tasks(db)[0]
    db.refresh(task)
    # הנדנוד קובע תזכורת למחר ומבטל את הסימון "נשלחה", אחרת היא לא תצא שוב
    assert task.reminder_sent_at is None
    assert task.reminder_at == moment("2026-11-05")

    assert reminders.send_due_reminders(db, moment("2026-11-05")) == 1
    assert len(sent) == 2
    # ההודעה החוזרת אומרת למה היא חוזרת
    assert "עבר התאריך" in sent[1][1]


def test_the_nagging_stops_seven_days_after_the_date(db, sent):
    recurrence(db, start_date=date(2026, 11, 4), interval_unit="year")
    recurring.materialize(db, moment("2026-11-04"))
    task = tasks(db)[0]
    task.reminder_at = moment("2026-11-11", 9)
    task.reminder_sent_at = None
    db.commit()

    assert reminders.send_due_reminders(db, moment("2026-11-11")) == 1
    db.refresh(task)
    assert task.reminder_sent_at is not None


def test_a_task_that_was_done_is_not_nagged(db, sent):
    recurrence(db, start_date=date(2026, 11, 4), interval_unit="year")
    recurring.materialize(db, moment("2026-11-04"))
    task = tasks(db)[0]
    task.status = "done"
    db.commit()

    assert reminders.send_due_reminders(db, moment("2026-11-04")) == 0
    assert sent == []


def test_an_ordinary_reminder_does_not_nag(db, sent):
    task = Task(title="להתפלל ערבית", status="open", reminder_at=moment("2026-11-04", 9))
    db.add(task)
    db.commit()

    assert reminders.send_due_reminders(db, moment("2026-11-04")) == 1
    db.refresh(task)
    assert task.reminder_sent_at is not None
    assert len(sent) == 1


def test_a_recurring_reminder_is_not_thrown_away_as_stale(db, sent):
    """חידוש ביטוח רלוונטי גם אחרי יום שהשרת היה כבוי. "בעוד עשר דקות" לא."""
    recurrence(db, start_date=date(2026, 11, 4), interval_unit="year")
    recurring.materialize(db, moment("2026-11-04"))

    # עשרים שעות אחרי — מעבר לחלון ההתיישנות של תזכורת רגילה
    assert reminders.send_due_reminders(db, moment("2026-11-05", 6)) == 1
    assert len(sent) == 1


# --- המסך בדשבורד ---


def test_recurrences_are_closed_to_anyone_who_is_not_signed_in(anon):
    assert anon.get("/api/recurrences").status_code == 401
    assert anon.post("/api/recurrences", json={"title": "x"}).status_code == 401


def test_a_recurrence_is_created_read_and_deleted(client, db):
    created = client.post(
        "/api/recurrences",
        json={
            "title": "חידוש ביטוח רכב",
            "interval_unit": "year",
            "interval_count": 1,
            "start_date": "2027-03-01",
            "lead_days": 14,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["every"] == "כל שנה"
    assert body["next_due"] == "2027-03-01"
    # מחזור עתידי: עוד לא נוצרה משימה
    assert body["open_task_id"] is None

    assert [item["id"] for item in client.get("/api/recurrences").json()] == [body["id"]]
    assert client.delete(f"/api/recurrences/{body['id']}").status_code == 200
    assert client.get("/api/recurrences").json() == []
    assert kinds(db) == ["recurrence_created", "recurrence_removed"]


def test_a_frequency_outside_the_range_is_refused(client):
    for change in (
        {"interval_count": 0},
        {"interval_count": 99},
        {"interval_unit": "day"},
        {"lead_days": -1},
        {"lead_days": 400},
    ):
        body = {
            "title": "משהו",
            "interval_unit": "month",
            "interval_count": 1,
            "start_date": "2027-01-01",
        }
        body.update(change)
        assert client.post("/api/recurrences", json=body).status_code == 422


def test_a_client_that_does_not_exist_is_refused(client):
    body = {
        "title": "משהו",
        "interval_unit": "month",
        "interval_count": 1,
        "start_date": "2027-01-01",
        "client_id": 999,
    }
    assert client.post("/api/recurrences", json=body).status_code == 422


def test_a_missing_recurrence_is_a_404(client):
    assert client.delete("/api/recurrences/999").status_code == 404


def test_changing_the_frequency_restarts_the_count(client, db):
    body = {
        "title": "דוח מע״מ",
        "interval_unit": "month",
        "interval_count": 2,
        "start_date": "2027-01-15",
    }
    created = client.post("/api/recurrences", json=body).json()
    rec = db.get(Recurrence, created["id"])
    rec.cycle = 3  # כאילו עברו שלושה מחזורים
    db.commit()

    # שינוי שאינו נוגע לעוגן לא מזיז את המחזורים
    same = client.put(
        f"/api/recurrences/{created['id']}", json={**body, "title": "דוח לרשות"}
    ).json()
    assert same["next_due"] == "2027-07-15"

    # שינוי התדירות מאפס את המניין, אחרת התאריך הבא היה נגזר מעוגן אחר
    moved = client.put(
        f"/api/recurrences/{created['id']}", json={**body, "interval_count": 3}
    ).json()
    assert moved["every"] == "כל 3 חודשים"
    assert moved["next_due"] == "2027-01-15"


def test_deleting_a_recurrence_keeps_the_tasks_it_created(client, db):
    rec = recurrence(db, start_date=date(2026, 11, 4), interval_unit="year")
    recurring.materialize(db, moment("2026-11-04"))

    assert client.delete(f"/api/recurrences/{rec.id}").status_code == 200
    task = tasks(db)[0]
    db.refresh(task)
    assert task.recurrence_id is None
    assert task.status == "open"


def test_the_screen_says_when_the_current_cycle_is_still_open(client, db):
    rec = recurrence(db, start_date=date(2026, 11, 4), interval_unit="week", interval_count=1)
    recurring.materialize(db, moment("2026-11-04"))

    row = next(item for item in client.get("/api/recurrences").json() if item["id"] == rec.id)
    assert row["open_task_id"] == tasks(db)[0].id
    assert row["next_due"] == "2026-11-11"
