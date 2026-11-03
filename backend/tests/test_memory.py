"""בדיקות למסך הזיכרון: מה הבוט יודע, ומי יכול לשנות את זה."""

from sqlalchemy import select

from app.models import Observation


def kinds(db) -> list[str]:
    return [row.kind for row in db.scalars(select(Observation).order_by(Observation.id)).all()]


def test_memory_is_closed_to_anyone_who_is_not_signed_in(anon):
    assert anon.get("/api/memory/facts").status_code == 401
    assert anon.post("/api/memory/facts", json={"dimension": 1, "content": "משהו"}).status_code == 401


def test_the_nine_dimensions_say_which_of_them_reaches_the_bot(client):
    items = client.get("/api/memory/dimensions").json()
    assert len(items) == 9
    assert {item["id"] for item in items if item["in_prompt"]} == {1, 2, 3, 5, 7}
    assert items[0]["name"] == "אנשים"


def test_a_fact_is_created_read_and_deleted(client, db):
    created = client.post(
        "/api/memory/facts", json={"dimension": 2, "content": "  לא עונה אחרי שבע  "}
    )
    assert created.status_code == 201
    body = created.json()
    # רווחים מיותרים נדחסים, כי העובדה נכנסת לפרומפט כמו שהיא
    assert body["content"] == "לא עונה אחרי שבע"
    assert body["source"] == "dashboard"

    assert [item["id"] for item in client.get("/api/memory/facts").json()] == [body["id"]]
    assert client.delete(f"/api/memory/facts/{body['id']}").status_code == 200
    assert client.get("/api/memory/facts").json() == []
    assert kinds(db) == ["fact_added", "fact_removed"]


def test_a_fact_can_be_corrected(client):
    body = client.post("/api/memory/facts", json={"dimension": 2, "content": "לא אחרי שבע"}).json()
    updated = client.put(
        f"/api/memory/facts/{body['id']}", json={"dimension": 5, "content": "לא אחרי שמונה"}
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "לא אחרי שמונה"
    assert updated.json()["dimension"] == 5


def test_a_dimension_outside_the_table_is_refused(client):
    assert client.post("/api/memory/facts", json={"dimension": 11, "content": "משהו"}).status_code == 422
    assert client.post("/api/memory/facts", json={"dimension": 2, "content": " "}).status_code == 422


def test_a_fact_about_a_client_that_does_not_exist_is_refused(client):
    resp = client.post(
        "/api/memory/facts", json={"dimension": 1, "content": "משהו", "client_id": 9876}
    )
    assert resp.status_code == 422


def test_a_missing_fact_is_a_404(client):
    assert client.delete("/api/memory/facts/9876").status_code == 404


def test_the_block_shows_exactly_what_the_bot_receives(client):
    assert client.get("/api/memory/block").json() == {"block": ""}
    client.post("/api/memory/facts", json={"dimension": 1, "content": "דני כהן מיעדים"})
    block = client.get("/api/memory/block").json()["block"]
    assert "[אנשים] דני כהן מיעדים" in block


def test_a_fact_in_a_dimension_the_bot_ignores_is_still_kept(client):
    """ממד 9 לא נשלח לבוט היום, אבל העובדה נשמרת ולא נזרקת."""
    created = client.post("/api/memory/facts", json={"dimension": 9, "content": "כותב קצר"})
    assert created.status_code == 201
    assert client.get("/api/memory/block").json()["block"] == ""
    assert len(client.get("/api/memory/facts").json()) == 1
