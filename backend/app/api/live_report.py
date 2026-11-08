"""ResQ live call report: additive FastAPI router backed by SQLite.
No real driver GPS or dispatch approval is inferred.
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/v16', tags=['live-report'])
DB = Path(os.getenv('RESQ_LIVE_REPORT_DB', 'data/resq_live_reports.sqlite3'))
LOCK = RLock()


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('''CREATE TABLE IF NOT EXISTS live_reports (
      call_id TEXT PRIMARY KEY, rescue_driver TEXT NOT NULL,
      breakdown_driver TEXT NOT NULL, breakdown_location TEXT NOT NULL,
      parcel_ids TEXT NOT NULL DEFAULT '[]', nearby_parcels INTEGER,
      next_route TEXT, current_location TEXT, pickup_eta_minutes INTEGER,
      call_status TEXT NOT NULL DEFAULT 'in_progress',
      end_permission INTEGER, updated_at TEXT NOT NULL
    )''')
    return db


def as_dict(row):
    if row is None: return None
    out = dict(row)
    out['parcel_ids'] = json.loads(out['parcel_ids'])
    out['end_permission'] = None if out['end_permission'] is None else bool(out['end_permission'])
    return out


class StartReport(BaseModel):
    call_id: str = Field(min_length=1, max_length=80)
    rescue_driver: str = Field(min_length=1, max_length=80)
    breakdown_driver: str = Field(min_length=1, max_length=80)
    breakdown_location: str = Field(min_length=3, max_length=200)


class UpdateReport(BaseModel):
    next_route: str | None = Field(default=None, max_length=250)
    current_location: str | None = Field(default=None, max_length=250)
    parcel_ids: list[str] | None = None
    pickup_eta_minutes: int | None = Field(default=None, ge=1, le=240)
    call_status: Literal['in_progress','awaiting_eta','awaiting_permission','completed','declined'] | None = None
    end_permission: bool | None = None


@router.post('/reports/start')
def start_report(body: StartReport):
    now = datetime.now(timezone.utc).isoformat()
    with LOCK, connect() as db:
        db.execute('''INSERT INTO live_reports
          (call_id,rescue_driver,breakdown_driver,breakdown_location,updated_at)
          VALUES (?,?,?,?,?) ON CONFLICT(call_id) DO NOTHING''',
          (body.call_id,body.rescue_driver,body.breakdown_driver,body.breakdown_location,now))
        return as_dict(db.execute('SELECT * FROM live_reports WHERE call_id=?',(body.call_id,)).fetchone())


@router.patch('/reports/{call_id}')
def update_report(call_id: str, body: UpdateReport):
    values = body.model_dump(exclude_unset=True)
    if not values: raise HTTPException(422, 'No fields supplied')
    if 'parcel_ids' in values:
        ids = values['parcel_ids']
        if len(ids) != len(set(ids)): raise HTTPException(422,'Duplicate parcel IDs')
        values['nearby_parcels'] = len(ids)
        values['parcel_ids'] = json.dumps(ids)
    if 'end_permission' in values and values['end_permission'] is not None:
        values['end_permission'] = int(values['end_permission'])
    with LOCK, connect() as db:
        row = db.execute('SELECT * FROM live_reports WHERE call_id=?',(call_id,)).fetchone()
        if row is None: raise HTTPException(404,'Call report not found')
        existing = as_dict(row)
        status = values.get('call_status')
        if status == 'completed':
            eta = values.get('pickup_eta_minutes',existing['pickup_eta_minutes'])
            consent = values.get('end_permission',existing['end_permission'])
            if not eta or consent not in (True,1):
                raise HTTPException(409,'Pickup ETA and explicit end permission required')
        values['updated_at'] = datetime.now(timezone.utc).isoformat()
        columns = ', '.join(f'{key}=?' for key in values)
        db.execute(f'UPDATE live_reports SET {columns} WHERE call_id=?',(*values.values(),call_id))
        return as_dict(db.execute('SELECT * FROM live_reports WHERE call_id=?',(call_id,)).fetchone())


@router.get('/reports/{call_id}')
def get_report(call_id: str):
    with connect() as db:
        row = db.execute('SELECT * FROM live_reports WHERE call_id=?',(call_id,)).fetchone()
        if row is None: raise HTTPException(404,'Call report not found')
        return as_dict(row)


@router.get('/reports')
def list_reports():
    with connect() as db:
        rows = db.execute('SELECT * FROM live_reports ORDER BY updated_at DESC LIMIT 20').fetchall()
        return [as_dict(row) for row in rows]
