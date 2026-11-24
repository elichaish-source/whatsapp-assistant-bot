"""בדיקות לקריאת מיילים דרך הבוט (שלב 4-2).

אין כאן אף פנייה לגוגל ואף קריאה למודל: שכבת השירות מוחלפת ב-monkeypatch,
וזה בדיוק מה שההפרדה בין ``app/gmail.py`` ל-``app/bot/emails.py`` קנתה.

⚠️ מה שהבדיקות **לא** יכולות לכסות, ולכן נבדק מול הודעות אמיתיות אחרי
הפריסה: בחירת הפעולה על ידי המודל, ושהסכימה החדשה עוברת את ה-API.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import gauth, gmail
from app.bot import actions
from app.bot.intent import Intent
from app.models import BotMessage, Client, Task

IL = ZoneInfo("Asia/Jerusalem")

TOKENS = {
    "refresh_token": "refresh-1",
    "access_token": "access-1",
    "expires_in": 3600,
    "scope": " ".join(gauth.SCOPES),
}


@pytest.fixture
def connected(db, monkeypatch):
    """חיבור גוגל תקף במסד, בלי אף פנייה לגוגל."""
    monkeypatch.setattr(gauth, "fetch_email", lambda token: "me@gmail.com")
    cred = gauth.save_tokens(db, dict(TOKENS))
    yield cred
    db.rollback()


def mail(number: int, sender: str = "דני כהן", address: str = "dani@example.com"):
    """⚠️ מייל של **היום**, ולא תאריך קבוע.

    הרשימה מציגה תאריך למייל שאינו מהיום, ולכן בדיקה עם תאריך קבוע
    נשברת מעצמה למחרת. זה קרה ב-23.11.2026 על בדיקה שנכתבה ב-19.11.
    """
    today = datetime.now(tz=IL).replace(hour=9, minute=number, second=0, microsecond=0)
    return gmail.EmailSummary(
        id=f"gid-{number}",
        thread_id=f"th-{number}",
        sender_name=sender,
        sender_email=address,
        subject=f"נושא {number}",
        snippet=f"פתיחה {number}",
        received_at=today,
    )


def full(number: int = 1, body: str = "שלום, מצרף את החוזה.", **extra):
    base = dict(
        id=f"gid-{number}",
        thread_id=f"th-{number}",
        sender_name="דני כהן",
        sender_email="dani@example.com",
        to="me@gmail.com",
        subject=f"נושא {number}",
        received_at=datetime(2026, 11, 19, 9, number, tzinfo=IL),
        body=body,
    )
    base.update(extra)
    return gmail.EmailFull(**base)


def no_filter(monkeypatch):
    """הסינון מעביר הכול. מי שבודק את הסינון עצמו הוא test_gmail.py."""
    monkeypatch.setattr(
        gmail,
        "triage",
        lambda found, client_emails=None: [
            gmail.Triaged(email=item, relevant=True, line=f"תיאור {index}")
            for index, item in enumerate(found, start=1)
        ],
    )


# --- בלי חיבור ---


def test_without_a_google_connection_the_bot_says_so(db):
    outcome = actions.execute(db, Intent(action="list_emails"))
    assert "לא מחובר" in outcome.reply
    assert outcome.listed_email_ids == []


def test_a_revoked_connection_asks_to_reconnect(db, connected):
    connected.status = "disconnected"
    db.commit()
    assert "לחבר מחדש" in actions.execute(db, Intent(action="list_emails")).reply


def test_a_network_error_does_not_void_the_existing_numbering(db, connected, monkeypatch):
    """⚠️ אם הרשת נפלה, הרשימה מלפני רגע עדיין תקפה.

    ``clear_list`` כאן היה שובר "תראה לי את 2" בכל פעם שגוגל מגמגמת.
    """
    monkeypatch.setattr(
        gmail, "list_inbox", lambda *a, **k: (_ for _ in ()).throw(gmail.GmailError("רשת"))
    )
    outcome = actions.execute(db, Intent(action="list_emails"))
    assert "לא הצלחתי להגיע" in outcome.reply
    assert outcome.clear_list is False


def test_a_disconnect_during_the_call_is_reported_as_a_disconnect(db, connected, monkeypatch):
    monkeypatch.setattr(
        gmail,
        "list_inbox",
        lambda *a, **k: (_ for _ in ()).throw(gauth.GoogleDisconnected("invalid_grant")),
    )
    assert "לחבר מחדש" in actions.execute(db, Intent(action="list_emails")).reply


# --- "מה נכנס היום" ---


def test_the_summary_returns_a_numbered_list(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1), mail(2)])
    no_filter(monkeypatch)
    outcome = actions.execute(db, Intent(action="list_emails"))
    assert "נכנסו היום 2 מיילים" in outcome.reply
    assert "1. דני כהן · 09:01" in outcome.reply
    assert "2. דני כהן · 09:02" in outcome.reply
    assert "תיאור 1" in outcome.reply
    assert outcome.listed_email_ids == ["gid-1", "gid-2"]


def test_the_hint_points_at_a_number_that_exists(db, connected, monkeypatch):
    """⚠️ נראה מול התיבה האמיתית: רשימה של מייל אחד הפנתה ל"תראה לי את 2"."""
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1)])
    no_filter(monkeypatch)
    one = actions.execute(db, Intent(action="list_emails")).reply
    assert 'תראה לי את 1' in one
    assert 'תראה לי את 2' not in one

    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1), mail(2)])
    two = actions.execute(db, Intent(action="list_emails")).reply
    assert 'תראה לי את 2' in two


def test_the_search_hint_also_points_at_a_number_that_exists(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "search", lambda *a, **k: [mail(1)])
    reply = actions.execute(db, Intent(action="search_emails", email_query="דני")).reply
    assert 'תראה לי את 1' in reply


def test_a_mail_from_today_shows_only_the_time(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(7)])
    no_filter(monkeypatch)
    assert "· 09:07" in actions.execute(db, Intent(action="list_emails")).reply


def test_a_mail_from_another_day_shows_the_date(db, connected, monkeypatch):
    """⚠️ בסיכום שבועי "20:36" ו-"12:29" נראו כאילו מאותו יום.

    נראה בתשובה אמיתית ב-19.11.2026.
    """
    earlier = gmail.EmailSummary(
        id="gid-old",
        thread_id="th-old",
        sender_name="דני כהן",
        sender_email="dani@example.com",
        subject="נושא",
        snippet="פתיחה",
        received_at=datetime.now(tz=IL) - timedelta(days=3),
    )
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [earlier])
    no_filter(monkeypatch)
    reply = actions.execute(db, Intent(action="list_emails", email_scope="week")).reply
    assert f"· {earlier.received_at:%d/%m %H:%M}" in reply


def test_an_empty_inbox_says_so(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [])
    outcome = actions.execute(db, Intent(action="list_emails"))
    assert "אין מיילים חדשים היום" in outcome.reply
    assert outcome.listed_email_ids == []


def test_the_week_scope_changes_the_wording_and_the_query(db, connected, monkeypatch):
    seen: dict = {}

    def capture(db_, scope, show_all=False):
        seen["scope"] = scope
        return []

    monkeypatch.setattr(gmail, "list_inbox", capture)
    outcome = actions.execute(db, Intent(action="list_emails", email_scope="week"))
    assert seen["scope"] == "week"
    assert "השבוע" in outcome.reply


def test_the_default_scope_is_today(db, connected, monkeypatch):
    seen: dict = {}

    def capture(db_, scope, show_all=False):
        seen["scope"] = scope
        return []

    monkeypatch.setattr(gmail, "list_inbox", capture)
    actions.execute(db, Intent(action="list_emails"))
    assert seen["scope"] == "today"


def test_filtered_mail_is_counted_and_not_hidden_silently(db, connected, monkeypatch):
    """ההכרעה של המשתמש: מה שסונן מוצג כמונה בשורה אחת."""
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1), mail(2), mail(3)])
    monkeypatch.setattr(
        gmail,
        "triage",
        lambda found, client_emails=None: [
            gmail.Triaged(email=item, relevant=index == 1, line="שורה")
            for index, item in enumerate(found, start=1)
        ],
    )
    outcome = actions.execute(db, Intent(action="list_emails"))
    assert "(ועוד 2 סוננו)" in outcome.reply
    # רק מה שעבר נכנס למספור, אחרת "תראה לי את 2" היה פותח פרסומת
    assert outcome.listed_email_ids == ["gid-1"]


def reject_all(monkeypatch):
    monkeypatch.setattr(
        gmail,
        "triage",
        lambda found, client_emails=None: [
            gmail.Triaged(email=item, relevant=False, line="פרסומת") for item in found
        ],
    )


def test_when_nothing_passes_the_filter_the_count_is_still_reported(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1), mail(2)])
    reject_all(monkeypatch)
    outcome = actions.execute(db, Intent(action="list_emails"))
    assert "נכנסו היום 2 מיילים" in outcome.reply
    assert "לא נראה דורש תשומת לב" in outcome.reply


# --- "תראה לי את כולם": הדרך לראות את מה שסוננו ---


def test_nothing_passed_tells_the_user_how_to_see_them(db, connected, monkeypatch):
    """⚠️ הפער שהמשתמש גילה בשימוש הראשון, 19.11.2026.

    ההכרעה שהוא בחר אמרה "אתה יודע שהיה שם משהו **ויכול לבקש לראות**",
    והיכולת לבקש לא נבנתה: הוא כתב "תראה לי את כולם בכל זאת" וקיבל שוב
    את אותה תשובה בדיוק.
    """
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1)])
    reject_all(monkeypatch)
    assert 'תראה לי את כולם' in actions.execute(db, Intent(action="list_emails")).reply


def test_the_counter_line_also_tells_the_user_how_to_see_them(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1), mail(2)])
    monkeypatch.setattr(
        gmail,
        "triage",
        lambda found, client_emails=None: [
            gmail.Triaged(email=item, relevant=index == 1, line="שורה")
            for index, item in enumerate(found, start=1)
        ],
    )
    reply = actions.execute(db, Intent(action="list_emails")).reply
    assert "(ועוד 1 סוננו)" in reply
    assert 'תראה לי את כולם' in reply


def test_show_all_skips_the_filter_entirely(db, connected, monkeypatch):
    """הסינון הוא שירות, לא שוער. ⚠️ ואינו נקרא בכלל — גם חיסכון."""
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1), mail(2), mail(3)])
    monkeypatch.setattr(gmail, "triage", lambda *a, **k: pytest.fail("אין לסנן כאן"))
    outcome = actions.execute(db, Intent(action="list_emails", email_show_all=True))
    assert "נכנסו היום 3 מיילים בדואר הנכנס, הכול" in outcome.reply
    assert outcome.listed_email_ids == ["gid-1", "gid-2", "gid-3"]


def test_show_all_is_passed_down_to_the_query(db, connected, monkeypatch):
    """⚠️ הלב של התיקון: השכבות נופלות ב-gmail ולא רק הסינון ב-bot."""
    seen: dict = {}

    def capture(db_, scope, show_all=False):
        seen["show_all"] = show_all
        return []

    monkeypatch.setattr(gmail, "list_inbox", capture)
    actions.execute(db, Intent(action="list_emails", email_show_all=True))
    assert seen["show_all"] is True
    actions.execute(db, Intent(action="list_emails"))
    assert seen["show_all"] is False


def test_a_long_list_is_split_into_several_messages(db, connected, monkeypatch):
    """⚠️ 29 מיילים בשבוע מול התיבה האמיתית, ווואטסאפ חותכת ב-4096.

    בלי הפיצול סוף הרשימה היה נאבד בשקט, יחד עם המספרים הגבוהים.
    """
    # נושא באורך של פרסומת אמיתית, כי שם ההבדל נמצא: 45 מיילים עם נושא
    # קצר נכנסים בהודעה אחת, ועם נושא אמיתי הם חורגים
    many = [
        gmail.EmailSummary(
            id=f"gid-{index}",
            thread_id=f"th-{index}",
            sender_name=f"שולח מספר {index}",
            sender_email=f"s{index}@example.com",
            subject="נושא ארוך כמו של פרסומת אמיתית, עם הבטחה גדולה ועוד פסיק " * 2,
            snippet="",
            received_at=datetime(2026, 11, 19, 9, 0, tzinfo=IL),
        )
        for index in range(1, 46)
    ]
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: many)
    outcome = actions.execute(db, Intent(action="list_emails", email_show_all=True))
    assert len(outcome.parts) > 1
    # ⚠️ והמספור שלם, גם למיילים שיצאו בהודעה השנייה
    assert len(outcome.listed_email_ids) == 45
    assert outcome.listed_email_ids[-1] == "gid-45"


def test_show_all_numbers_everything_so_a_filtered_mail_can_be_opened(db, connected, monkeypatch):
    """אחרי "תראה לי את כולם", "תראה לי את 3" חייב להגיע למייל שסונן."""
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1), mail(2), mail(3)])
    actions.execute(db, Intent(action="list_emails", email_show_all=True))
    listed(db, ["gid-1", "gid-2", "gid-3"])
    seen: dict = {}

    def capture(db_, message_id):
        seen["id"] = message_id
        return full(3)

    monkeypatch.setattr(gmail, "fetch_full", capture)
    actions.execute(db, Intent(action="show_email", task_number=3))
    assert seen["id"] == "gid-3"


def test_show_all_on_an_empty_inbox_still_says_there_is_nothing(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [])
    outcome = actions.execute(db, Intent(action="list_emails", email_show_all=True))
    assert "אין מיילים חדשים היום" in outcome.reply


# --- פעולה על מייל שטרם נבנתה ---


def test_an_email_action_that_is_not_built_says_so_plainly(db, connected):
    """⚠️ נראה בשימוש אמיתי ב-22.11.2026.

    "זרוק אותו לארכיון" קיבל `unknown`, והתשובה הייתה "לא הבנתי. אפשר
    לכתוב למשל תזכיר לי מחר ב-10 להתקשר לדני" — הפניה למשימות במקום
    לומר שהיכולת עוד לא קיימת.
    """
    reply = actions.execute(db, Intent(action="email_not_yet")).reply
    assert "ארכוב" in reply and "עוד לא נבנו" in reply
    # ואומר מה כן אפשר, כדי שהמשתמש לא ינחש
    assert "מה נכנס היום" in reply
    assert "תזכיר לי" not in reply


def test_the_not_yet_answer_does_not_promise_a_date(db, connected):
    """טרם הוכרע אם 4-3 ו-4-4 בבוט או במסך, ואין להבטיח."""
    reply = actions.execute(db, Intent(action="email_not_yet")).reply
    for word in ("בקרוב", "בהמשך", "בשלב הבא", "נבנה בימים"):
        assert word not in reply, word


def test_the_not_yet_answer_changes_nothing(db, connected):
    outcome = actions.execute(db, Intent(action="email_not_yet"))
    assert outcome.listed_email_ids == []
    assert outcome.clear_list is False
    assert outcome.task_id is None
    assert outcome.pending is None


# --- עברית: "מייל אחד" ולא "1 מיילים" ---


def test_a_single_mail_is_counted_in_hebrew(db, connected, monkeypatch):
    """נראה בתשובה אמיתית: "נכנסו היום 1 מיילים"."""
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1)])
    no_filter(monkeypatch)
    reply = actions.execute(db, Intent(action="list_emails")).reply
    assert "נכנס היום מייל אחד" in reply
    assert "1 מיילים" not in reply


def test_a_single_filtered_mail_is_counted_in_hebrew(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1)])
    reject_all(monkeypatch)
    reply = actions.execute(db, Intent(action="list_emails")).reply
    assert "נכנס היום מייל אחד, והוא לא נראה דורש תשומת לב" in reply


def test_a_single_search_hit_is_counted_in_hebrew(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "search", lambda *a, **k: [mail(1)])
    reply = actions.execute(db, Intent(action="search_emails", email_query="דני")).reply
    assert 'מצאתי מייל אחד על "דני"' in reply


def test_the_client_addresses_are_handed_to_the_filter(db, connected, monkeypatch):
    """"מייל משולח שרשום בכרטיס לקוח עובר תמיד" — הכתובות מגיעות לסינון."""
    db.add(Client(name="דני", email="dani@example.com"))
    db.commit()
    seen: dict = {}

    def capture(found, client_emails=None):
        seen["addresses"] = client_emails
        return [gmail.Triaged(email=item, relevant=True, line="שורה") for item in found]

    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1)])
    monkeypatch.setattr(gmail, "triage", capture)
    actions.execute(db, Intent(action="list_emails"))
    assert "dani@example.com" in seen["addresses"]


def test_the_summary_voids_the_task_numbering(db, connected, monkeypatch):
    """⚠️ אחרת "סיימתי 2" אחרי רשימת מיילים היה סוגר משימה אחרת לגמרי."""
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1)])
    no_filter(monkeypatch)
    assert actions.execute(db, Intent(action="list_emails")).clear_list is True


# --- חיפוש ---


def test_search_runs_on_the_whole_mailbox_and_numbers_the_results(db, connected, monkeypatch):
    seen: dict = {}

    def capture(db_, text, limit=gmail.SEARCH_LIMIT):
        seen["text"] = text
        return [mail(1), mail(2)]

    monkeypatch.setattr(gmail, "search", capture)
    outcome = actions.execute(db, Intent(action="search_emails", email_query="דני"))
    assert seen["text"] == "דני"
    assert "מצאתי 2 מיילים" in outcome.reply
    # בחיפוש הנושא הוא מה שמאפשר לזהות את המייל הנכון
    assert "נושא 1" in outcome.reply
    assert outcome.listed_email_ids == ["gid-1", "gid-2"]


def test_search_does_not_call_the_filter(db, connected, monkeypatch):
    """⚠️ בחיפוש המשתמש כבר אמר מה הוא מחפש. סינון היה מסתיר בדיוק את זה."""
    monkeypatch.setattr(gmail, "search", lambda *a, **k: [mail(1)])
    monkeypatch.setattr(
        gmail, "triage", lambda *a, **k: pytest.fail("אין לסנן תוצאות חיפוש")
    )
    assert "מצאתי מייל אחד" in actions.execute(
        db, Intent(action="search_emails", email_query="דני")
    ).reply


def test_search_with_nothing_found_says_so(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "search", lambda *a, **k: [])
    outcome = actions.execute(db, Intent(action="search_emails", email_query="אין כזה"))
    assert 'לא מצאתי מייל שמתאים ל"אין כזה"' in outcome.reply


def test_search_without_a_query_asks(db, connected):
    assert "מה לחפש" in actions.execute(db, Intent(action="search_emails")).reply


# --- מייל מלא ---


def listed(db, ids: list[str]) -> BotMessage:
    """רושם ביומן רשימה שהבוט שלח, כדי שהמספור יהיה למה להתייחס."""
    row = BotMessage(
        wa_message_id=f"wa-{len(ids)}-{ids[0]}",
        body="מה נכנס היום",
        intent="list_emails",
        listed_email_ids=",".join(ids),
    )
    db.add(row)
    db.commit()
    return row


def test_show_email_resolves_the_number_from_the_last_list(db, connected, monkeypatch):
    listed(db, ["gid-7", "gid-8"])
    seen: dict = {}

    def capture(db_, message_id):
        seen["id"] = message_id
        return full(8)

    monkeypatch.setattr(gmail, "fetch_full", capture)
    outcome = actions.execute(db, Intent(action="show_email", task_number=2))
    assert seen["id"] == "gid-8"
    assert "מאת: דני כהן" in outcome.reply
    assert "נושא: נושא 8" in outcome.reply


def test_show_email_uses_the_newest_list_when_there_are_several(db, connected, monkeypatch):
    listed(db, ["old-1"])
    listed(db, ["new-1"])
    seen: dict = {}

    def capture(db_, message_id):
        seen["id"] = message_id
        return full()

    monkeypatch.setattr(gmail, "fetch_full", capture)
    actions.execute(db, Intent(action="show_email", task_number=1))
    assert seen["id"] == "new-1"


def test_a_number_outside_the_list_is_refused(db, connected, monkeypatch):
    listed(db, ["gid-1"])
    outcome = actions.execute(db, Intent(action="show_email", task_number=5))
    assert "לא מצאתי מייל במספר הזה" in outcome.reply


def test_a_number_without_any_list_is_refused(db, connected):
    outcome = actions.execute(db, Intent(action="show_email", task_number=2))
    assert "לא מצאתי מייל במספר הזה" in outcome.reply


def test_show_email_does_not_void_the_numbering(db, connected, monkeypatch):
    """אחרי "תראה לי את 2" צריך שגם "תראה לי את 3" יעבוד."""
    listed(db, ["gid-1", "gid-2"])
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full())
    outcome = actions.execute(db, Intent(action="show_email", task_number=1))
    assert outcome.listed_email_ids == []
    assert outcome.clear_list is False


def summarized(monkeypatch, text: str = "מבקש חתימה על החוזה עד חמישי."):
    monkeypatch.setattr(gmail, "summarize", lambda mail: text)


def test_show_email_returns_a_summary_and_not_the_body(db, connected, monkeypatch):
    """⚠️ ההכרעה המרכזית של 23.11.2026: הבוט אינו מדפיס את מלל המייל.

    הטריאז' עבר למסך, ותפקיד הבוט כאן הוא לומר **מה יש** במייל.
    """
    secret = "שורת גוף שאינה אמורה לצאת לוואטסאפ בשום מצב"
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(body=secret))
    summarized(monkeypatch)
    listed(db, ["gid-1"])
    reply = actions.execute(db, Intent(action="show_email", task_number=1)).reply
    assert "מבקש חתימה על החוזה עד חמישי." in reply
    assert secret not in reply


def test_the_header_is_built_in_code_and_not_by_the_model(db, connected, monkeypatch):
    """⚠️ שולח, נושא, תאריך וקבצים אינם עוברים דרך המודל.

    לכן טקסט שבתוך המייל אינו יכול לשנות אותם.
    """
    monkeypatch.setattr(
        gmail, "fetch_full", lambda db_, mid: full(4, attachments=["חוזה.pdf"])
    )
    summarized(monkeypatch, "תקציר")
    listed(db, ["gid-1"])
    reply = actions.execute(db, Intent(action="show_email", task_number=1)).reply
    assert "מאת: דני כהן" in reply
    assert "נושא: נושא 4" in reply
    assert "מצורף: חוזה.pdf" in reply


def test_a_failed_summary_shows_a_bounded_opening_and_says_so(db, connected, monkeypatch):
    """⚠️ נפילה מבוקרת: שורות פתיחה חסומות באורך, ולא המייל המלא.

    להציג כלום היה גרוע יותר, ולהציג הכול היה חזרה להתנהגות שבוטלה.
    """
    long_body = "א" * 3000
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(body=long_body))

    def boom(mail):
        raise gmail.SummaryFailed("אין מפתח")

    monkeypatch.setattr(gmail, "summarize", boom)
    listed(db, ["gid-1"])
    reply = actions.execute(db, Intent(action="show_email", task_number=1)).reply
    assert "לא הצלחתי לתקצר" in reply
    # ⚠️ הגוף חסום, ולא יוצא במלואו
    assert reply.count("א") <= gmail.FALLBACK_CHARS
    assert long_body not in reply


def test_an_empty_mail_is_not_sent_to_the_model(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(body="   "))
    monkeypatch.setattr(gmail, "summarize", lambda mail: pytest.fail("אין מה לתקצר"))
    listed(db, ["gid-1"])
    assert "(המייל ריק)" in actions.execute(
        db, Intent(action="show_email", task_number=1)
    ).reply


def test_a_summarised_mail_fits_one_whatsapp_message(db, connected, monkeypatch):
    """תקציר של שתיים-שלוש שורות לא אמור להתפצל יותר."""
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(body="ב" * 20000))
    summarized(monkeypatch)
    listed(db, ["gid-1"])
    assert actions.execute(db, Intent(action="show_email", task_number=1)).parts == []


def test_attachment_names_are_shown_without_downloading_them(db, connected, monkeypatch):
    monkeypatch.setattr(
        gmail, "fetch_full", lambda db_, mid: full(attachments=["חוזה.pdf", "נספח.docx"])
    )
    listed(db, ["gid-1"])
    outcome = actions.execute(db, Intent(action="show_email", task_number=1))
    assert "מצורף: חוזה.pdf, נספח.docx" in outcome.reply


def test_an_empty_mail_body_is_reported(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(body="   "))
    listed(db, ["gid-1"])
    assert "(המייל ריק)" in actions.execute(
        db, Intent(action="show_email", task_number=1)
    ).reply


def test_a_long_mail_no_longer_floods_whatsapp(db, connected, monkeypatch):
    """⚠️ היה מתפצל לכמה הודעות, ומ-23.11.2026 הוא מתקצר במקום.

    הפיצול עצמו נשאר ונחוץ — אבל לרשימות, לא למייל בודד.
    """
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(body="א" * 9000))
    summarized(monkeypatch)
    listed(db, ["gid-1"])
    outcome = actions.execute(db, Intent(action="show_email", task_number=1))
    assert outcome.parts == []
    assert len(outcome.reply) < gmail.PART_CHARS


def test_a_short_mail_stays_one_message(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full())
    listed(db, ["gid-1"])
    assert actions.execute(db, Intent(action="show_email", task_number=1)).parts == []


def test_show_email_by_words_shows_the_only_match(db, connected, monkeypatch):
    monkeypatch.setattr(gmail, "search", lambda *a, **k: [mail(4)])
    monkeypatch.setattr(gmail, "fetch_full", lambda db_, mid: full(4))
    outcome = actions.execute(db, Intent(action="show_email", email_query="דני"))
    assert "נושא: נושא 4" in outcome.reply


def test_show_email_by_words_does_not_choose_between_several(db, connected, monkeypatch):
    """אותו כלל של המשימות: הבוט מציג ואינו בוחר לבד."""
    monkeypatch.setattr(gmail, "search", lambda *a, **k: [mail(1), mail(2)])
    monkeypatch.setattr(gmail, "fetch_full", lambda *a, **k: pytest.fail("אין לבחור לבד"))
    outcome = actions.execute(db, Intent(action="show_email", email_query="דני"))
    assert "לאיזה התכוונת" in outcome.reply
    assert outcome.listed_email_ids == ["gid-1", "gid-2"]


def test_show_email_without_a_number_or_words_asks(db, connected):
    assert "איזה מייל להציג" in actions.execute(db, Intent(action="show_email")).reply


# --- המספור נשמר ביומן ---


def test_the_numbering_is_written_to_the_message_log(db, connected, monkeypatch, sent):
    """המספור חייב להגיע למסד, אחרת "תראה לי את 2" לא ימצא אותו."""
    from app.routers import bot as bot_router

    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1), mail(2)])
    no_filter(monkeypatch)
    monkeypatch.setattr(
        bot_router,
        "extract",
        lambda *a, **k: _result(Intent(action="list_emails")),
    )
    row = BotMessage(wa_message_id="wa-log-1", body="מה נכנס היום")
    db.add(row)
    db.commit()

    bot_router.handle_message("wa-log-1", "מה נכנס היום")
    db.expire_all()
    saved = db.scalars(select(BotMessage).where(BotMessage.wa_message_id == "wa-log-1")).one()
    assert saved.listed_email_ids == "gid-1,gid-2"
    # ‏⚠️ ובמקביל מספור המשימות התאפס
    assert saved.listed_task_ids == ""


def test_a_long_list_goes_out_as_several_whatsapp_messages(db, connected, monkeypatch, sent):
    """⚠️ מקצה לקצה: ``Outcome.parts`` הופך לכמה קריאות ל-``send_text``.

    הבדיקה הזאת בדקה פעם מייל ארוך; מ-23.11.2026 מייל בודד מתקצר, אבל
    **הפיצול עצמו עדיין נחוץ לרשימות** — 25 מיילים חרגו מתקרת וואטסאפ
    מול התיבה האמיתית. לכן הכיסוי עבר לכאן ולא נמחק.
    """
    from app.routers import bot as bot_router

    many = [
        gmail.EmailSummary(
            id=f"gid-{index}",
            thread_id=f"th-{index}",
            sender_name=f"שולח מספר {index}",
            sender_email=f"s{index}@example.com",
            subject="נושא ארוך כמו של פרסומת אמיתית, עם הבטחה גדולה ועוד פסיק " * 2,
            snippet="",
            received_at=datetime.now(tz=IL),
        )
        for index in range(1, 46)
    ]
    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: many)
    monkeypatch.setattr(
        bot_router,
        "extract",
        lambda *a, **k: _result(Intent(action="list_emails", email_show_all=True)),
    )
    row = BotMessage(wa_message_id="wa-log-2", body="תראה לי את כולם")
    db.add(row)
    db.commit()

    sent.clear()
    bot_router.handle_message("wa-log-2", "תראה לי את כולם")
    assert len(sent) > 1


def test_nothing_about_the_mail_content_is_stored(db, connected, monkeypatch):
    """⚠️ ההבטחה המרכזית של השלב: במסד נשמרים מזהים, לא תוכן.

    אם הבדיקה הזאת נשברת, צריך לעדכן את ``frontend/public/privacy.html``
    ואת ``terms.html`` — הם מוגשים ב-/privacy וב-/terms, וגוגל מצביעה
    עליהם.
    """
    from app.routers import bot as bot_router

    monkeypatch.setattr(gmail, "list_inbox", lambda *a, **k: [mail(1)])
    no_filter(monkeypatch)
    monkeypatch.setattr(
        bot_router, "extract", lambda *a, **k: _result(Intent(action="list_emails"))
    )
    row = BotMessage(wa_message_id="wa-log-3", body="מה נכנס היום")
    db.add(row)
    db.commit()
    bot_router.handle_message("wa-log-3", "מה נכנס היום")

    db.expire_all()
    saved = db.scalars(select(BotMessage).where(BotMessage.wa_message_id == "wa-log-3")).one()
    # רק המזהה. הנושא שהגיע מגוגל אינו בשום עמודה
    assert saved.listed_email_ids == "gid-1"
    columns = " ".join(
        str(getattr(saved, name) or "") for name in ("body", "reply", "query_sql", "undo_json")
    )
    assert "נושא 1" not in columns
    # בטבלת המשימות לא נוצר דבר: קריאה אינה יוצרת משימה בשלב הזה
    assert db.scalars(select(Task)).all() == []


def _result(intent: Intent):
    from app.bot.intent import IntentResult

    return IntentResult(intent=intent)
