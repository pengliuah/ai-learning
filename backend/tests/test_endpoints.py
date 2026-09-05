"""Endpoint happy paths + error cases (spec sec 8) via FastAPI TestClient.

The LLM is mocked (fake_coach); the store is isolated per test (tmp_store).
"""
from __future__ import annotations

from _factories import make_plan, make_quiz, make_result
from conftest import auth_headers
from app import store
from app.schemas import PlanSource


def _sse_done(r):
    """POST quiz/grade 现在返回 SSE 流, 解析 done 事件里的最终 Document。"""
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    for frame in r.text.split("\n\n"):
        event = ""
        data = ""
        for line in frame.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data += line[6:]
        if event == "done":
            import json
            return json.loads(data)
    raise AssertionError("no done event in stream")


# ----- health -----

def test_health_configured(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert "model" in body  # 用户未配置模型名时为空串，字段始终存在


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
    module = next(m for m in _sse_done(r)["plan"]["modules"] if m["id"] == mid)
    assert module["quiz"] is not None
    assert len(module["quiz"]["questions"]) == 2

    r2 = client.get(f"/api/plans/{seeded_doc.id}/modules/{mid}/quiz")
    assert r2.status_code == 200
    assert len(r2.json()["questions"]) == 2


def test_regenerate_quiz_clears_result_and_answers(client, fake_coach, seeded_doc):
    """Regenerating a quiz must wipe the prior result + draft answers
    (they reference old question ids)."""
    fake_coach.quiz = make_quiz()
    fake_coach.result = make_result()
    mid = seeded_doc.plan.modules[0].id
    base = f"/api/plans/{seeded_doc.id}/modules/{mid}"
    # Generate quiz, save answers, grade -> result set, status completed
    client.post(f"{base}/quiz")
    client.put(f"{base}/answers", json={"answers": {"q1": "2", "q2": "text"}})
    client.post(f"{base}/grade")
    graded = client.get(f"/api/plans/{seeded_doc.id}").json()
    mod = next(m for m in graded["plan"]["modules"] if m["id"] == mid)
    assert mod["result"] is not None
    assert mod["answers"] is not None

    # Regenerate quiz
    r = client.post(f"{base}/quiz")
    mod = next(m for m in _sse_done(r)["plan"]["modules"] if m["id"] == mid)
    assert mod["quiz"] is not None
    assert mod["result"] is None
    assert mod["answers"] is None


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
    module = next(m for m in _sse_done(r)["plan"]["modules"] if m["id"] == mid)
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


# ----- edit content (PUT) -----

def test_edit_content(client, fake_coach, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    plan_id = seeded_doc.id
    # 先生成内容
    assert client.post(f"/api/plans/{plan_id}/modules/{mid}/content").status_code == 200

    r = client.put(f"/api/plans/{plan_id}/modules/{mid}/content",
                   json={"markdown": "# 手工编辑\n\n改过的正文"})
    assert r.status_code == 200
    module = next(m for m in r.json()["plan"]["modules"] if m["id"] == mid)
    assert module["content"]["markdown"] == "# 手工编辑\n\n改过的正文"
    # 关键要点保持不变
    assert module["content"]["keyTakeaways"] == ["point one", "point two"]
    # 持久化 -> 再读一次
    g = client.get(f"/api/plans/{plan_id}/modules/{mid}/content")
    assert g.json()["markdown"] == "# 手工编辑\n\n改过的正文"


def test_edit_content_rejects_blank(client, fake_coach, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    plan_id = seeded_doc.id
    assert client.post(f"/api/plans/{plan_id}/modules/{mid}/content").status_code == 200
    assert client.put(f"/api/plans/{plan_id}/modules/{mid}/content",
                      json={"markdown": "   "}).status_code == 400


def test_edit_content_404_when_no_content(client, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    assert client.put(f"/api/plans/{seeded_doc.id}/modules/{mid}/content",
                      json={"markdown": "x"}).status_code == 400


# ----- reorder plans (home page drag sorting) -----

def test_reorder_plans(client, admin_user, seeded_doc):
    # seeded_doc 之外再造一份计划，保证至少两份
    second = store.create_document(
        PlanSource(input="another topic", mode="topic"), make_plan(modules=2), str(admin_user["id"]))
    ids = [seeded_doc.id, second.id]

    new_order = list(reversed(ids))
    r = client.put("/api/plans/order", json={"planIds": new_order})
    assert r.status_code == 200
    assert [item["id"] for item in r.json()] == new_order
    # 列表读取也按新顺序
    g = client.get("/api/plans")
    assert [item["id"] for item in g.json()] == new_order


def test_reorder_plans_rejects_wrong_ids(client, admin_user, seeded_doc):
    second = store.create_document(
        PlanSource(input="another topic", mode="topic"), make_plan(modules=1), str(admin_user["id"]))
    # 少了一份
    r = client.put("/api/plans/order", json={"planIds": [seeded_doc.id]})
    assert r.status_code == 400
    # 含不存在的 id
    r = client.put("/api/plans/order",
                   json={"planIds": [seeded_doc.id, second.id, "00000000-0000-0000-0000-000000000000"]})
    assert r.status_code == 400


def test_reorder_plans_is_user_scoped(client, normal_user, seeded_doc):
    """用户只能重排自己的计划，他人计划 id 会被判为非法集合。"""
    other = store.create_document(
        PlanSource(input="other user topic", mode="topic"), make_plan(modules=1), str(normal_user["id"]))
    r = client.put("/api/plans/order", json={"planIds": [seeded_doc.id, other.id]})
    assert r.status_code == 400


def test_patch_module_status(client, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    r = client.patch(f"/api/plans/{seeded_doc.id}/modules/{mid}", json={"status": "studying"})
    assert r.status_code == 200
    module = next(m for m in r.json()["plan"]["modules"] if m["id"] == mid)
    assert module["status"] == "studying"


def test_patch_module_invalid_status_422(client, seeded_doc):
    mid = seeded_doc.plan.modules[0].id
    assert client.patch(f"/api/plans/{seeded_doc.id}/modules/{mid}", json={"status": "bogus"}).status_code == 422



def test_annotation_flow(client, seeded_doc):
    """Create -> list -> update -> delete annotations via the API."""
    doc = seeded_doc
    mid = doc.plan.modules[0].id
    base = f"/api/plans/{doc.id}/modules/{mid}/annotations"

    r = client.post(base, json={"quote": "浮力公式", "prefix": "阿基米德：", "suffix": "是重点", "note": "考试必考"})
    assert r.status_code == 200, r.text
    anno = r.json()
    assert anno["quote"] == "浮力公式" and anno["note"] == "考试必考"

    r = client.get(base)
    assert r.status_code == 200 and len(r.json()) == 1

    r = client.put(f"/api/plans/{doc.id}/annotations/{anno['id']}", json={"note": "改了"})
    assert r.status_code == 200 and r.json()["note"] == "改了"

    r = client.delete(f"/api/plans/{doc.id}/annotations/{anno['id']}")
    assert r.status_code == 200
    assert client.get(base).json() == []


def test_annotation_404s(client, seeded_doc, normal_user):
    """Missing module/annotation and cross-user access all 404."""
    doc = seeded_doc
    mid = doc.plan.modules[0].id
    base = f"/api/plans/{doc.id}/modules/{mid}/annotations"

    # 模块不存在
    r = client.post(f"/api/plans/{doc.id}/modules/nope/annotations", json={"quote": "x"})
    assert r.status_code == 404

    # 批注不存在
    r = client.put(f"/api/plans/{doc.id}/annotations/does-not-exist", json={"note": "n"})
    assert r.status_code == 404
    r = client.delete(f"/api/plans/{doc.id}/annotations/does-not-exist")
    assert r.status_code == 404

    # 跨用户: normal_user 建的批注对 admin 计划不可见/不可改
    other = client.post(
        f"/api/plans/{doc.id}/modules/{mid}/annotations",
        json={"quote": "x"}, headers=auth_headers(normal_user),
    )
    assert other.status_code == 404  # plan 不属于 normal_user


def test_annotation_cross_user_isolation(client, seeded_doc, normal_user):
    """A normal user cannot read or modify the admin's annotations."""
    doc = seeded_doc
    mid = doc.plan.modules[0].id
    anno = client.post(
        f"/api/plans/{doc.id}/modules/{mid}/annotations",
        json={"quote": "管理员批注", "note": "admin only"},
    ).json()

    r = client.get(
        f"/api/plans/{doc.id}/modules/{mid}/annotations",
        headers=auth_headers(normal_user),
    )
    assert r.status_code == 404  # 计划本身就不属于 normal_user

    r = client.put(
        f"/api/plans/{doc.id}/annotations/{anno['id']}",
        json={"note": "越权"}, headers=auth_headers(normal_user),
    )
    assert r.status_code == 404
