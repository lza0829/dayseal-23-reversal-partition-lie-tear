from __future__ import annotations
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """每个用例一个全新的临时库，通过环境变量隔离数据目录。"""
    monkeypatch.setenv("DAYSEAL_DATA_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    from app.main import app  # noqa: WPS433 导入即建表+种子
    with TestClient(app) as c:
        yield c


SEED_DAY = "2026-11-16"
SEED_TOTAL = 35.5 + 128.0 + 66.0 + 210.0 + 49.9  # 489.4


def _line_by_no(client, line_no: str, day: str = SEED_DAY) -> dict:
    rows = client.get("/api/lines", params={"business_day": day}).json()
    return next(r for r in rows if r["line_no"] == line_no)


def test_default_policy_is_same_day(client):
    meta = client.get("/api/settings/reversal-policy").json()
    assert meta["reversal_policy"] == "same_day"
    assert set(meta["options"]) == {"same_day", "current_day"}


def test_same_day_reversal_unsealed_nets_into_day_total(client):
    original = _line_by_no(client, "CL-0001")

    resp = client.post(f"/api/lines/{original['id']}/reverse", json={})
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # 冲正落在原流水同一营业日，金额为负，引用原 line_no
    rev = payload["reversal"]
    assert rev["business_day"] == SEED_DAY
    assert rev["amount"] == pytest.approx(-35.5)
    assert rev["entry_type"] == "reversal"
    assert rev["reversal_of_line_no"] == "CL-0001"
    assert payload["policy"] == "same_day"
    assert payload["original_business_day"] == SEED_DAY
    assert payload["reversal_business_day"] == SEED_DAY

    # 原流水仍在且未被改动（不靠删除冒充冲正）
    untouched = _line_by_no(client, "CL-0001")
    assert untouched["amount"] == pytest.approx(35.5)
    assert untouched["entry_type"] == "normal"

    # 预览口径：净额含负向冲正，笔数含冲正流水
    preview = client.get("/api/close/preview").json()
    assert preview["system_total"] == pytest.approx(SEED_TOTAL - 35.5)
    assert preview["line_count"] == 6
    assert preview["reversal_count"] == 1

    # 溯源记录可回查原 line_no 与落点营业日
    trace = client.get("/api/lines/reversals/all").json()
    assert len(trace) == 1
    assert trace[0]["original_line_no"] == "CL-0001"
    assert trace[0]["reversal_line_no"] == rev["line_no"]
    assert trace[0]["reversal_business_day"] == SEED_DAY

    # 对冲后净额进入该日封账合计（预览/封账/仪表盘同源）
    sealed = client.post("/api/close/seal", json={
        "business_day": SEED_DAY,
        "declared_cash": SEED_TOTAL - 35.5,
    }).json()
    assert sealed["system_total"] == pytest.approx(SEED_TOTAL - 35.5)
    assert sealed["variance"] == pytest.approx(0.0)
    dash = client.get("/api/dashboard").json()
    assert dash["system_total_today"] == pytest.approx(SEED_TOTAL - 35.5)


def test_same_day_reversal_rejected_when_day_sealed(client):
    client.post("/api/close/seal", json={
        "business_day": SEED_DAY,
        "declared_cash": SEED_TOTAL,
    })
    original = _line_by_no(client, "CL-0001")

    resp = client.post(f"/api/lines/{original['id']}/reverse", json={})
    assert resp.status_code == 409
    assert "封账" in resp.json()["detail"]

    # 被拒后无冲正流水、无溯源记录、原日合计不变
    preview = client.get("/api/close/preview").json()
    assert preview["system_total"] == pytest.approx(SEED_TOTAL)
    assert preview["line_count"] == 5
    assert client.get("/api/lines/reversals/all").json() == []
    assert _line_by_no(client, "CL-0001")["amount"] == pytest.approx(35.5)


def test_current_day_reversal_keeps_sealed_day_untouched(client):
    # 切到「冲正日另计」，并把当前营业日推进到次日
    assert client.put("/api/settings/reversal-policy",
                      json={"reversal_policy": "current_day"}).status_code == 200
    client.put("/api/settings/business-day", json={"business_day": "2026-11-17"})

    # 原营业日先封账，合计定格
    client.post("/api/close/seal", json={
        "business_day": SEED_DAY,
        "declared_cash": SEED_TOTAL,
    })
    original = _line_by_no(client, "CL-0001")

    resp = client.post(f"/api/lines/{original['id']}/reverse", json={})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    rev = payload["reversal"]

    # 冲正落入发起时当前营业日，原日已封合计不变
    assert rev["business_day"] == "2026-11-17"
    assert rev["amount"] == pytest.approx(-35.5)
    assert rev["reversal_of_line_no"] == "CL-0001"
    assert payload["policy"] == "current_day"

    old_preview = client.get("/api/close/preview",
                             params={"business_day": SEED_DAY}).json()
    assert old_preview["sealed"] is True
    assert old_preview["system_total"] == pytest.approx(SEED_TOTAL)
    assert old_preview["line_count"] == 5
    batch = next(b for b in client.get("/api/close/batches").json()
                 if b["business_day"] == SEED_DAY)
    assert batch["system_total"] == pytest.approx(SEED_TOTAL)

    # 冲正日合计含负向额
    new_preview = client.get("/api/close/preview",
                             params={"business_day": "2026-11-17"}).json()
    assert new_preview["system_total"] == pytest.approx(-35.5)
    assert new_preview["line_count"] == 1
    assert new_preview["reversal_count"] == 1

    # 批次与流水均可溯源原 line_no
    trace = client.get("/api/lines/reversals/all").json()
    assert trace[0]["original_line_no"] == "CL-0001"
    assert trace[0]["original_business_day"] == SEED_DAY
    assert trace[0]["reversal_business_day"] == "2026-11-17"

    # 冲正日可带着负向额封账
    sealed = client.post("/api/close/seal", json={
        "business_day": "2026-11-17",
        "declared_cash": -35.5,
    }).json()
    assert sealed["system_total"] == pytest.approx(-35.5)
    assert sealed["variance"] == pytest.approx(0.0)


def test_readonly_chain_and_no_physical_delete(client):
    original = _line_by_no(client, "CL-0001")
    rev = client.post(f"/api/lines/{original['id']}/reverse", json={}).json()["reversal"]

    # 已冲正的原流水：禁改禁删
    assert client.patch(f"/api/lines/{original['id']}",
                        json={"amount": 1}).status_code == 409
    assert client.delete(f"/api/lines/{original['id']}").status_code == 409
    # 冲正流水本身也是只读溯源记录
    assert client.delete(f"/api/lines/{rev['id']}").status_code == 409
    assert client.patch(f"/api/lines/{rev['id']}",
                        json={"amount": -1}).status_code == 409
    # 禁止重复冲正
    assert client.post(f"/api/lines/{original['id']}/reverse",
                       json={}).status_code == 409
    # 冲正流水不可再次冲正
    assert client.post(f"/api/lines/{rev['id']}/reverse",
                       json={}).status_code == 400

    # 普通入口拒绝负金额，负向流水只能走冲正
    bad = client.post("/api/lines", json={
        "till_code": "TILL-A", "amount": -10, "business_day": SEED_DAY,
    })
    assert bad.status_code == 400

    # 原流水物理上仍然存在
    assert _line_by_no(client, "CL-0001")["id"] == original["id"]


def test_policy_is_global_mutex_and_validated(client):
    bad = client.put("/api/settings/reversal-policy",
                     json={"reversal_policy": "pick-both"})
    assert bad.status_code == 400
    assert client.get("/api/settings/reversal-policy").json()["reversal_policy"] == "same_day"

    client.put("/api/settings/reversal-policy",
               json={"reversal_policy": "current_day"})
    client.put("/api/settings/business-day", json={"business_day": "2026-11-18"})
    original = _line_by_no(client, "CL-0002")
    payload = client.post(f"/api/lines/{original['id']}/reverse", json={}).json()
    # 切换后全系统只贯彻新策略：冲正一律落当前营业日
    assert payload["policy"] == "current_day"
    assert payload["reversal_business_day"] == "2026-11-18"
