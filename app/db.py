import json, os, sqlite3, threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = os.getenv("AUDITOR_DB_PATH", "data/auditor.sqlite3")
_lock = threading.RLock()

@contextmanager
def _conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False); c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def init_db():
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS api_cache (cache_key TEXT PRIMARY KEY, response_json TEXT NOT NULL, fetched_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS llm_cache (cache_key TEXT PRIMARY KEY, response_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audits (id TEXT PRIMARY KEY, video_id TEXT, status TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS claims (id TEXT PRIMARY KEY, audit_id TEXT NOT NULL, payload_json TEXT NOT NULL, state TEXT NOT NULL, FOREIGN KEY(audit_id) REFERENCES audits(id));
        """)

def _now(): return datetime.now(timezone.utc).isoformat()
def cache_get(key, table="api_cache"):
    with _lock, _conn() as c:
        row=c.execute(f"SELECT response_json FROM {table} WHERE cache_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None
def cache_put(key, value, table="api_cache"):
    col="cache_key"; ts="fetched_at" if table=="api_cache" else "created_at"
    with _lock, _conn() as c: c.execute(f"INSERT OR REPLACE INTO {table} ({col},response_json,{ts}) VALUES (?,?,?)", (key,json.dumps(value,ensure_ascii=False),_now()))
def save_audit(audit_id, video_id, status, payload):
    with _lock, _conn() as c:
        now=_now(); c.execute("INSERT OR REPLACE INTO audits VALUES (?,?,?,?,?,?)", (audit_id,video_id,status,json.dumps(payload,ensure_ascii=False),now,now))
def load_audit(audit_id):
    with _lock, _conn() as c:
        row=c.execute("SELECT * FROM audits WHERE id=?",(audit_id,)).fetchone()
        return dict(row) if row else None
def save_claim(claim_id, audit_id, payload, state="pending"):
    with _lock, _conn() as c: c.execute("INSERT OR REPLACE INTO claims VALUES (?,?,?,?)",(claim_id,audit_id,json.dumps(payload,ensure_ascii=False),state))
def list_claims(audit_id):
    with _lock, _conn() as c: return [dict(r) for r in c.execute("SELECT * FROM claims WHERE audit_id=? ORDER BY rowid",(audit_id,))]
init_db()
