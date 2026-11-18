"""פריסה 4-1: החיבור לגוגל.

שום בדיקה כאן לא פונה לגוגל. כל קריאת רשת מוחלפת, ומה שנבדק הוא מה
שהקוד שלנו עושה עם התשובה — במיוחד השלושה שלא ניתן לראות בעין: שהטוקן
באמת מוצפן במסד, שההודעה על ניתוק יוצאת פעם אחת בלבד, ושתקלת רשת אינה
מסומנת כניתוק.
"""

import time
from datetime import timedelta

import pytest
from sqlalchemy import text

from app import crypto, gauth
from app.auth import now
from app.bot import reminders
from app.config import get_settings
from app.db import SessionLocal
from app.models import GoogleCredential

TOKENS = {
    "access_token": "access-1",
    "refresh_token": "refresh-1",
    "expires_in": 3599,
    "scope": " ".join(gauth.SCOPES),
}


@pytest.fixture(autouse=True)
def reset_retry():
    """‏_retry_at חי בזיכרון המודול ועובר בין בדיקות אם לא מאפסים."""
    gauth._retry_at = None
    yield
    gauth._retry_at = None


@pytest.fixture
def no_profile(monkeypatch):
    """כתובת התיבה נקראת מגוגל בכל חיבור. כאן מחזירים ערך קבוע."""
    monkeypatch.setattr(gauth, "fetch_email", lambda token: "me@gmail.com")


@pytest.fixture
def connected(db, no_profile):
    cred = gauth.save_tokens(db, dict(TOKENS))
    yield cred
    db.rollback()


# --- הצפנה ---


def test_encrypt_round_trip():
    assert crypto.decrypt(crypto.encrypt("סוד")) == "סוד"
    # ריק נשאר ריק, כדי ש"אין טוקן" לא ייראה כמו ערך מוצפן
    assert crypto.encrypt("") == ""
    assert crypto.decrypt("") == ""


def test_encrypt_is_not_reversible_without_the_key(monkeypatch):
    blob = crypto.encrypt("סוד")
    monkeypatch.setattr(get_settings(), "google_token_key", "מפתח-אחר")
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(blob)


def test_token_is_encrypted_in_the_database(db, connected):
    """⚠️ הבדיקה החשובה כאן: קריאה ישירה מהמסד, לא דרך המודל."""
    with SessionLocal() as raw:
        stored = raw.execute(text("SELECT refresh_token_enc FROM google_credentials")).scalar_one()
    assert "refresh-1" not in stored
    assert crypto.decrypt(stored) == "refresh-1"


# --- ה-state ---


def test_state_round_trip():
    assert gauth.valid_state(gauth.make_state())


def test_tampered_or_old_state_is_rejected():
    assert not gauth.valid_state("")
    assert not gauth.valid_state("לא-מספר.abc")
    # ⚠️ זיוף שאינו ASCII: לפני התיקון זה הפיל את הנתיב ב-TypeError
    assert not gauth.valid_state(f"{int(time.time())}.{'א' * 32}")
    stamp, _, sig = gauth.make_state().partition(".")
    assert not gauth.valid_state(f"{stamp}.{'0' * len(sig)}")
    old = str(int(time.time()) - (gauth.STATE_MINUTES * 60 + 5))
    assert not gauth.valid_state(f"{old}.{gauth._sign(old)}")


# --- כתובת מסך האישור ---


def test_auth_url_asks_for_exactly_the_decided_scopes():
    url = gauth.auth_url()
    assert "gmail.modify" in url
    assert "calendar.events" in url and "calendar.readonly" in url
    # ⚠️ ההרשאה שמוחקת לצמיתות. אסור שתופיע כאן לעולם
    assert "mail.google.com" not in url
    assert "gmail.send" not in url


def test_auth_url_asks_for_a_refresh_token():
    url = gauth.auth_url()
    # בלי שני אלה החיבור שורד שעה אחת ואז מת
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "redirect_uri=https%3A%2F%2Ftest.example.com%2Fapi%2Fgoogle%2Fcallback" in url


# --- הנתיבים ---


def test_status_requires_login(anon):
    assert anon.get("/api/google/status").status_code == 401
    assert anon.post("/api/google/connect").status_code == 401
    assert anon.post("/api/google/disconnect").status_code == 401


def test_status_when_not_connected(client):
    body = client.get("/api/google/status").json()
    assert body["configured"] is True
    assert body["connected"] is False
    assert body["status"] == ""


def test_connect_returns_the_google_url(client):
    assert client.post("/api/google/connect").json()["url"].startswith(gauth.AUTH_URL)


def test_connect_without_keys_says_so(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "")
    assert client.post("/api/google/connect").status_code == 503
    assert client.get("/api/google/status").json()["configured"] is False


def test_callback_stores_the_connection(client, monkeypatch, no_profile):
    monkeypatch.setattr(gauth, "exchange_code", lambda code: dict(TOKENS))
    resp = client.get(
        "/api/google/callback",
        params={"code": "abc", "state": gauth.make_state()},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings?google=ok"

    body = client.get("/api/google/status").json()
    assert body["connected"] is True
    assert body["email"] == "me@gmail.com"
    assert body["missing_scopes"] == []


def test_callback_rejects_a_forged_state(client, monkeypatch):
    called = []
    monkeypatch.setattr(gauth, "exchange_code", lambda code: called.append(code) or dict(TOKENS))
    resp = client.get(
        "/api/google/callback",
        params={"code": "abc", "state": f"{int(time.time())}.{'0' * 32}"},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/settings?google=state"
    # ⚠️ העיקר: הקוד לא הוחלף בטוקן
    assert called == []
    assert client.get("/api/google/status").json()["connected"] is False


def test_callback_without_login_does_not_connect(anon, monkeypatch):
    monkeypatch.setattr(gauth, "exchange_code", lambda code: dict(TOKENS))
    resp = anon.get(
        "/api/google/callback",
        params={"code": "abc", "state": gauth.make_state()},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/settings?google=auth"


def test_callback_when_the_user_pressed_cancel(client):
    resp = client.get(
        "/api/google/callback", params={"error": "access_denied"}, follow_redirects=False
    )
    assert resp.headers["location"] == "/settings?google=denied"


def test_callback_reports_partly_granted_scopes(client, monkeypatch, no_profile):
    partial = dict(TOKENS, scope="https://www.googleapis.com/auth/gmail.modify")
    monkeypatch.setattr(gauth, "exchange_code", lambda code: partial)
    resp = client.get(
        "/api/google/callback",
        params={"code": "abc", "state": gauth.make_state()},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/settings?google=partial"
    missing = client.get("/api/google/status").json()["missing_scopes"]
    assert len(missing) == 2 and all("calendar" in s for s in missing)


def test_disconnect_removes_the_row(client, db, connected, monkeypatch):
    monkeypatch.setattr(gauth.httpx, "post", lambda *a, **k: None)
    assert client.post("/api/google/disconnect").json() == {"ok": True}
    assert gauth.get_credential(db) is None


# --- טוקן גישה ורענון ---


def test_access_token_uses_the_stored_one_while_it_is_valid(db, connected, monkeypatch):
    monkeypatch.setattr(
        gauth, "_post_token", lambda data: pytest.fail("לא היה צריך לרענן")
    )
    assert gauth.access_token(db) == "access-1"


def test_access_token_refreshes_when_expired(db, connected, monkeypatch):
    connected.access_expires_at = now() - timedelta(minutes=1)
    db.commit()
    monkeypatch.setattr(
        gauth, "_post_token", lambda data: {"access_token": "access-2", "expires_in": 3599}
    )
    assert gauth.access_token(db) == "access-2"
    db.refresh(connected)
    assert crypto.decrypt(connected.access_token_enc) == "access-2"


# --- הבדיקה התקופתית ---


def test_check_waits_for_the_interval(db, connected, monkeypatch):
    monkeypatch.setattr(gauth, "_post_token", lambda data: pytest.fail("מוקדם מדי"))
    assert gauth.check(db, now()) is None


def test_check_runs_once_the_interval_passed(db, connected, monkeypatch):
    monkeypatch.setattr(
        gauth, "_post_token", lambda data: {"access_token": "access-3", "expires_in": 3599}
    )
    later = now() + timedelta(hours=get_settings().google_check_hours + 1)
    cred = gauth.check(db, later)
    assert cred is not None and cred.status == "connected"


def test_invalid_grant_marks_disconnected_and_warns_once(db, connected, monkeypatch, sent):
    def dead(data):
        raise gauth.GoogleDisconnected("Token has been expired or revoked.")

    monkeypatch.setattr(gauth, "_post_token", dead)
    later = now() + timedelta(hours=get_settings().google_check_hours + 1)

    assert reminders.watch_google(db, later) is True
    db.refresh(connected)
    assert connected.status == "disconnected"
    assert len(sent) == 1 and "נותק" in sent[0][1]

    # ⚠️ הסבב הבא לא שולח שוב, וגם לא בודק — מנותק נשאר מנותק עד חיבור
    assert reminders.watch_google(db, later + timedelta(days=2)) is False
    assert len(sent) == 1


def test_a_network_error_is_not_a_disconnect(db, connected, monkeypatch, sent):
    def flaky(data):
        raise gauth.GoogleError("timeout")

    monkeypatch.setattr(gauth, "_post_token", flaky)
    later = now() + timedelta(hours=get_settings().google_check_hours + 1)

    assert reminders.watch_google(db, later) is False
    db.refresh(connected)
    assert connected.status == "connected"
    assert sent == []
    # לא בודקים שוב מיד, אבל גם לא מחכים יממה
    assert gauth._retry_at == later + gauth.RETRY_AFTER_ERROR


def test_reconnecting_clears_the_disconnected_warning(db, connected, no_profile):
    connected.status = "disconnected"
    connected.last_error = "revoked"
    connected.disconnected_notified_at = now()
    db.commit()

    cred = gauth.save_tokens(db, dict(TOKENS))
    assert cred.status == "connected"
    assert cred.last_error == ""
    # בלי האיפוס הזה ניתוק הבא היה עובר בשקט
    assert cred.disconnected_notified_at is None


def test_reconnect_keeps_the_old_refresh_token_when_google_omits_it(db, connected, no_profile):
    """גוגל לא תמיד מחזירה טוקן רענון. דריסה בריק הייתה הורגת את החיבור."""
    gauth.save_tokens(db, {"access_token": "access-9", "expires_in": 3599, "scope": TOKENS["scope"]})
    cred = gauth.get_credential(db)
    assert crypto.decrypt(cred.refresh_token_enc) == "refresh-1"


def test_only_one_connection_row_exists(db, connected, no_profile):
    gauth.save_tokens(db, dict(TOKENS, refresh_token="refresh-2"))
    assert db.query(GoogleCredential).count() == 1
