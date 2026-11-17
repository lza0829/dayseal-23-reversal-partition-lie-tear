from __future__ import annotations
from app.db import connect


SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tills (
  id INTEGER PRIMARY KEY,
  till_code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cash_lines (
  id INTEGER PRIMARY KEY,
  line_no TEXT NOT NULL UNIQUE,
  till_code TEXT NOT NULL,
  business_day TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  amount REAL NOT NULL,
  pay_method TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL,
  entry_type TEXT NOT NULL DEFAULT 'normal',
  reversal_of_line_no TEXT
);
CREATE TABLE IF NOT EXISTS close_batches (
  id INTEGER PRIMARY KEY,
  batch_no TEXT NOT NULL UNIQUE,
  business_day TEXT NOT NULL,
  system_total REAL NOT NULL,
  declared_cash REAL NOT NULL,
  variance REAL NOT NULL,
  line_count INTEGER NOT NULL,
  status TEXT NOT NULL,
  sealed_at TEXT NOT NULL,
  note TEXT
);
CREATE TABLE IF NOT EXISTS variance_rows (
  id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL,
  business_day TEXT NOT NULL,
  variance REAL NOT NULL,
  disposition TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS variance_holds (
  id INTEGER PRIMARY KEY,
  business_day TEXT NOT NULL,
  reason TEXT
);
CREATE TABLE IF NOT EXISTS reopen_requests (
  id INTEGER PRIMARY KEY,
  business_day TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'none'
);
CREATE TABLE IF NOT EXISTS reversals (
  id INTEGER PRIMARY KEY,
  reversal_line_id INTEGER NOT NULL,
  reversal_line_no TEXT NOT NULL,
  original_line_id INTEGER NOT NULL,
  original_line_no TEXT NOT NULL,
  policy TEXT NOT NULL,
  original_business_day TEXT NOT NULL,
  reversal_business_day TEXT NOT NULL,
  amount REAL NOT NULL,
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reversals_original
  ON reversals(original_line_no);
'''

# 冲正命运全局互斥策略（只贯彻一种）：
#   same_day    同日对冲：冲正落在原流水同一营业日，负向额进入该日合计
#   current_day 冲正日另计：冲正落入发起时当前营业日，原日已封合计不变
REVERSAL_POLICIES = ("same_day", "current_day")
DEFAULT_REVERSAL_POLICY = "same_day"


def _column_names(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate(conn) -> None:
    """对已存在的旧库补列/补表，不改动任何既有流水。"""
    cols = _column_names(conn, "cash_lines")
    if "entry_type" not in cols:
        conn.execute("ALTER TABLE cash_lines ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'normal'")
    if "reversal_of_line_no" not in cols:
        conn.execute("ALTER TABLE cash_lines ADD COLUMN reversal_of_line_no")
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS reversals (
             id INTEGER PRIMARY KEY,
             reversal_line_id INTEGER NOT NULL,
             reversal_line_no TEXT NOT NULL,
             original_line_id INTEGER NOT NULL,
             original_line_no TEXT NOT NULL,
             policy TEXT NOT NULL,
             original_business_day TEXT NOT NULL,
             reversal_business_day TEXT NOT NULL,
             amount REAL NOT NULL,
             created_at TEXT NOT NULL
           )'''
    )
    # 数据库级兜底：一条原流水至多一条冲正，防重复冲正
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_reversals_original ON reversals(original_line_no)"
    )
    row = conn.execute(
        "SELECT value FROM settings WHERE key='reversal_policy'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES ('reversal_policy', ?)",
            (DEFAULT_REVERSAL_POLICY,),
        )


def seed_if_empty() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        migrate(conn)
        n = conn.execute("SELECT COUNT(*) c FROM tills").fetchone()["c"]
        if n:
            conn.commit()
            return
        conn.execute("INSERT INTO settings(key, value) VALUES ('business_day', ?)", ("2026-11-16",))
        tills = [
            ("TILL-A", "一号收银"),
            ("TILL-B", "二号收银"),
            ("TILL-C", "三号收银"),
        ]
        for code, title in tills:
            conn.execute("INSERT INTO tills(till_code, title) VALUES (?,?)", (code, title))
        lines = [
            ("CL-0001", "TILL-A", "2026-11-16", "2026-11-16T09:12:00Z", 35.5, "现金", "早市"),
            ("CL-0002", "TILL-A", "2026-11-16", "2026-11-16T10:05:00Z", 128.0, "微信", None),
            ("CL-0003", "TILL-B", "2026-11-16", "2026-11-16T11:20:00Z", 66.0, "现金", None),
            ("CL-0004", "TILL-B", "2026-11-16", "2026-11-16T14:02:00Z", 210.0, "支付宝", None),
            ("CL-0005", "TILL-C", "2026-11-16", "2026-11-16T16:40:00Z", 49.9, "现金", None),
            ("CL-0006", "TILL-A", "2026-11-15", "2026-11-15T18:10:00Z", 88.0, "现金", "昨日"),
        ]
        for row in lines:
            conn.execute(
                '''INSERT INTO cash_lines(line_no, till_code, business_day, occurred_at, amount, pay_method, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (*row, row[3]),
            )
        conn.commit()
    finally:
        conn.close()
