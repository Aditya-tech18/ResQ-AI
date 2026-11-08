"""Read-only operational snapshot plus clearly marked persistent demo actions.

Mount as a standalone app to avoid changing existing FastAPI router internals.
"""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="ResQ V4 Dashboard Bridge")
ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "frontend" / "index.html"
DEMO_DB = Path(os.getenv("RESQ_V4_DEMO_DB", str(ROOT / "data" / "v4_demo.sqlite3")))
INBOX_DB = os.getenv("RESQ_TELEPHONY_INBOX_DB", "")


def db():
    DEMO_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DEMO_DB, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("CREATE TABLE IF NOT EXISTS v4_demo (id INTEGER PRIMARY KEY CHECK(id=1), stage TEXT NOT NULL, driver TEXT, updated_at TEXT NOT NULL)")
    connection.execute("INSERT OR IGNORE INTO v4_demo VALUES (1,'incident',NULL,?)", (datetime.now(timezone.utc).isoformat(),))
    connection.commit()
    return connection


def inbox_counts():
    if not INBOX_DB or not Path(INBOX_DB).is_file():
        return {"connected": False, "message": "Set RESQ_TELEPHONY_INBOX_DB to the actual telephony inbox SQLite path"}
    try:
        with sqlite3.connect(f"file:{Path(INBOX_DB).resolve()}?mode=ro", uri=True) as conn:
            rows = conn.execute("SELECT status, COUNT(*) FROM telephony_inbox GROUP BY status").fetchall()
        return {"connected": True, "counts": {str(status): count for status, count in rows}}
    except sqlite3.Error:
        return {"connected": False, "message": "Inbox unavailable or incompatible schema"}


@app.get("/")
def home():
    return FileResponse(HTML, media_type="text/html")


@app.get("/v4.js")
def javascript():
    return FileResponse(ROOT / "frontend" / "v4.js", media_type="application/javascript")


@app.get("/api/v4/state")
def state():
    with db() as conn:
        row = conn.execute("SELECT stage,driver,updated_at FROM v4_demo WHERE id=1").fetchone()
    return {"mode": "SIMULATION", "stage": row["stage"], "driver": row["driver"], "updated_at": row["updated_at"], "telephony_inbox": inbox_counts(), "real_call_connected": False, "verified_consent": False, "real_rescue_workflow_connected": False}


class DemoAction(BaseModel):
    action: str
    driver: str | None = None


TRANSITIONS = {
    "incident": {"find_drivers": "ranked"},
    "ranked": {"simulate_call": "calling"},
    "calling": {"simulate_acceptance": "accepted", "reset": "incident"},
    "accepted": {"simulate_approval": "approved", "reset": "incident"},
    "approved": {"simulate_handover": "completed", "reset": "incident"},
    "completed": {"reset": "incident"},
}


@app.post("/api/v4/demo/action")
def action(body: DemoAction):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT stage,driver FROM v4_demo WHERE id=1").fetchone()
        stage = current["stage"]
        if body.action == "reset":
            next_stage = "incident"
        else:
            next_stage = TRANSITIONS.get(stage, {}).get(body.action)
        if not next_stage:
            raise HTTPException(status_code=409, detail=f"Action {body.action} not allowed from {stage}")
        if body.action == "simulate_call" and body.driver not in {"Suresh", "Amit"}:
            raise HTTPException(status_code=422, detail="Choose Suresh or Amit")
        driver = body.driver if body.action == "simulate_call" else (None if body.action == "reset" else current["driver"])
        conn.execute("UPDATE v4_demo SET stage=?,driver=?,updated_at=? WHERE id=1", (next_stage, driver, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return state()
