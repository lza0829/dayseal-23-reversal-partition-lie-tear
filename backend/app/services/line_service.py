from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from fastapi import HTTPException
from app.db import connect
from app.repositories import closes as close_repo
from app.repositories import lines as line_repo
from app.repositories import reversals as reversal_repo
from app.repositories import settings as settings_repo
from app import reversal_view
from app import align_23 as align_mod


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def list_lines(business_day: str | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return line_repo.list_lines(conn, business_day)
    finally:
        conn.close()


def list_reversals() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return reversal_repo.list_reversals(conn)
    finally:
        conn.close()


def create_line(body: dict[str, Any]) -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        day = body.get("business_day") or settings_repo.get(conn, "business_day")
        if not day:
            raise HTTPException(400, "未设置营业日")
        if close_repo.is_sealed(conn, day) and not reversal_view.allow_reversal_into_sealed(conn, close_repo, day):
            raise HTTPException(409, f"营业日 {day} 已封账，禁止新增流水")
        amount = float(body["amount"])
        # 负向流水只能由冲正入口产生，普通登记不得直接写负数
        if amount < 0:
            raise HTTPException(400, "负向流水须走冲正入口，禁止直接登记")
        created = _now()
        lid = line_repo.insert_line(
            conn,
            line_no=line_repo.next_line_no(conn),
            till_code=body["till_code"],
            business_day=day,
            occurred_at=body.get("occurred_at") or created,
            amount=amount,
            pay_method=body.get("pay_method") or "现金",
            note=body.get("note"),
            created_at=created,
            entry_type=line_repo.ENTRY_NORMAL,
        )
        conn.commit()
        return line_repo.get_line(conn, lid)  # type: ignore
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reverse_line(line_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """冲正唯一入口。

    冲正命运由全局互斥策略 reversal_policy 决定，全系统同一时刻只贯彻一种：
      same_day    同日对冲：冲正必须落在原流水同一 business_day，金额为负并向原
                  line_no 留引用；该日已 sealed 且系统未实现解封时直接拒绝；对冲后
                  净额进入该日封账合计。
      current_day 冲正日另计：冲正落入发起时的当前营业日，原日已封合计不变；冲正日
                  合计含负向额，批次与流水均能溯源原 line_no。
    原流水全程只读，绝不物理删除。
    """
    conn = connect(immediate=True)
    try:
        original = line_repo.get_line(conn, line_id)
        if not original:
            raise HTTPException(404, "原流水不存在")
        if original["entry_type"] == line_repo.ENTRY_REVERSAL:
            raise HTTPException(400, "冲正流水不可再次冲正")
        if line_repo.has_reversal(conn, original["line_no"]):
            raise HTTPException(409, f"流水 {original['line_no']} 已冲正，禁止重复冲正")

        policy = settings_repo.get_reversal_policy(conn)
        original_day = original["business_day"]
        created = _now()

        if policy == settings_repo.REVERSAL_POLICY_SAME_DAY:
            target_day = original_day
            # 同日对冲且该日已封账：未实现解封，直接拒绝，不撬已封日
            if close_repo.is_sealed(conn, target_day):
                raise HTTPException(
                    409,
                    f"营业日 {target_day} 已封账，同日对冲被拒绝（系统未提供解封）",
                )
        else:  # current_day：冲正日另计
            target_day = settings_repo.get(conn, "business_day")
            if not target_day:
                raise HTTPException(400, "未设置当前营业日，无法发起冲正日另计")
            # 冲正日本身已封账时，负向流水无处可落，拒绝
            if close_repo.is_sealed(conn, target_day):
                raise HTTPException(409, f"当前营业日 {target_day} 已封账，禁止落入冲正流水")

        reversal_no = line_repo.next_line_no(conn)
        reversal_amount = -abs(float(original["amount"]))
        note = body.get("note") or f"冲正 {original['line_no']}"
        reversal_id = line_repo.insert_line(
            conn,
            line_no=reversal_no,
            till_code=original["till_code"],
            business_day=target_day,
            occurred_at=created,
            amount=reversal_amount,
            pay_method=original["pay_method"],
            note=note,
            created_at=created,
            entry_type=line_repo.ENTRY_REVERSAL,
            reversal_of_line_no=original["line_no"],
        )
        reversal_repo.add_reversal(
            conn,
            reversal_line_id=reversal_id,
            reversal_line_no=reversal_no,
            original_line_id=original["id"],
            original_line_no=original["line_no"],
            policy=policy,
            original_business_day=original_day,
            reversal_business_day=target_day,
            amount=reversal_amount,
            created_at=created,
        )
        summary = line_repo.day_summary(conn, target_day)
        conn.commit()
        return {
            "reversal": line_repo.get_line(conn, reversal_id),
            "original": original,
            "policy": policy,
            "original_business_day": original_day,
            "reversal_business_day": target_day,
            "target_day_summary": summary,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def patch_line(line_id: int, body: dict[str, Any]) -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        row = line_repo.get_line(conn, line_id)
        if not row:
            raise HTTPException(404, "流水不存在")
        if close_repo.is_sealed(conn, row["business_day"]):
            raise HTTPException(409, f"营业日 {row['business_day']} 已封账，禁止修改流水")
        # 原流水只读链：冲正流水与已被冲正的原流水均不得改写
        if row["entry_type"] == line_repo.ENTRY_REVERSAL:
            raise HTTPException(409, "冲正流水只读，禁止修改")
        if line_repo.has_reversal(conn, row["line_no"]):
            raise HTTPException(409, f"流水 {row['line_no']} 已冲正，原流水只读")
        amount = float(body.get("amount", row["amount"]))
        if amount < 0:
            raise HTTPException(400, "负向流水须走冲正入口，禁止直接登记")
        line_repo.update_line(
            conn,
            line_id,
            amount=amount,
            pay_method=body.get("pay_method", row["pay_method"]),
            note=body.get("note", row["note"]),
        )
        conn.commit()
        return line_repo.get_line(conn, line_id)  # type: ignore
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def remove_line(line_id: int) -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        row = line_repo.get_line(conn, line_id)
        if not row:
            raise HTTPException(404, "流水不存在")
        if close_repo.is_sealed(conn, row["business_day"]):
            raise HTTPException(409, f"营业日 {row['business_day']} 已封账，禁止删除流水")
        # 禁止物理删除原流水冒充冲正：冲正流水、已被冲正的原流水都不可删
        if row["entry_type"] == line_repo.ENTRY_REVERSAL:
            raise HTTPException(409, "冲正流水为只读溯源记录，禁止删除")
        if line_repo.has_reversal(conn, row["line_no"]):
            raise HTTPException(409, f"流水 {row['line_no']} 已冲正，禁止删除原流水")
        line_repo.delete_line(conn, line_id)
        conn.commit()
        return {"deleted": True, "id": line_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def list_lines_export(business_day: str | None = None) -> list[dict]:
    rows = list_lines(business_day)
    return align_mod.filter_lines_for_export(rows)


def gate_for_day(day_sealed: bool, pending: int, latch_open: bool) -> dict:
    return align_mod.gate_matrix(day_sealed, pending, latch_open)

