from __future__ import annotations
import sqlite3
from typing import Any

# 有效流水类型：normal=普通流水，reversal=冲正负向流水
ENTRY_NORMAL = "normal"
ENTRY_REVERSAL = "reversal"
ENTRY_TYPES = (ENTRY_NORMAL, ENTRY_REVERSAL)


def list_lines(conn: sqlite3.Connection, business_day: str | None = None) -> list[dict[str, Any]]:
    if business_day:
        rows = conn.execute(
            "SELECT * FROM cash_lines WHERE business_day=? ORDER BY occurred_at, id",
            (business_day,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM cash_lines ORDER BY business_day DESC, occurred_at, id").fetchall()
    return [dict(r) for r in rows]


def day_summary(conn: sqlite3.Connection, business_day: str) -> dict[str, Any]:
    """营业日有效合计的唯一口径：该日全部有效流水（含冲正负向额）求和。

    冲正以负金额流水参与合计，不做物理删除，因此无需额外过滤墓碑数据；
    封账预览、封账落批、仪表盘都必须取这里的结果，保证同源。
    """
    row = conn.execute(
        '''SELECT COALESCE(SUM(amount), 0) AS system_total,
                  COUNT(*) AS line_count,
                  COALESCE(SUM(CASE WHEN entry_type='reversal' THEN 1 ELSE 0 END), 0) AS reversal_count
           FROM cash_lines
           WHERE business_day=?''',
        (business_day,),
    ).fetchone()
    return {
        "business_day": business_day,
        "system_total": float(row["system_total"]),
        "line_count": int(row["line_count"]),
        "reversal_count": int(row["reversal_count"]),
    }


def next_line_no(conn: sqlite3.Connection) -> str:
    n = conn.execute("SELECT COUNT(*) c FROM cash_lines").fetchone()["c"] + 1
    return f"CL-{n:04d}"


def insert_line(conn: sqlite3.Connection, **fields: Any) -> int:
    cur = conn.execute(
        '''INSERT INTO cash_lines(
             line_no, till_code, business_day, occurred_at, amount, pay_method, note,
             created_at, entry_type, reversal_of_line_no
           ) VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (
            fields["line_no"],
            fields["till_code"],
            fields["business_day"],
            fields["occurred_at"],
            fields["amount"],
            fields["pay_method"],
            fields.get("note"),
            fields["created_at"],
            fields.get("entry_type", ENTRY_NORMAL),
            fields.get("reversal_of_line_no"),
        ),
    )
    return int(cur.lastrowid)


def update_line(conn: sqlite3.Connection, line_id: int, **fields: Any) -> None:
    conn.execute(
        "UPDATE cash_lines SET amount=?, pay_method=?, note=? WHERE id=?",
        (fields["amount"], fields["pay_method"], fields.get("note"), line_id),
    )


def delete_line(conn: sqlite3.Connection, line_id: int) -> None:
    conn.execute("DELETE FROM cash_lines WHERE id=?", (line_id,))


def get_line(conn: sqlite3.Connection, line_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM cash_lines WHERE id=?", (line_id,)).fetchone()
    return dict(row) if row else None


def get_line_by_no(conn: sqlite3.Connection, line_no: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM cash_lines WHERE line_no=?", (line_no,)).fetchone()
    return dict(row) if row else None


def has_reversal(conn: sqlite3.Connection, line_no: str) -> bool:
    """该流水是否已被冲正（原流水只读链的一部分）。"""
    row = conn.execute(
        "SELECT 1 FROM reversals WHERE original_line_no=? LIMIT 1",
        (line_no,),
    ).fetchone()
    return row is not None

def net_total_raw(conn, business_day: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount),0) s FROM sale_lines WHERE business_day=?",
        (business_day,),
    ).fetchone()
    return float(row["s"])


def net_total_with_reversal_view(conn, business_day: str) -> float:
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM sale_lines WHERE business_day=?", (business_day,)
    ).fetchall()]
    from app import reversal_view
    return reversal_view.double_count_partition(rows)

