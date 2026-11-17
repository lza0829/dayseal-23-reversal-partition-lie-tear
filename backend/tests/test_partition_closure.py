"""负向冲正事实 ↔ 分区钉扎合计：三夹具互证。

每个夹具都同时钉住两侧并验证同源：
  事实侧  cash_lines 原行/冲正行 + reversals 引用链
  度量侧  封账预览 / 封账批次 / 仪表盘 的分区净额

互斥收口（全局只贯彻一种，由 settings.reversal_policy 决定）：
  same_day    以引用链为准：冲正落原分区，已封则拒绝承认该冲正
  current_day 以已封分区净额为准：冲正落当前营业日分区，已封分区纹丝不动
两条都不允许：删原事实冒充冲正；已 sealed 分区度量被冲正悄悄改写。
"""
from __future__ import annotations

import pytest


SEED_DAY = "2026-11-16"
NEXT_DAY = "2026-11-17"
SEED_TOTAL = 35.5 + 128.0 + 66.0 + 210.0 + 49.9  # 489.4


def _lines(client, day: str) -> list[dict]:
    return client.get("/api/lines", params={"business_day": day}).json()


def _line_by_no(client, line_no: str, day: str = SEED_DAY) -> dict:
    return next(r for r in _lines(client, day) if r["line_no"] == line_no)


def _preview(client, day: str) -> dict:
    return client.get("/api/close/preview", params={"business_day": day}).json()


def _batch_for(client, day: str) -> dict:
    return next(b for b in client.get("/api/close/batches").json()
                if b["business_day"] == day)


def _assert_preview_self_consistent(preview: dict) -> None:
    """预览聚合同源：行集合求和恒等于净额，笔数恒等于行数（含负向冲正行）。"""
    assert sum(r["amount"] for r in preview["lines"]) == pytest.approx(preview["system_total"])
    assert len(preview["lines"]) == preview["line_count"]


def test_fixture_original_never_vanishes_without_negative_row(client):
    """夹具一「原单消失无冲正」：冲正后原单必须物理存在，且必有对应负向冲正行。

    分区净额只能经由「原行 + 负向行」成对变化，绝不凭空消失；
    任何入口（删/改）都无法让已冲正原单或冲正单消失。
    """
    original = _line_by_no(client, "CL-0001")
    resp = client.post(f"/api/lines/{original['id']}/reverse", json={})
    assert resp.status_code == 200, resp.text
    rev = resp.json()["reversal"]

    # 事实侧：原单仍在、原额未动；负向冲正行真实存在并引用原单号
    by_no = {r["line_no"]: r for r in _lines(client, SEED_DAY)}
    assert original["line_no"] in by_no, "原单被物理删除冒充冲正"
    assert by_no["CL-0001"]["amount"] == pytest.approx(35.5)
    assert by_no["CL-0001"]["entry_type"] == "normal"
    assert rev["line_no"] in by_no, "冲正声称完成却无负向冲正行"
    assert by_no[rev["line_no"]]["amount"] == pytest.approx(-35.5)
    assert by_no[rev["line_no"]]["reversal_of_line_no"] == "CL-0001"

    # 度量侧：分区净额 = 原行 + 负向行之和；预览行集合与净额同源（不单边计）
    preview = _preview(client, SEED_DAY)
    assert preview["system_total"] == pytest.approx(SEED_TOTAL - 35.5)
    _assert_preview_self_consistent(preview)
    assert {r["line_no"] for r in preview["lines"]} >= {"CL-0001", rev["line_no"]}

    # 引用链互证：溯源记录两端都物理存在，落点分区与流水一致
    traces = client.get("/api/lines/reversals/all").json()
    assert len(traces) == 1
    trace = traces[0]
    assert trace["original_line_no"] in by_no
    assert trace["reversal_line_no"] in by_no
    assert trace["reversal_business_day"] == by_no[rev["line_no"]]["business_day"]
    assert trace["amount"] == pytest.approx(by_no[rev["line_no"]]["amount"])

    # 任何入口都无法让原单/冲正单消失：禁删禁改，拒绝后事实与度量仍一致
    assert client.delete(f"/api/lines/{original['id']}").status_code == 409
    assert client.delete(f"/api/lines/{rev['id']}").status_code == 409
    assert client.patch(f"/api/lines/{original['id']}", json={"amount": 0}).status_code == 409
    assert len(_lines(client, SEED_DAY)) == 6
    _assert_preview_self_consistent(_preview(client, SEED_DAY))

    # 仪表盘与预览同源
    dash = client.get("/api/dashboard").json()
    assert dash["system_total_today"] == pytest.approx(SEED_TOTAL - 35.5)


def test_fixture_reversal_never_enters_sealed_partition(client):
    """夹具二「冲正进已封分区」：已 sealed 分区净额钉扎，冲正与任何写入都撬不动。

    same_day    → 拒绝承认该冲正，已封分区净额与批次合计纹丝不动；
    current_day → 冲正落当前营业日分区，已封分区与批次不被改写；
    两种策略下普通登记写闸同样生效（恢复写闸）。
    """
    sealed = client.post("/api/close/seal", json={
        "business_day": SEED_DAY, "declared_cash": SEED_TOTAL,
    }).json()
    assert sealed["system_total"] == pytest.approx(SEED_TOTAL)

    # 写闸：普通流水也不得写入已封分区（不允许静默改写已封净额）
    blocked = client.post("/api/lines", json={
        "till_code": "TILL-A", "amount": 1, "business_day": SEED_DAY,
    })
    assert blocked.status_code == 409

    # same_day（默认）：拒绝承认该冲正；无冲正行、无溯源记录、批次合计不变
    original = _line_by_no(client, "CL-0001")
    rejected = client.post(f"/api/lines/{original['id']}/reverse", json={})
    assert rejected.status_code == 409
    preview = _preview(client, SEED_DAY)
    assert preview["system_total"] == pytest.approx(SEED_TOTAL)
    assert preview["line_count"] == 5
    _assert_preview_self_consistent(preview)
    assert client.get("/api/lines/reversals/all").json() == []
    assert _batch_for(client, SEED_DAY)["system_total"] == pytest.approx(SEED_TOTAL)

    # current_day：冲正落新分区，已封分区与批次保持钉扎
    assert client.put("/api/settings/reversal-policy",
                      json={"reversal_policy": "current_day"}).status_code == 200
    client.put("/api/settings/business-day", json={"business_day": NEXT_DAY})
    resp = client.post(f"/api/lines/{original['id']}/reverse", json={})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["reversal_business_day"] == NEXT_DAY

    old = _preview(client, SEED_DAY)
    assert old["sealed"] is True
    assert old["system_total"] == pytest.approx(SEED_TOTAL)
    assert old["reversal_count"] == 0
    _assert_preview_self_consistent(old)
    assert _batch_for(client, SEED_DAY)["system_total"] == pytest.approx(SEED_TOTAL)

    # 已封分区写闸仍然生效；冲正日分区可正常封账
    assert client.post("/api/lines", json={
        "till_code": "TILL-A", "amount": 1, "business_day": SEED_DAY,
    }).status_code == 409
    new_sealed = client.post("/api/close/seal", json={
        "business_day": NEXT_DAY, "declared_cash": -35.5,
    }).json()
    assert new_sealed["system_total"] == pytest.approx(-35.5)
    # 两个批次各自钉扎，互不撬动
    assert _batch_for(client, SEED_DAY)["system_total"] == pytest.approx(SEED_TOTAL)
    assert _batch_for(client, NEXT_DAY)["system_total"] == pytest.approx(-35.5)


def test_fixture_no_double_deduction_across_partitions(client):
    """夹具三「双边重复扣」：一笔冲正全局只扣一次。

    current_day：原已封分区保持钉扎不再扣，冲正分区只含一笔负向额，
    跨分区合计 = 原合计 - 冲正额（恰好一次）；
    随后切回 same_day 对未封分区对冲，同样只扣一次且封账落批同源。
    """
    # 第一笔：current_day，原日已封
    assert client.put("/api/settings/reversal-policy",
                      json={"reversal_policy": "current_day"}).status_code == 200
    client.put("/api/settings/business-day", json={"business_day": NEXT_DAY})
    client.post("/api/close/seal", json={
        "business_day": SEED_DAY, "declared_cash": SEED_TOTAL,
    })
    original = _line_by_no(client, "CL-0001")  # 35.5
    client.post(f"/api/lines/{original['id']}/reverse", json={})

    old = _preview(client, SEED_DAY)
    new = _preview(client, NEXT_DAY)
    # 原分区不被再扣一次，冲正分区只扣一次
    assert old["system_total"] == pytest.approx(SEED_TOTAL)
    assert new["system_total"] == pytest.approx(-35.5)
    assert old["system_total"] + new["system_total"] == pytest.approx(SEED_TOTAL - 35.5)
    _assert_preview_self_consistent(old)
    _assert_preview_self_consistent(new)
    # 引用链只登记一条，金额与落点唯一
    traces = client.get("/api/lines/reversals/all").json()
    assert len(traces) == 1
    assert traces[0]["amount"] == pytest.approx(-35.5)

    # 第二笔：切回 same_day，对未封的冲正日分区对冲另一原单？——
    # 冲正日分区只有冲正行（不可再冲正），改为验证同分区同日对冲也只扣一次：
    # 直接对未封的昨日分区（2026-11-15，CL-0006=88.0）同日对冲。
    assert client.put("/api/settings/reversal-policy",
                      json={"reversal_policy": "same_day"}).status_code == 200
    yesterday = _line_by_no(client, "CL-0006", day="2026-11-15")
    resp = client.post(f"/api/lines/{yesterday['id']}/reverse", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["reversal_business_day"] == "2026-11-15"

    yday = _preview(client, "2026-11-15")
    assert yday["system_total"] == pytest.approx(0.0)  # 88.0 - 88.0，恰好一次
    _assert_preview_self_consistent(yday)
    # 全局冲正记录两笔，各自独立引用，无重复扣
    traces = client.get("/api/lines/reversals/all").json()
    assert len(traces) == 2
    assert {t["original_line_no"] for t in traces} == {"CL-0001", "CL-0006"}

    # 封账落批与预览同源：批次净额 == 预览净额，不重复扣
    sealed = client.post("/api/close/seal", json={
        "business_day": "2026-11-15", "declared_cash": 0.0,
    }).json()
    assert sealed["system_total"] == pytest.approx(0.0)
    assert _batch_for(client, "2026-11-15")["system_total"] == pytest.approx(0.0)
    # 已封的 original 分区依旧钉扎，未被任何后续冲正撬动
    assert _batch_for(client, SEED_DAY)["system_total"] == pytest.approx(SEED_TOTAL)
