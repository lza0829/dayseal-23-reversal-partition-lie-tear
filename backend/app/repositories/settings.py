from __future__ import annotations
import sqlite3

# 冲正命运全局互斥策略：全系统同一时刻只贯彻一种
REVERSAL_POLICY_SAME_DAY = "same_day"        # 同日对冲
REVERSAL_POLICY_CURRENT_DAY = "current_day"  # 冲正日另计
REVERSAL_POLICIES = (REVERSAL_POLICY_SAME_DAY, REVERSAL_POLICY_CURRENT_DAY)
DEFAULT_REVERSAL_POLICY = REVERSAL_POLICY_SAME_DAY
REVERSAL_POLICY_KEY = "reversal_policy"


def get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_reversal_policy(conn: sqlite3.Connection) -> str:
    value = get(conn, REVERSAL_POLICY_KEY)
    return value if value in REVERSAL_POLICIES else DEFAULT_REVERSAL_POLICY
