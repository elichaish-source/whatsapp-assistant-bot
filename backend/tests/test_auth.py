from .conftest import OWNER


def _code(sent):
    return sent[-1][1].split(": ")[1][:6]


def test_requires_login(anon):
    assert anon.get("/api/tasks").status_code == 401
    assert anon.get("/api/auth/me").status_code == 401


def test_login_flow(anon, sent):
    assert anon.post("/api/auth/request-code", json={"phone": "050-123-4567"}).status_code == 200
    assert sent[0][0] == OWNER
    r = anon.post("/api/auth/verify", json={"phone": "0501234567", "code": _code(sent)})
    assert r.status_code == 200
    assert anon.get("/api/auth/me").json() == {"phone": OWNER}
    anon.post("/api/auth/logout")
    assert anon.get("/api/auth/me").status_code == 401


def test_other_phone_gets_no_code(anon, sent):
    assert anon.post("/api/auth/request-code", json={"phone": "972509999999"}).status_code == 200
    assert sent == []


def test_wrong_code_and_reuse(anon, sent):
    anon.post("/api/auth/request-code", json={"phone": OWNER})
    code = _code(sent)
    wrong = "000000" if code != "000000" else "111111"
    assert anon.post("/api/auth/verify", json={"phone": OWNER, "code": wrong}).status_code == 401
    assert anon.post("/api/auth/verify", json={"phone": OWNER, "code": code}).status_code == 200
    assert anon.post("/api/auth/verify", json={"phone": OWNER, "code": code}).status_code == 401


def test_attempts_limited(anon, sent):
    anon.post("/api/auth/request-code", json={"phone": OWNER})
    code = _code(sent)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        anon.post("/api/auth/verify", json={"phone": OWNER, "code": wrong})
    assert anon.post("/api/auth/verify", json={"phone": OWNER, "code": code}).status_code == 401


def test_resend_throttled(anon, sent):
    anon.post("/api/auth/request-code", json={"phone": OWNER})
    anon.post("/api/auth/request-code", json={"phone": OWNER})
    assert len(sent) == 1
