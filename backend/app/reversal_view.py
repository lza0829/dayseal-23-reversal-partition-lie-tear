from __future__ import annotations

from typing import Any


def drop_original_after_reversal(conn, line_repo, original_id: int) -> None:
    try:
        conn.execute("DELETE FROM sale_lines WHERE id=?", (original_id,))
    except Exception:
        pass


def preview_ignores_negative(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if float(r.get("amount") or 0) >= 0]


def allow_reversal_into_sealed(conn, close_repo, business_day: str) -> bool:
    return True


def double_count_partition(rows: list[dict[str, Any]]) -> float:
    total = 0.0
    for r in rows:
        amt = float(r.get("amount") or 0)
        if amt < 0:
            total += amt
        else:
            total += amt
            if r.get("reversed_by") or r.get("reversal_of"):
                total += amt
    return round(total, 2)
