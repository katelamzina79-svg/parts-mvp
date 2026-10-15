"""SQLite-хранилище MVP: предложения замен (с согласованием инженером) и запросы КП."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("KRIT_DB") or Path(__file__).resolve().parent / "data" / "krit.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_number TEXT NOT NULL, line_id INTEGER NOT NULL, qty INTEGER NOT NULL,
  original_name TEXT NOT NULL, analogue_id TEXT NOT NULL, analogue_name TEXT NOT NULL,
  score REAL, verdict_code TEXT, verdict_text TEXT, comparison TEXT, offer TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  proposed_by TEXT, proposed_at TEXT, proposal_comment TEXT,
  decided_by TEXT, decided_at TEXT, decision_comment TEXT
);
CREATE TABLE IF NOT EXISTS quotes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, name TEXT, supplier TEXT,
  qty INTEGER, comment TEXT, created_at TEXT
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def _dec(row):
    d = dict(row)
    d["comparison"] = json.loads(d["comparison"] or "[]")
    d["offer"] = json.loads(d["offer"]) if d["offer"] else None
    return d


def create_decision(request_number, line_id, qty, original_name, match, proposed_by, comment):
    """Новое предложение замены. Возвращает запись или None, если по строке уже есть ожидающее."""
    with conn() as c:
        busy = c.execute("SELECT 1 FROM decisions WHERE request_number=? AND line_id=? AND status='pending'",
                         (request_number, line_id)).fetchone()
        if busy:
            return None
        cur = c.execute(
            """INSERT INTO decisions (request_number,line_id,qty,original_name,analogue_id,analogue_name,
               score,verdict_code,verdict_text,comparison,offer,status,proposed_by,proposed_at,proposal_comment)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending',?,?,?)""",
            (request_number, line_id, qty, original_name, match["id"], match["name"], match["score"],
             match["verdict"]["code"], match["verdict"]["text"],
             json.dumps(match["comparison"], ensure_ascii=False),
             json.dumps(match["best_offer"], ensure_ascii=False) if match["best_offer"] else None,
             proposed_by, now(), comment))
        return _dec(c.execute("SELECT * FROM decisions WHERE id=?", (cur.lastrowid,)).fetchone())


def list_decisions(status=None, request_number=None):
    q, args = "SELECT * FROM decisions WHERE 1=1", []
    if status:
        q += " AND status=?"
        args.append(status)
    if request_number:
        q += " AND request_number=?"
        args.append(request_number)
    with conn() as c:
        return [_dec(r) for r in c.execute(q + " ORDER BY id DESC", args)]


def get_decision(did):
    with conn() as c:
        r = c.execute("SELECT * FROM decisions WHERE id=?", (did,)).fetchone()
        return _dec(r) if r else None


def decide(did, status, decided_by, comment):
    """Фиксирует решение инженера. Только из статуса pending; возвращает запись или None."""
    with conn() as c:
        cur = c.execute("UPDATE decisions SET status=?, decided_by=?, decided_at=?, decision_comment=? "
                        "WHERE id=? AND status='pending'", (status, decided_by, now(), comment, did))
        if cur.rowcount == 0:
            return None
        return _dec(c.execute("SELECT * FROM decisions WHERE id=?", (did,)).fetchone())


def add_quote(item_id, name, supplier, qty, comment):
    with conn() as c:
        cur = c.execute("INSERT INTO quotes (item_id,name,supplier,qty,comment,created_at) VALUES (?,?,?,?,?,?)",
                        (item_id, name, supplier, qty, comment, now()))
        return {"number": f"КП-{cur.lastrowid:04d}", "item_id": item_id, "name": name,
                "supplier": supplier, "qty": qty, "comment": comment}


def list_quotes():
    with conn() as c:
        return [{"number": f"КП-{r['id']:04d}", "item_id": r["item_id"], "name": r["name"],
                 "supplier": r["supplier"], "qty": r["qty"], "comment": r["comment"],
                 "created_at": r["created_at"]} for r in c.execute("SELECT * FROM quotes ORDER BY id")]
