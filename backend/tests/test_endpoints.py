"""Endpoint happy paths + error cases (spec sec 8) via FastAPI TestClient.

The LLM is mocked (fake_coach); the store is isolated per test (tmp_store).
"""
from __future__ import annotations

from _factories import make_plan, make_quiz, make_result


# ----- health -----

def test_health_configured(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["model"]


def test_health_unconfigured(unconfigured_client):
    r = unconfigured_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["configured"] is False


# ----- create plan -----

def test_create_plan(client, fake_coach):
    fake_coach.plan = make_plan(modules=3)
    r = client.post("/api/plans", json={"input": "a topic", "mode": "topic"})
    assert r.status_code == 200
    doc = r.json()
    assert doc["id"]
    assert doc["plan"]["title"] == "test-plan"
    assert len(doc["plan"]["modules"]) == 3
    # persisted
    assert client.get(f"/api/plans/{doc['id']}").status_code == 200


def test_create_plan_unconfigured_503(unconfigured_client):
    r = unconfigured_client.post("/api/plans", json={"input": "x", "mode": "topic"})
    assert r.status_code == 503


def test_create_plan_materials_mode(client, fake_coach):
    fake_coach.plan = make_plan(modules=2)
    r = client.post("/api/plans", json={"input": "pasted material", "mode": "materials"})
    assert r.status_code == 200
    assert r.json()["source"]["mode"] == "materials"


# ----- list / get / delete -----

def test_list_and_get(client, seeded_doc):
    r = client.get("/api/plans")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == seeded_doc.id
    assert items[0]["progress"] == round(1 / 3, 4)

    r2 = client.get(f"/api/plans/{seeded_doc.id}")
    assert r2.status_code == 200
    assert r2.json()["plan"]["title"]


def test_get_plan_404(client):
    assert client.get("/api/plans/nope").status_code == 404


def test_delete_plan(client, seeded_doc):
    r = client.delete(f"/api/plans/{seeded_doc.id}")
    assert r.status_code == 200
    assert r.json()["deleted"] == seeded_doc.id
    assert client.get(f"/api/plans/{seeded_doc.id}").status_code == 404


def test_delete_plan_404(client):
    assert client.delete("/api/plans/nope").status_code == 404


# ----- quiz -----

def test_generate_and_get_quiz(client, fake_coach, seeded_doc):
    fake_coach.quiz = make_quiz()
    mid = seeded_doc.plan.modules[0].id
    r = client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/quiz")
    assert r.status_code == 200
    module = next(m for m in r.json()["plan"]["modules"] if m["id"] == mid)
    assert module["quiz"] is not None
    assert len(module["quiz"]["questions"]) == 2

    r2 = client.get(f"/api/plans/{seeded_doc.id}/modules/{mid}/quiz")
    assert r2.status_code == 200
    assert len(r2.json()["questions"]) == 2


def test_get_quiz_404_when_missing(client, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    assert client.get(f"/api/plans/{seeded_doc.id}/modules/{mid}/quiz").status_code == 404


def test_module_404(client, seeded_doc):
    r = client.get(f"/api/plans/{seeded_doc.id}/modules/no-such-module/quiz")
    assert r.status_code == 404


# ----- answers -----

def test_answers_save_and_progress(client, fake_coach, seeded_doc):
    fake_coach.quiz = make_quiz()
    mid = seeded_doc.plan.modules[0].id
    client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/quiz")
    r = client.put(f"/api/plans/{seeded_doc.id}/modules/{mid}/answers", json={"answers": {"q1": "2"}})
    assert r.status_code == 200

    g = client.get(f"/api/plans/{seeded_doc.id}/modules/{mid}/answers")
    assert g.status_code == 200
    body = g.json()
    assert body["answers"]["q1"] == "2"
    assert body["answered"] == 1
    assert body["total"] == 2


def test_answers_merge(client, fake_coach, seeded_doc):
    fake_coach.quiz = make_quiz()
    mid = seeded_doc.plan.modules[0].id
    client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/quiz")
    client.put(f"/api/plans/{seeded_doc.id}/modules/{mid}/answers", json={"answers": {"q1": "2"}})
    client.put(f"/api/plans/{seeded_doc.id}/modules/{mid}/answers", json={"answers": {"q2": "text"}})
    body = client.get(f"/api/plans/{seeded_doc.id}/modules/{mid}/answers").json()
    assert body["answers"] == {"q1": "2", "q2": "text"}
    assert body["answered"] == 2


# ----- grade -----

def test_grade_no_answers_400(client, fake_coach, seeded_doc):
    fake_coach.quiz = make_quiz()
    mid = seeded_doc.plan.modules[0].id
    client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/quiz")
    r = client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/grade")
    assert r.status_code == 400


def test_grade_without_quiz_404(client, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    assert client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/grade").status_code == 404


def test_grade_happy_sets_completed(client, fake_coach, seeded_doc):
    fake_coach.quiz = make_quiz()
    fake_coach.result = make_result()
    mid = seeded_doc.plan.modules[0].id
    client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/quiz")
    client.put(f"/api/plans/{seeded_doc.id}/modules/{mid}/answers", json={"answers": {"q1": "2", "q2": "text"}})
    r = client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/grade")
    assert r.status_code == 200
    module = next(m for m in r.json()["plan"]["modules"] if m["id"] == mid)
    assert module["status"] == "completed"
    assert module["result"] is not None
    assert module["result"]["maxScore"] == 2.0
    assert fake_coach.last_grade_answers == {"q1": "2", "q2": "text"}


def test_grade_unconfigured_503(unconfigured_client, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    assert unconfigured_client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/grade").status_code == 503


# ----- content (SSE) -----

def test_generate_content_sse(client, fake_coach, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    r = client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/content")
    assert r.status_code == 200
    text = r.text
    assert "event: delta" in text
    assert "event: done" in text
    # content persisted -> GET returns it
    g = client.get(f"/api/plans/{seeded_doc.id}/modules/{mid}/content")
    assert g.status_code == 200
    assert g.json()["keyTakeaways"] == ["point one", "point two"]


def test_get_content_404_when_missing(client, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    assert client.get(f"/api/plans/{seeded_doc.id}/modules/{mid}/content").status_code == 404


def test_generate_content_unconfigured_503(unconfigured_client, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    assert unconfigured_client.post(f"/api/plans/{seeded_doc.id}/modules/{mid}/content").status_code == 503


# ----- patch module status -----

def test_patch_module_status(client, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    r = client.patch(f"/api/plans/{seeded_doc.id}/modules/{mid}", json={"status": "studying"})
    assert r.status_code == 200
    module = next(m for m in r.json()["plan"]["modules"] if m["id"] == mid)
    assert module["status"] == "studying"


def test_patch_module_invalid_status_422(client, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    assert client.patch(f"/api/plans/{seeded_doc.id}/modules/{mid}", json={"status": "bogus"}).status_code == 422

