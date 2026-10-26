import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from fastapi import HTTPException

def now():
    # Fixed client timezone; no dependence on execution host timezone.
    from datetime import timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


@contextmanager
def database(DB):
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB, timeout=15)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        yield connection
        connection.commit()
    finally:
        connection.close()


def load(DB, sid):
    with database(DB) as conn:
        row = conn.execute("SELECT body FROM sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        raise HTTPException(404, "练习不存在")
    return json.loads(row[0])


def save(DB, session):
    session["updated_at"] = now()
    with database(DB) as conn:
        conn.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (session["id"], json.dumps(session, ensure_ascii=False)))


