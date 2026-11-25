"""בדיקות לשכבת השירות של היומן (שלב 4ב-1). אין כאן אף פנייה לגוגל.

מה שנבדק הוא ההמרה והבחירה — קידוד המזהה, אירוע של כל היום, אילו יומנים
נקראים, והמיון. אלה הדברים שנשברים בשקט.

⚠️ מה שהבדיקות **לא** יכולות לכסות, ולכן נבדק מול היומן האמיתי אחרי
הפריסה: בחירת הפעולה על ידי המודל, ושהסכימה עוברת את ה-API.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app import gcal
from app.config import get_settings

IL = ZoneInfo("Asia/Jerusalem")


def timed(start: str, end: str | None = None, **extra) -> dict:
    raw = {"id": "e1", "summary": "פגישה", "start": {"dateTime": start}}
    if end:
        raw["end"] = {"dateTime": end}
    raw.update(extra)
    return raw


# --- קידוד המזהה: הלקח של ה-404 ---


def test_a_calendar_id_with_a_hash_is_url_encoded():
    """⚠️⚠️ זה הבאג שבוזבז עליו זמן ב-24.11.2026.

    מזהה יומן החגים מכיל ``#``, וללא קידוד הוא הופך את שאר המזהה לעוגן:
    גוגל מקבלת נתיב קטוע ומחזירה **404**, שנראה כמו "אין יומן כזה".
    """
    path = gcal._path("iw.jewish#holiday@group.v.calendar.google.com")
    assert "#" not in path
    assert "%23holiday" in path
    # ‏@ ונקודות אינם חייבים קידוד, אבל safe="" מקודד אותם — וזה תקף
    assert path.startswith("calendars/")
    assert path.endswith("/events")


def test_every_calendar_id_is_encoded_even_without_a_hash():
    """הקידוד אינו מותנה בכך שראינו ``#``, כדי שלא יישכח במזהה הבא."""
    assert gcal._path("me@gmail.com") == "calendars/me%40gmail.com/events"


# --- אירוע של כל היום ---


def test_an_all_day_event_has_no_time():
    """⚠️ ``start.date`` ולא ``start.dateTime``, ואין לו שעה בכלל.

    להמיר אותו ל-00:00 היה מציג "חופשה 00:00" בראש היום, כאילו היא אירוע
    שמתחיל בחצות.
    """
    event = gcal._parse({"id": "e", "summary": "חופשה", "start": {"date": "2026-12-01"}}, "ראשי")
    assert event is not None
    assert event.all_day is True
    assert event.start is None
    assert event.day == date(2026, 12, 1)
    assert event.when == date(2026, 12, 1)
    assert event.minutes == 0


def test_a_timed_event_is_converted_to_israel_time():
    """גוגל מחזירה היסט, והתשובה למשתמש היא בשעון ישראל."""
    event = gcal._parse(timed("2026-11-25T07:30:00Z", "2026-11-25T08:30:00Z"), "ראשי")
    assert event is not None
    assert event.all_day is False
    assert event.start.strftime("%H:%M") == "09:30"
    assert event.minutes == 60
    assert event.when == date(2026, 11, 25)


def test_an_event_without_a_start_is_dropped():
    """אירוע בלי התחלה אינו ניתן להצגה, ועדיף להשמיט אותו מלהתרסק."""
    assert gcal._parse({"id": "e", "summary": "משהו"}, "ראשי") is None


def test_a_broken_date_is_dropped_and_does_not_raise():
    assert gcal._parse({"id": "e", "start": {"date": "2026-13-45"}}, "ראשי") is None
    assert gcal._parse({"id": "e", "start": {"dateTime": "לא תאריך"}}, "ראשי") is None


def test_an_event_without_a_title_still_shows():
    """כותרת ריקה אינה סיבה להעלים אירוע מהיומן."""
    event = gcal._parse(timed("2026-11-25T07:30:00Z"), "ראשי")
    event_blank = gcal._parse(
        {"id": "e", "summary": "   ", "start": {"dateTime": "2026-11-25T07:30:00Z"}}, "ראשי"
    )
    assert event is not None and event_blank is not None
    assert event_blank.title == "(בלי כותרת)"


def test_the_user_is_not_listed_as_an_attendee_of_his_own_meeting():
    """⚠️ בלי זה כל פגישה שהמשתמש ארגן הייתה מוצגת עם אדם אחד יותר."""
    raw = timed(
        "2026-11-25T07:30:00Z",
        attendees=[
            {"email": "me@gmail.com", "self": True},
            {"email": "dani@example.com"},
            {"displayName": "בלי כתובת"},
        ],
    )
    event = gcal._parse(raw, "ראשי")
    assert event is not None
    assert event.attendees == ["dani@example.com"]


# --- אילו יומנים נקראים ---


def calendar_list(*items) -> dict:
    return {"items": list(items)}


def entry(cal_id: str, name: str, role: str = "owner", primary: bool = False) -> dict:
    raw = {"id": cal_id, "summary": name, "accessRole": role}
    if primary:
        raw["primary"] = True
    return raw


def test_only_owned_calendars_are_read(db, monkeypatch):
    """⚠️ ההכרעה של 24.11.2026: הראשי והמשפחתי, ולא מה שאינו של המשתמש.

    חדר הישיבות ויומן החגים מגיעים בהרשאת ``reader``, ולכן כלל ההרשאה
    לבדו מוציא את שניהם — ויומן חגים בתשובה היומית היה מוסיף שורה כמעט
    כל שבוע.
    """
    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(
        gcal,
        "_request",
        lambda token, path, params=None: calendar_list(
            entry("me@gmail.com", "אני", primary=True),
            entry("family@group.calendar.google.com", "היומן המשפחתי"),
            entry("room@group.calendar.google.com", "חדר ישיבות", role="reader"),
            entry("iw.jewish#holiday@group.v.calendar.google.com", "חגים", role="reader"),
        ),
    )
    names = [cal.name for cal in gcal.calendars(db)]
    assert names == ["אני", "היומן המשפחתי"]


def test_a_generated_calendar_is_excluded_even_if_google_calls_it_owned(db, monkeypatch):
    """חגורה שנייה: יומן שגוגל מייצרת יושב תמיד תחת אותו דומיין."""
    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(
        gcal,
        "_request",
        lambda token, path, params=None: calendar_list(
            entry("me@gmail.com", "אני", primary=True),
            entry("iw.jewish#holiday@group.v.calendar.google.com", "חגים"),
        ),
    )
    assert [cal.name for cal in gcal.calendars(db)] == ["אני"]


def test_calendar_skip_removes_a_calendar_by_id(db, monkeypatch):
    """⚠️ ההחרגה יושבת ב-.env ולא בקוד: מזהה יומן הוא נתון של ההתקנה."""
    get_settings.cache_clear()
    monkeypatch.setenv("CALENDAR_SKIP", "tasks@group.calendar.google.com")
    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(
        gcal,
        "_request",
        lambda token, path, params=None: calendar_list(
            entry("me@gmail.com", "אני", primary=True),
            entry("tasks@group.calendar.google.com", "משימות"),
        ),
    )
    try:
        assert [cal.name for cal in gcal.calendars(db)] == ["אני"]
    finally:
        get_settings.cache_clear()


def test_nothing_is_skipped_by_default(db, monkeypatch):
    """⚠️ הכשל הוא לכיוון "להציג".

    כשההחרגה ריקה נקראים כל היומנים שבבעלות המשתמש. זאת אותה הכרעה
    שנקבעה לסינון המיילים ב-4-2: אירוע שנעלם בשקט הוא הכשל היחיד שאסור.
    """
    get_settings.cache_clear()
    monkeypatch.delenv("CALENDAR_SKIP", raising=False)
    try:
        assert gcal.skipped() == set()
    finally:
        get_settings.cache_clear()


def test_the_primary_calendar_comes_first(db, monkeypatch):
    """סדר קבוע בין הרצות, כדי שהתשובה לא תשתנה בלי סיבה."""
    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(
        gcal,
        "_request",
        lambda token, path, params=None: calendar_list(
            entry("aaa@group.calendar.google.com", "אלף"),
            entry("me@gmail.com", "אני", primary=True),
        ),
    )
    assert [cal.primary for cal in gcal.calendars(db)] == [True, False]


# --- הטווח ---


def test_today_is_one_day():
    first, last = gcal.span("today", date(2026, 11, 24))
    assert (first, last) == (date(2026, 11, 24), date(2026, 11, 24))


def test_tomorrow_is_only_tomorrow():
    """⚠️ מחר הוא מחר, ולא "היום ומחר"."""
    first, last = gcal.span("tomorrow", date(2026, 11, 24))
    assert (first, last) == (date(2026, 11, 25), date(2026, 11, 25))


def test_a_week_is_seven_days_forward_and_not_until_saturday():
    """⚠️ מי ששואל ביום חמישי "מה יש לי השבוע" מתכוון לשבוע הקרוב.

    "עד שבת" היה מחזיר לו יומיים ונראה כאילו היומן ריק.
    """
    first, last = gcal.span("week", date(2026, 11, 26))
    assert (first, last) == (date(2026, 11, 26), date(2026, 12, 2))


def test_an_unknown_scope_falls_back_to_today():
    assert gcal.span("לא קיים", date(2026, 11, 24))[0] == date(2026, 11, 24)


# --- המיון והשליפה ---


def test_events_from_several_calendars_are_merged_and_sorted(db, monkeypatch):
    """⚠️ זה הלב של ההכרעה: "מה יש לי מחר" קורא מכמה יומנים.

    כרגע רק הראשי בשימוש בפועל, ולכן ההבדל אינו נראה — אבל ברגע שתיכנס
    פגישה ליומן המשפחתי, תשובה שקוראת רק את הראשי תהיה **שגויה בשקט**.
    """
    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(
        gcal,
        "calendars",
        lambda session: [
            gcal.Calendar(id="me@gmail.com", name="ראשי", primary=True),
            gcal.Calendar(id="family@group.calendar.google.com", name="משפחתי"),
        ],
    )

    def fake(token, cal, begins, ends):
        assert token == "tok"
        if cal.name == "ראשי":
            return [
                gcal.Event(
                    id="a",
                    title="מאוחר",
                    calendar="ראשי",
                    start=datetime(2026, 11, 25, 14, 0, tzinfo=IL),
                )
            ]
        return [
            gcal.Event(
                id="b",
                title="מוקדם",
                calendar="משפחתי",
                start=datetime(2026, 11, 25, 9, 0, tzinfo=IL),
            ),
            gcal.Event(id="c", title="כל היום", calendar="משפחתי", all_day=True, day=date(2026, 11, 25)),
        ]

    monkeypatch.setattr(gcal, "_events", fake)
    found = gcal.agenda(db, "tomorrow")
    # אירוע של כל היום ראשון באותו תאריך, ואחריו לפי שעה
    assert [event.title for event in found] == ["כל היום", "מוקדם", "מאוחר"]


def test_no_calendars_means_no_events_and_no_call(db, monkeypatch):
    """בלי יומנים אין למי לפנות, ואין טעם לשלוף טוקן."""
    monkeypatch.setattr(gcal, "calendars", lambda session: [])

    def explode(*args, **kwargs):  # pragma: no cover - אמור לא להיקרא
        raise AssertionError("לא אמורה להיות פנייה לגוגל")

    monkeypatch.setattr(gcal, "_events", explode)
    assert gcal.agenda(db, "today") == []


def test_recurring_events_are_expanded_by_single_events(db, monkeypatch):
    """⚠️ בלי ``singleEvents``, פגישה שבועית חוזרת מוחזרת כהגדרה אחת.

    כלומר "מה יש לי מחר" היה מחמיץ אותה לגמרי — וביומן האמיתי רוב
    הפגישות הן חוזרות.
    """
    seen: dict = {}

    def capture(token, path, params=None):
        seen.update(params or {})
        return {"items": []}

    monkeypatch.setattr(gcal, "_request", capture)
    gcal._events(
        "tok",
        gcal.Calendar(id="me@gmail.com", name="ראשי"),
        datetime(2026, 11, 25, tzinfo=IL),
        datetime(2026, 11, 26, tzinfo=IL),
    )
    assert seen["singleEvents"] == "true"
    assert seen["orderBy"] == "startTime"


def test_a_session_is_never_used_inside_the_threads(db, monkeypatch):
    """⚠️ ``Session`` של SQLAlchemy אינו בטוח לשימוש מקביל.

    זה הבאג שתוקן ב-``gmail._summaries`` וכמעט חזר ב-``_thread_tail``
    ב-4-6. הבדיקה מוודאת ש-``_events`` מקבלת טוקן, ולא ``Session``.
    """
    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(
        gcal, "calendars", lambda session: [gcal.Calendar(id="me@gmail.com", name="ראשי")]
    )
    got: list = []

    def fake(token, cal, begins, ends):
        got.append(token)
        return []

    monkeypatch.setattr(gcal, "_events", fake)
    gcal.agenda(db, "today")
    assert got == ["tok"]
    assert all(isinstance(item, str) for item in got)


# --- מה לא נעשה כאן, ויש בדיקה שתשמור על זה ---


def test_the_calendar_layer_never_modifies_an_existing_event(monkeypatch):
    """⚠️ ‏4ב-2 יוצרת ומוחקת, **ואינה משנה אירוע קיים.**

    עד 4ב-1 הבדיקה הזאת אסרה כל כתיבה. היא נפתחה במכוון: ``freeBusy``
    הוא POST שאינו כותב, ``events.insert`` הוא POST שכן, ו-``delete``
    נחוץ ל"בטל". **מה שנשאר אסור הוא PATCH ו-PUT** — שינוי של אירוע
    שהבוט לא יצר הוא 4ב-3 ואילך, ובלי הגדרה הוא עלול לדרוס פגישה.
    """
    source = (gcal.__file__ or "").replace(".pyc", ".py")
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    for verb in ("httpx.put", "httpx.patch"):
        assert verb not in text, verb


def test_the_calendar_layer_calls_no_model(monkeypatch):
    """⚠️ אין כאן קריאת מודל, ולכן אין משטח הזרקה.

    שעה וכותרת הן עובדות מהיומן. כותרת אירוע היא טקסט שאדם אחר כתב,
    ובפריסה הזאת הוא אינו מגיע לשום מודל — אותה הכרעה שהייתה בתוקף
    ב-``show_email`` עד שהתקציר החזיר את משטח ההזרקה ב-24.11.
    """
    source = (gcal.__file__ or "").replace(".pyc", ".py")
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    for marker in ("anthropic", "claude", "messages.create"):
        assert marker not in text.lower(), marker


def test_an_event_knows_whether_its_calendar_is_the_primary_one(monkeypatch):
    """הדגל נקבע מהיומן שממנו נשלף האירוע, ולא מניחוש לפי השם."""
    seen: dict = {}

    def capture(token, path, params=None):
        seen["path"] = path
        return {"items": [timed("2026-11-25T07:30:00Z")]}

    monkeypatch.setattr(gcal, "_request", capture)
    from_family = gcal._events(
        "tok",
        gcal.Calendar(id="family@group.calendar.google.com", name="משפחתי", primary=False),
        datetime(2026, 11, 25, tzinfo=IL),
        datetime(2026, 11, 26, tzinfo=IL),
    )
    assert from_family[0].from_primary is False
    from_main = gcal._events(
        "tok",
        gcal.Calendar(id="me@gmail.com", name="ראשי", primary=True),
        datetime(2026, 11, 25, tzinfo=IL),
        datetime(2026, 11, 26, tzinfo=IL),
    )
    assert from_main[0].from_primary is True


def test_an_attendee_is_shown_by_name_when_google_has_one():
    """⚠️ התגלה בפלט האמיתי ב-25.11.2026.

    התשובה הציגה את כתובת המייל של המשתתף במקום את שמו. כתובת גולמית
    היא פחות קריאה ופחות שימושית — צריך לפענח אותה בראש.
    """
    raw = timed(
        "2026-11-25T07:30:00Z",
        attendees=[
            {"email": "a@example.com", "displayName": "דני כהן"},
            {"email": "noname@example.com"},
            {"email": "blank@example.com", "displayName": "   "},
        ],
    )
    event = gcal._parse(raw, "ראשי")
    assert event is not None
    # שם כשיש, וכתובת כשאין — ולא שורה ריקה
    assert event.attendees == ["דני כהן", "noname@example.com", "blank@example.com"]


def test_an_attendee_who_is_a_client_is_shown_by_the_card_name(db, monkeypatch):
    """⚠️⚠️ זה מה שבאמת פותר את שמות המשתתפים.

    העדפת ``displayName`` נכונה אך אינה מספיקה: בפלט האמיתי של
    25.11.2026 גוגל לא החזירה אותו **לאף אחד** מ-7 המשתתפים, והתשובה
    הציגה שבע כתובות מייל. השם מגיע מכרטיס הלקוח, בקוד ולא במודל.
    """
    from app.models import Client

    db.add(Client(name="דני כהן", email="Dani@Example.com"))
    db.flush()

    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(
        gcal, "calendars", lambda session: [gcal.Calendar(id="me@gmail.com", name="ראשי")]
    )
    monkeypatch.setattr(
        gcal,
        "_events",
        lambda token, cal, begins, ends: [
            gcal.Event(
                id="a",
                title="פגישה",
                calendar="ראשי",
                start=datetime(2026, 11, 25, 9, 0, tzinfo=IL),
                attendees=["dani@example.com", "stranger@example.com"],
            )
        ],
    )
    found = gcal.agenda(db, "today")
    # ⚠️ ההשוואה אינה תלויה באותיות גדולות: בכרטיס נרשם Dani@Example.com
    assert found[0].attendees == ["דני כהן", "stranger@example.com"]
    db.rollback()


def test_a_client_card_without_an_email_does_not_break_the_lookup(db):
    from app.models import Client

    db.add(Client(name="בלי מייל"))
    db.flush()
    assert gcal.client_names(db) == {}
    db.rollback()


# --- יצירה: הגבול היחיד כאן שאינו הפיך ---


def _posted(monkeypatch) -> dict:
    """תופס את הקריאה ל-POST בלי לפנות לגוגל."""
    seen: dict = {}

    class Fake:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "ev-1"}

    def capture(url, headers=None, params=None, json=None, timeout=None):
        seen.update({"url": url, "params": params or {}, "body": json or {}})
        return Fake()

    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(gcal.httpx, "post", capture)
    return seen


def test_an_event_without_guests_sends_no_invitation(db, monkeypatch):
    """⚠️⚠️ ``sendUpdates="none"`` כשאין משתתפים.

    פגישה ביומן של המשתמש לבדו אינה אמורה לייצר מייל לאף אחד, ו-``all``
    כאן היה הופך פעולה הפיכה לפעולה שאינה הפיכה.
    """
    seen = _posted(monkeypatch)
    made = gcal.create(
        db,
        "כושר",
        datetime(2026, 11, 26, 8, 0, tzinfo=IL),
        datetime(2026, 11, 26, 9, 0, tzinfo=IL),
    )
    assert made.id == "ev-1"
    assert made.invited is False
    assert seen["params"]["sendUpdates"] == "none"
    assert "attendees" not in seen["body"]


def test_an_event_with_a_guest_sends_the_invitation(db, monkeypatch):
    """⚠️⚠️ ``sendUpdates="all"`` **רק** כשנמסרו משתתפים במפורש."""
    seen = _posted(monkeypatch)
    made = gcal.create(
        db,
        "פגישה",
        datetime(2026, 11, 26, 10, 0, tzinfo=IL),
        datetime(2026, 11, 26, 11, 0, tzinfo=IL),
        ["dani@example.com"],
    )
    assert made.invited is True
    assert seen["params"]["sendUpdates"] == "all"
    assert seen["body"]["attendees"] == [{"email": "dani@example.com"}]


def test_an_empty_guest_address_is_not_an_invitation(db, monkeypatch):
    """מחרוזת ריקה ברשימה אינה משתתף, ואינה אמורה להדליק את השליחה."""
    seen = _posted(monkeypatch)
    made = gcal.create(
        db,
        "פגישה",
        datetime(2026, 11, 26, 10, 0, tzinfo=IL),
        datetime(2026, 11, 26, 11, 0, tzinfo=IL),
        ["", "  "],
    )
    assert made.invited is False
    assert seen["params"]["sendUpdates"] == "none"


def test_the_event_is_created_on_the_primary_calendar(db, monkeypatch):
    """⚠️ קביעה ביומן המשפחתי לא הוכרעה, וחדר הישיבות אינו של המשתמש."""
    seen = _posted(monkeypatch)
    gcal.create(
        db,
        "פגישה",
        datetime(2026, 11, 26, 10, 0, tzinfo=IL),
        datetime(2026, 11, 26, 11, 0, tzinfo=IL),
    )
    assert "calendars/primary/events" in seen["url"]


def test_deleting_an_event_that_had_guests_tells_them(db, monkeypatch):
    """⚠️ ההזמנה אינה נמחקת מהתיבה שלהם, אבל הודעת ביטול כן מגיעה.

    זה הדבר הקרוב ביותר ל"בטל" שאפשר, ועדיף על שתיקה.
    """
    seen: dict = {}

    class Fake:
        status_code = 204

    def capture(url, headers=None, params=None, timeout=None):
        seen.update({"url": url, "params": params or {}})
        return Fake()

    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(gcal.httpx, "delete", capture)
    assert gcal.delete_event(db, "ev-1", invited=True) is True
    assert seen["params"]["sendUpdates"] == "all"

    assert gcal.delete_event(db, "ev-1", invited=False) is True
    assert seen["params"]["sendUpdates"] == "none"


def test_deleting_an_event_that_is_already_gone_is_not_an_error(db, monkeypatch):
    """⚠️ ‏404 ו-410 אינם תקלה: המשתמש מחק אותו בגוגל קלנדר בעצמו."""

    class Gone:
        status_code = 410

    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(gcal.httpx, "delete", lambda *a, **k: Gone())
    assert gcal.delete_event(db, "ev-1") is False


# --- התנגשות ---


def _free_busy(monkeypatch, slots: list[tuple[str, str]]):
    class Fake:
        status_code = 200

        @staticmethod
        def json():
            return {"calendars": {"primary": {"busy": [{"start": s, "end": e} for s, e in slots]}}}

    monkeypatch.setattr(gcal.gauth, "access_token", lambda session: "tok")
    monkeypatch.setattr(
        gcal, "calendars", lambda session: [gcal.Calendar(id="primary", name="ראשי")]
    )
    monkeypatch.setattr(gcal.httpx, "post", lambda *a, **k: Fake())


def test_an_overlap_that_starts_before_the_slot_is_a_conflict(db, monkeypatch):
    """⚠️ **חפיפה ולא הכלה.**

    פגישה 09:00–11:00 מתנגשת עם בקשה ל-10:00–11:00 גם שהיא מתחילה
    לפניה. תנאי שבודק רק הכלה היה מפספס בדיוק את המצב הנפוץ.
    """
    _free_busy(monkeypatch, [("2026-11-26T07:00:00Z", "2026-11-26T09:00:00Z")])
    clash = gcal.conflicts(
        db,
        datetime(2026, 11, 26, 10, 0, tzinfo=IL),
        datetime(2026, 11, 26, 11, 0, tzinfo=IL),
    )
    assert len(clash) == 1


def test_a_meeting_that_ends_exactly_when_the_slot_starts_is_not_a_conflict(db, monkeypatch):
    """פגישה שנגמרת ב-10:00 אינה מתנגשת עם אחת שמתחילה ב-10:00."""
    _free_busy(monkeypatch, [("2026-11-26T07:00:00Z", "2026-11-26T08:00:00Z")])
    clash = gcal.conflicts(
        db,
        datetime(2026, 11, 26, 10, 0, tzinfo=IL),
        datetime(2026, 11, 26, 11, 0, tzinfo=IL),
    )
    assert clash == []


def test_free_busy_returns_no_titles(db, monkeypatch):
    """⚠️ ‏``freeBusy`` מחזיר טווחים בלבד, בלי כותרות ובלי משתתפים.

    זאת הסיבה שבדיקת התנגשות אינה דורשת הרשאה נוספת ואינה חושפת דבר.
    """
    _free_busy(monkeypatch, [("2026-11-26T07:00:00Z", "2026-11-26T08:00:00Z")])
    ranges = gcal.busy(
        db, datetime(2026, 11, 26, tzinfo=IL), datetime(2026, 11, 27, tzinfo=IL)
    )
    assert ranges == [
        (
            datetime(2026, 11, 26, 9, 0, tzinfo=IL),
            datetime(2026, 11, 26, 10, 0, tzinfo=IL),
        )
    ]


def test_the_next_free_slot_skips_what_is_busy(db, monkeypatch):
    _free_busy(monkeypatch, [("2026-11-26T08:00:00Z", "2026-11-26T09:00:00Z")])
    found = gcal.next_free(db, datetime(2026, 11, 26, 10, 0, tzinfo=IL), 60)
    # תפוס 10:00–11:00 בשעון ישראל, ולכן הראשון הפנוי הוא 11:00
    assert found == datetime(2026, 11, 26, 11, 0, tzinfo=IL)


def test_the_next_free_slot_is_never_at_night(db, monkeypatch):
    """⚠️ חלון פנוי בשתיים לפנות בוקר הוא תשובה נכונה וחסרת תועלת."""
    _free_busy(monkeypatch, [])
    found = gcal.next_free(db, datetime(2026, 11, 26, 23, 0, tzinfo=IL), 60)
    assert found is not None
    assert found.hour >= gcal.DAY_START
    assert found.date() > date(2026, 11, 26)


def test_the_next_free_slot_is_never_on_saturday(db, monkeypatch):
    """⚠️ הצעה לקבוע בשבת אינה הצעה."""
    _free_busy(monkeypatch, [])
    # 28.11.2026 הוא שבת
    found = gcal.next_free(db, datetime(2026, 11, 28, 9, 0, tzinfo=IL), 60)
    assert found is not None
    assert found.weekday() != gcal.SATURDAY


def test_the_next_free_slot_is_rounded_to_a_quarter_hour(db, monkeypatch):
    """לא להציע "10:07"."""
    _free_busy(monkeypatch, [])
    found = gcal.next_free(db, datetime(2026, 11, 26, 10, 7, tzinfo=IL), 60)
    assert found is not None
    assert found.minute % gcal.SLOT_MINUTES == 0
