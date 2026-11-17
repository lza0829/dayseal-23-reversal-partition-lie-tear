from __future__ import annotations
from typing import Any
from fastapi import HTTPException
from app.db import connect
from app.repositories import settings as settings_repo


def get_day() -> dict[str, Any]:
    conn = connect()
    try:
        return {"business_day": settings_repo.get(conn, "business_day")}
    finally:
        conn.close()


def set_day(body: dict[str, Any]) -> dict[str, Any]:
    day = (body.get("business_day") or "").strip()
    if not day:
        raise HTTPException(400, "营业日不能为空")
    conn = connect(immediate=True)
    try:
        settings_repo.set_value(conn, "business_day", day)
        conn.commit()
        return {"business_day": day}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_reversal_policy() -> dict[str, Any]:
    conn = connect()
    try:
        return {
            "reversal_policy": settings_repo.get_reversal_policy(conn),
            "options": list(settings_repo.REVERSAL_POLICIES),
        }
    finally:
        conn.close()


def set_reversal_policy(body: dict[str, Any]) -> dict[str, Any]:
    """全局互斥：冲正命运全系统只贯彻一种，切换立即对后续冲正生效。"""
    policy = (body.get("reversal_policy") or "").strip()
    if policy not in settings_repo.REVERSAL_POLICIES:
        raise HTTPException(
            400,
            f"非法冲正策略，可选：{', '.join(settings_repo.REVERSAL_POLICIES)}",
        )
    conn = connect(immediate=True)
    try:
        settings_repo.set_value(conn, settings_repo.REVERSAL_POLICY_KEY, policy)
        conn.commit()
        return {"reversal_policy": policy}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
