def _ids(client, path):
    return {item["name"]: item["id"] for item in client.get(path).json()}


def test_seeded_lists(client):
    assert set(_ids(client, "/api/client-families")) == {"יעדים", "עסק פרטי", 'נדל"ן'}
    assert list(_ids(client, "/api/domains")) == ["לקוחות", "כספים", "שיווק ומכירות", "פיתוח", "אישי/בית"]
    assert list(_ids(client, "/api/task-types")) == ["טלפון", "פגישה", "מחשב"]


def test_client_with_multiple_families(client):
    fam = _ids(client, "/api/client-families")
    r = client.post("/api/clients", json={"name": "דני", "family_ids": [fam["יעדים"], fam['נדל"ן']], "email": " "})
    assert r.status_code == 201
    body = r.json()
    assert {f["name"] for f in body["families"]} == {"יעדים", 'נדל"ן'}
    assert body["email"] is None
    only = client.get("/api/clients", params={"family_id": fam["עסק פרטי"]}).json()
    assert only == []


def test_client_tax_id_and_address(client):
    fam = _ids(client, "/api/client-families")
    r = client.post(
        "/api/clients",
        json={
            "name": 'ארץ זרועה ע"ר',
            "family_ids": [fam["עסק פרטי"]],
            "tax_id": "580743375",
            "address": "שדה אליהו",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["tax_id"] == "580743375"
    assert body["address"] == "שדה אליהו"

    # שדה שמגיע ריק נשמר כ-null ולא כמחרוזת ריקה
    r = client.put(
        f"/api/clients/{body['id']}",
        json={"name": body["name"], "family_ids": [fam["עסק פרטי"]], "tax_id": "  ", "address": ""},
    )
    assert r.status_code == 200
    assert r.json()["tax_id"] is None
    assert r.json()["address"] is None


def test_clients_domain_requires_client(client):
    dom = _ids(client, "/api/domains")
    r = client.post("/api/tasks", json={"title": "להתקשר", "domain_id": dom["לקוחות"]})
    assert r.status_code == 422
    c = client.post("/api/clients", json={"name": "דני"}).json()
    r = client.post("/api/tasks", json={"title": "להתקשר", "domain_id": dom["לקוחות"], "client_id": c["id"]})
    assert r.status_code == 201
    # בתחום אחר לקוח לא חובה
    assert client.post("/api/tasks", json={"title": "חשבונית", "domain_id": dom["כספים"]}).status_code == 201


def test_task_domain_required(client):
    assert client.post("/api/tasks", json={"title": "בלי תחום"}).status_code == 422


def test_task_inherits_from_project(client):
    dom = _ids(client, "/api/domains")
    c = client.post("/api/clients", json={"name": "דני"}).json()
    p = client.post("/api/projects", json={"name": "אתר", "domain_id": dom["פיתוח"], "client_id": c["id"]}).json()
    t = client.post("/api/tasks", json={"title": "עיצוב", "project_id": p["id"]}).json()
    assert t["domain_id"] == dom["פיתוח"]
    assert t["client_id"] == c["id"]
    # אפשר לשנות את התחום
    t2 = client.post("/api/tasks", json={"title": "הצעת מחיר", "project_id": p["id"], "domain_id": dom["כספים"]})
    assert t2.json()["domain_id"] == dom["כספים"]
    # אי אפשר לשייך ללקוח אחר
    other = client.post("/api/clients", json={"name": "רון"}).json()
    r = client.post("/api/tasks", json={"title": "x", "project_id": p["id"], "client_id": other["id"]})
    assert r.status_code == 422


def test_project_client_change_moves_tasks(client):
    dom = _ids(client, "/api/domains")
    a = client.post("/api/clients", json={"name": "א"}).json()
    b = client.post("/api/clients", json={"name": "ב"}).json()
    p = client.post("/api/projects", json={"name": "פ", "domain_id": dom["פיתוח"], "client_id": a["id"]}).json()
    t = client.post("/api/tasks", json={"title": "מ", "project_id": p["id"]}).json()
    client.put(f"/api/projects/{p['id']}", json={"name": "פ", "domain_id": dom["פיתוח"], "client_id": b["id"]})
    assert client.get(f"/api/tasks/{t['id']}").json()["client_id"] == b["id"]


def test_project_domain_required(client):
    assert client.post("/api/projects", json={"name": "פ"}).status_code == 422


def test_cannot_delete_with_tasks(client):
    dom = _ids(client, "/api/domains")
    c = client.post("/api/clients", json={"name": "דני"}).json()
    p = client.post("/api/projects", json={"name": "פ", "domain_id": dom["פיתוח"], "client_id": c["id"]}).json()
    t = client.post("/api/tasks", json={"title": "מ", "project_id": p["id"]}).json()
    assert client.delete(f"/api/clients/{c['id']}").status_code == 409
    assert client.delete(f"/api/projects/{p['id']}").status_code == 409
    assert client.delete(f"/api/domains/{dom['פיתוח']}").status_code == 409
    client.delete(f"/api/tasks/{t['id']}")
    assert client.delete(f"/api/projects/{p['id']}").status_code == 200
    assert client.delete(f"/api/clients/{c['id']}").status_code == 200


def test_task_status_and_counts(client):
    dom = _ids(client, "/api/domains")
    c = client.post("/api/clients", json={"name": "דני"}).json()
    t = client.post("/api/tasks", json={"title": "מ", "domain_id": dom["לקוחות"], "client_id": c["id"]}).json()
    assert client.get(f"/api/clients/{c['id']}").json()["open_tasks"] == 1
    done = client.patch(f"/api/tasks/{t['id']}/status", json={"status": "done"}).json()
    assert done["status"] == "done" and done["done_at"]
    assert client.get(f"/api/clients/{c['id']}").json()["open_tasks"] == 0
    assert client.get("/api/tasks", params={"status": "open"}).json() == []


def test_lookup_crud(client):
    r = client.post("/api/task-types", json={"name": "מייל", "sort_order": 4})
    assert r.status_code == 201
    assert client.post("/api/task-types", json={"name": "מייל"}).status_code == 409
    assert client.delete(f"/api/task-types/{r.json()['id']}").status_code == 200
