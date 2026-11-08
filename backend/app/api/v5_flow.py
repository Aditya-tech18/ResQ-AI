"""ResQ V5 local interactive demo. Does not place calls or assert verified consent."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/v5', tags=['ResQ interactive demo'])
DB = Path(os.getenv('RESQ_V5_DB', 'data/resq_v5.sqlite3'))

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS demo_flow (id INTEGER PRIMARY KEY CHECK(id=1), stage TEXT NOT NULL, incident TEXT NOT NULL, candidate TEXT, transcript TEXT, report TEXT, updated_at TEXT NOT NULL)')
    conn.execute("INSERT OR IGNORE INTO demo_flow VALUES (1,'new','{}',NULL,NULL,NULL,?)", (datetime.now(timezone.utc).isoformat(),))
    conn.commit()
    return conn

class Incident(BaseModel):
    driver_name: str = Field(default='Raju', min_length=1, max_length=80)
    location: str = Field(default='MVP Colony, Visakhapatnam', min_length=2, max_length=160)
    issue: str = Field(default='Van breakdown', min_length=2, max_length=200)
    parcels: int = Field(default=6, ge=1, le=100)
    language: str = Field(default='hi', pattern='^(hi|en)$')

class Transcript(BaseModel):
    driver: str = Field(pattern='^(Amit|Suresh)$')
    language: str = Field(pattern='^(hi|en|te)$')
    transcript: str = Field(min_length=10, max_length=4000)
    eta_minutes: int | None = Field(default=None, ge=1, le=240)
    parcel_capacity: int | None = Field(default=None, ge=0, le=100)
    destination: str | None = Field(default=None, max_length=160)
    accepted: bool | None = None

import json

def state():
    with connect() as conn:
        row = conn.execute('SELECT * FROM demo_flow WHERE id=1').fetchone()
    return {'mode':'SIMULATION','stage':row['stage'],'incident':json.loads(row['incident']), 'candidate':row['candidate'], 'transcript':row['transcript'], 'report':json.loads(row['report']) if row['report'] else None, 'real_call_connected':False}

@router.get('/state')
def get_state():
    return state()

@router.post('/incident')
def incident(body: Incident):
    with connect() as conn:
        conn.execute('UPDATE demo_flow SET stage=?,incident=?,candidate=NULL,transcript=NULL,report=NULL,updated_at=? WHERE id=1', ('reported',body.model_dump_json(),datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return state()

@router.post('/shortlist')
def shortlist():
    with connect() as conn:
        stage = conn.execute('SELECT stage FROM demo_flow WHERE id=1').fetchone()['stage']
        if stage != 'reported': raise HTTPException(409,'Report an incident first')
        conn.execute('UPDATE demo_flow SET stage=?,updated_at=? WHERE id=1',('shortlisted',datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return {'candidates':[{'name':'Suresh','language':'te','distance_km':2.1,'capacity':8},{'name':'Amit','language':'hi','distance_km':3.4,'capacity':10}], **state()}

@router.post('/call/{driver}')
def call(driver: str):
    if driver not in ('Suresh','Amit'): raise HTTPException(422,'Unknown driver')
    with connect() as conn:
        stage = conn.execute('SELECT stage FROM demo_flow WHERE id=1').fetchone()['stage']
        if stage not in ('shortlisted', 'reported_call'): raise HTTPException(409,'Shortlist drivers or finish the current call first')
        conn.execute('UPDATE demo_flow SET stage=?,candidate=?,updated_at=? WHERE id=1',('demo_call',driver,datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return state()

@router.post('/report')
def report(body: Transcript):
    with connect() as conn:
        row = conn.execute('SELECT stage,candidate,incident FROM demo_flow WHERE id=1').fetchone()
        if row['stage'] != 'demo_call' or row['candidate'] != body.driver:
            raise HTTPException(409,'No matching demo call in progress')
        incident_data = json.loads(row['incident'])
        report_data = {'driver':body.driver,'preferred_languages':['Telugu','English'] if body.driver=='Suresh' else ['Hindi','English'], 'breakdown_driver':incident_data['driver_name'], 'breakdown_location':incident_data['location'], 'eta_minutes':body.eta_minutes, 'destination':body.destination, 'parcels_offered':incident_data['parcels'], 'parcels_accepted':min(body.parcel_capacity,incident_data['parcels']) if body.accepted is True and body.parcel_capacity is not None else None, 'accepted':body.accepted, 'source':'MANUALLY ENTERED DEMO TRANSCRIPT — NOT VERIFIED PHONE AUDIO', 'transcript':body.transcript, 'dispatcher_approval':'PENDING', 'generated_at':datetime.now(timezone.utc).isoformat()}
        conn.execute('UPDATE demo_flow SET stage=?,transcript=?,report=?,updated_at=? WHERE id=1',('reported_call',body.transcript,json.dumps(report_data),datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return state()

@router.post('/reset')
def reset():
    with connect() as conn:
        conn.execute("UPDATE demo_flow SET stage='new',incident='{}',candidate=NULL,transcript=NULL,report=NULL,updated_at=? WHERE id=1",(datetime.now(timezone.utc).isoformat(),))
        conn.commit()
    return state()
