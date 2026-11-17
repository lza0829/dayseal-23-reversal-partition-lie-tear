from __future__ import annotations
import sqlite3
from typing import Any


def add_reversal(conn: sqlite3.Connection, **fields: Any) -> int:
    """登记一条冲正溯源记录。冲正流水本身落在 cash_lines，这里只保存血缘。"""
    cur = conn.execute(
        '''INSERT INTO reversals(
             reversal_line_id, reversal_line_no, original_line_id, original_line_no,
             policy, original_business_day, reversal_business_day, amount, created_at
           ) VALUES (?,?,?,?,?,?,?,?,?)''',
        (
            fields["reversal_line_id"],
            fields["reversal_line_no"],
            fields["original_line_id"],
            fields["original_line_no"],
            fields["policy"],
            fields["original_business_day"],
            fields["reversal_business_day"],
            fields["amount"],
            fields["created_at"],
        ),
    )
    return int(cur.lastrowid)


def list_reversals(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM reversals ORDER BY id DESC"
    ).fetchall()]


def get_by_original(conn: sqlite3.Connection, line_no: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM reversals WHERE original_line_no=? ORDER BY id LIMIT 1",
        (line_no,),
    ).fetchone()
    return dict(row) if row else None
