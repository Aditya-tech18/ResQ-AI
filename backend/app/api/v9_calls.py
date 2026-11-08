"""Local simulated calls with persistent, auditable conversation reports.

No real outbound telephone calls or verified driver consent are performed.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from app.api import v11_route as routes
from app.api import v14_nearby as nearby
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v9", tags=["ResQ continuous voice demo"])
DB = Path(os.getenv("RESQ_V9_DB", "data/resq_v9.sqlite3"))


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL,
        started_at TEXT NOT NULL, ended_at TEXT, turns TEXT NOT NULL DEFAULT '[]',
        facts TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active'
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS incidents (
        id INTEGER PRIMARY KEY CHECK(id=1), driver TEXT NOT NULL,
        location TEXT, issue TEXT, parcels INTEGER, status TEXT NOT NULL
    )""")
    db.execute("""INSERT OR IGNORE INTO incidents(id,driver,status) VALUES (1,'Raju','awaiting_call')""")
    db.commit()
    return db


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def incident(db):
    return dict(db.execute("SELECT * FROM incidents WHERE id=1").fetchone())


def report_view(db):
    rows = db.execute("SELECT * FROM calls WHERE status='completed' AND actor!='Raju' ORDER BY id").fetchall()
    return [{"driver": r["actor"], "facts": json.loads(r["facts"]),
             "source": "unverified local microphone demo", "status": "awaiting_dispatcher_approval",
             "call_id": r["id"]} for r in rows]


@router.get("/state")
def state():
    with connect() as db:
        latest = db.execute("SELECT id,actor,status FROM calls ORDER BY id DESC LIMIT 1").fetchone()
        return {"incident": incident(db), "reports": report_view(db),
                "latest_call_id": latest["id"] if latest else None,
                "latest_call_actor": latest["actor"] if latest else None,
                "latest_call_status": latest["status"] if latest else None,
                "mode": "SIMULATED_CALLS", "real_phone_calls": False}


@router.post("/reset")
def reset():
    with connect() as db:
        db.execute("DELETE FROM calls")
        db.execute("UPDATE incidents SET location=NULL,issue=NULL,parcels=NULL,status='awaiting_call' WHERE id=1")
        db.commit()
    return state()


class IncidentReport(BaseModel):
    location: str = Field(min_length=3, max_length=160)
    issue: str = Field(min_length=3, max_length=160)
    parcels: int = Field(ge=1, le=100)


@router.post("/incident/report")
def report_incident(body: IncidentReport):
    """Raju submits an incident in the delivery app; no phone call required."""
    with connect() as db:
        active = db.execute("SELECT id FROM calls WHERE status='active' LIMIT 1").fetchone()
        if active:
            raise HTTPException(409, "End the active call before editing the incident")
        db.execute(
            "UPDATE incidents SET location=?,issue=?,parcels=?,status='awaiting_rescue' WHERE id=1",
            (body.location.strip(), body.issue.strip(), body.parcels),
        )
        db.commit()
    # Ensure incident and manifest share one consistent location/count.
    # Seed clearly labeled synthetic demo destinations only if the parcel table is empty.
    try:
        manifest_info = routes.ensure_demo_manifest(body.location.strip(), body.issue.strip(), body.parcels)
    except HTTPException as exc:
        # Avoid a successful incident report with a missing/stale manifest.
        raise HTTPException(exc.status_code, f'Parcel database: {exc.detail}') from exc
    response = state()
    response['manifest'] = manifest_info
    return response


class StartCall(BaseModel):
    actor: str = Field(pattern="^(Raju|Suresh|Amit)$")


@router.post("/calls")
def start_call(body: StartCall):
    with connect() as db:
        current = db.execute("SELECT id FROM calls WHERE status='active' LIMIT 1").fetchone()
        if current:
            raise HTTPException(409, "End active call before starting another")
        if body.actor != "Raju" and incident(db)["status"] == "awaiting_call":
            raise HTTPException(409, "Speak to Raju first")
        cur = db.execute("INSERT INTO calls(actor,started_at) VALUES (?,?)", (body.actor, utcnow()))
        db.commit()
        from app.api import v18_logic
        v18_logic.start_report(cur.lastrowid, body.actor, incident(db))
        return {"call_id": cur.lastrowid, "actor": body.actor, "mode": "SIMULATED_CALL"}


class Turn(BaseModel):
    transcript: str = Field(min_length=1, max_length=3000)
    detected_language: str | None = Field(default=None, max_length=40)


async def _resq_original_ask_gemini(actor, transcript, history, facts, inc, detected_language):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "GEMINI_API_KEY not configured")
    model = os.getenv("RESQ_GEMINI_MODEL", "gemini-3-flash-preview")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise HTTPException(400, "Invalid Gemini model")
    is_raju = actor == "Raju"
    task = (
        "You are collecting a breakdown report from Raju. Extract exact location, issue and "
        "number of pending parcels. Ask ONE short question for missing information. "
        "Once all present, summarize and ask if Raju needs anything else; finish ONLY after "
        "he explicitly says no or confirms call may end."
        if is_raju else
        "You are offering an emergency parcel rescue to a nearby driver. Raju's breakdown "
        "details are trusted context. First establish willingness. Once willing, ask which "
        "route or locations the driver is heading toward. Extract route_localities from their "
        "own answer; never invent destinations. A deterministic matching engine will calculate "
        "eligible parcel IDs. Do not state any parcel count until route matching is done. "
        "Do NOT ask how many parcels the driver can carry or request a delivery address. "
        "If declined, politely close and mark declined. After a route match, briefly say the count of nearby parcels and that details will be shared in the driver app; then politely ask permission to end the call. Only end after explicit permission."
    )
    manifest = None
    if not is_raju:
        try:
            manifest = routes.context()
        except HTTPException:
            manifest = None
    prompt = (
        "You are ResQ AI, a polite FEMALE voice dispatcher in a LOCAL SIMULATED CALL. "
        "Keep replies 1-2 brief spoken sentences, no markdown. "
        "Initial speech is Hindi for everyone. After hearing user, respond in the user's "
        "detected language: Telugu -> Telugu script, Hindi/Haryanvi -> natural simple Hindi "
        "with occasional Haryanvi phrases if appropriate, English -> English. "
        "Do not claim dialect-perfect speech. NEVER invent location, parcel count, ETA, "
        "acceptance, or destination. Existing facts carry forward; null means unknown. "
        "Extract only from DRIVER utterances, not AI suggestions. A user's question is not consent. "
        "Use a JSON object ONLY with keys reply, language (hi/te/en), facts (object), "
        "ready_to_close (boolean), end_call (boolean). "
        "For Raju facts: location (string/null), issue (string/null), parcels (integer/null). "
        "For helpers: accepted (boolean/null), parcels (integer/null), eta_minutes (integer/null), "
        "destination (string/null), route_localities (array of actual locality names spoken by driver). "
        "If user says a route in natural language, normalize locality names into route_localities. "
        "Do not infer route_localities from the AI speech or the manifest. "
        "Preserve previously confirmed values unless explicitly corrected. "
        "Never end if critical facts missing; if declined, end politely. "
        f"TASK: {task}\nACTOR: {actor}\nINCIDENT: {json.dumps(inc,ensure_ascii=False)}"
        f"\nDELIVERY MANIFEST (TRUSTED DATABASE): {json.dumps(manifest,ensure_ascii=False)}"
        f"\nCURRENT FACTS: {json.dumps(facts,ensure_ascii=False)}"
        f"\nDETECTED LANGUAGE: {detected_language or 'unknown'}"
        f"\nRECENT CONVERSATION: {json.dumps(history[-14:],ensure_ascii=False)}"
        f"\nLATEST DRIVER SPEECH: {transcript}"
    )
    try:
        async with httpx.AsyncClient(timeout=28) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}},
            )
            response.raise_for_status()
            result = json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])
            return result
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        _resq_log.warning("Gemini upstream HTTP %s (model=%s)", status, model)
        if status in (429, 500, 502, 503, 504):
            raise HTTPException(503, f"Gemini upstream HTTP {status}") from exc
        if status in (400, 404):
            raise HTTPException(502, f"Gemini model/request rejected (HTTP {status}); check RESQ_GEMINI_MODEL") from exc
        raise HTTPException(502, f"Gemini upstream HTTP {status}") from exc
    except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as exc:
        raise HTTPException(502, f"Gemini processing unavailable ({type(exc).__name__})") from exc


# RESQ_V15_GEMINI_RECOVERY — Gemini retry + deterministic demo-only recovery.
import asyncio as _resq_asyncio
import logging as _resq_logging

_resq_log = _resq_logging.getLogger("resq.gemini")


def _resq_demo_fallback(actor, transcript, facts, inc, detected_language):
    """Limited, explicitly labelled fallback; no invented parcel counts or addresses."""
    t = transcript.casefold().strip()
    # Return a safe clarification for unknown intents rather than inventing facts.
    lang = 'te' if detected_language == 'te' else 'en' if detected_language == 'en' else 'hi'
    if actor == 'Raju':
        missing=[k for k in ('location','issue','parcels') if not (facts.get(k) or inc.get(k))]
        if missing:
            questions={'location':'राजू जी, आप अभी किस लोकेशन पर हैं?',
                       'issue':'राजू जी, क्या समस्या हुई है?',
                       'parcels':'राजू जी, कितने पार्सल डिलीवर होने बाकी हैं?'}
            return {'reply':questions[missing[0]],'language':'hi','facts':{},'ready_to_close':False,'end_call':False}
        return {'reply':'राजू जी, आपकी जानकारी मिल गई है। क्या आपको और कुछ बताना है?',
                'language':'hi','facts':{},'ready_to_close':True,'end_call':False}
    if any(w in t for w in ('नहीं','नही','मना','cannot','can’t','cant','not available','busy','వద్దు')):
        return {'reply':f'कोई बात नहीं {actor} जी, धन्यवाद। मैं दूसरे ड्राइवर से संपर्क करूँगी।',
                'language':'hi','facts':{'accepted':False},'end_call':True}
    if any(w in t for w in ('हाँ','हां','बिल्कुल','बिलकुल','जी हाँ','yes','sure','help','అవును','సరే')):
        if facts.get('closing_requested'):
            return {'reply':f'धन्यवाद {actor} जी, नमस्कार।','language':'hi',
                    'facts':{'accepted':True},'end_call':True}
        return {'reply':f'{actor} जी, आप किस लोकेशन या रूट की तरफ जा रहे हैं?',
                'language':'hi','facts':{'accepted':True},'end_call':False}
    # V14 deterministic matcher reads spoken route names from body.transcript.
    # We only preserve already confirmed consent and never create it from a route name.
    if facts.get('accepted') is True:
        return {'reply':f'{actor} जी, आपके बताए रूट के हिसाब से पार्सल चेक कर रही हूँ।',
                'language':'hi','facts':{'accepted':True},'end_call':False}
    return {'reply':f'{actor} जी, क्या आप राजू जी की डिलीवरी में मदद कर सकते हैं?',
            'language':'hi','facts':{},'end_call':False}


async def ask_gemini(actor, transcript, history, facts, inc, detected_language):
    """Try Gemini; retry temporary failures; preserve voice conversation if down."""
    for attempt in range(3):
        try:
            return await _resq_original_ask_gemini(
                actor, transcript, history, facts, inc, detected_language)
        except HTTPException as exc:
            # Never swallow missing credentials, invalid model config or unrelated errors.
            if exc.status_code not in (429, 500, 502, 503, 504):
                raise
            _resq_log.warning('Gemini attempt %d/3 failed: %s',attempt+1,exc.detail)
            if attempt < 2:
                await _resq_asyncio.sleep((0.6, 1.4)[attempt])
    _resq_log.error('Gemini unavailable; using restricted deterministic demo fallback')
    return _resq_demo_fallback(actor,transcript,facts,inc,detected_language)


def sanitize_facts(actor, old, proposed):
    if not isinstance(proposed, dict):
        return old
    out = dict(old)
    allowed = ("location", "issue", "parcels") if actor == "Raju" else ("accepted", "parcels", "eta_minutes", "destination", "route_localities")
    for key in allowed:
        value = proposed.get(key)
        if value is None:
            continue
        if key == "route_localities":
            if isinstance(value, list) and len(value) <= 12 and all(isinstance(x, str) and 1 <= len(x.strip()) <= 100 for x in value):
                out[key] = [x.strip() for x in value]
        elif key in ("parcels", "eta_minutes"):
            if type(value) is int and 1 <= value <= (100 if key == "parcels" else 240):
                out[key] = value
        elif key == "accepted":
            if type(value) is bool:
                out[key] = value
        elif isinstance(value, str) and 1 <= len(value.strip()) <= 160:
            out[key] = value.strip()
    return out


@router.post("/calls/{call_id}/turn")
async def turn(call_id: int, body: Turn):
    from app.api import v18_logic
    with connect() as db:
        row = db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        if not row or row["status"] != "active":
            raise HTTPException(409, "Call is not active")
        actor = row["actor"]
        history = json.loads(row["turns"])
        facts = json.loads(row["facts"])
        inc = incident(db)

    # Deterministic, fast control for already established helper call stages.
    # Gemini remains responsible for conversational understanding at willingness stage
    # and for the Raju report, but may be unavailable; V15 fallback is preserved.
    stage = facts.get('_v18_stage', 'willingness')
    if actor != 'Raju' and stage in ('route', 'eta', 'consent'):
        result = {'reply': '', 'language': 'hi', 'facts': {}, 'end_call': False}
        new_facts = dict(facts)
        provider = 'deterministic_route_eta_consent'
    else:
        result = await ask_gemini(actor, body.transcript, history, facts, inc, body.detected_language)
        new_facts = sanitize_facts(actor, facts, result.get('facts'))
        provider = 'gemini_or_configured_fallback'

    route_result = None
    if actor != 'Raju':
        result, new_facts, route_result, end_call, stage = v18_logic.decide(
            actor, body.transcript, facts, new_facts, result)
        # Persist report before responding; dashboard polls this SQLite record.
        v18_logic.save(call_id, actor, inc, new_facts, stage, ended=end_call and stage=='completed')
        ready = bool(end_call)
    else:
        ready = all(new_facts.get(k) is not None for k in ('location', 'issue', 'parcels'))
        end_call = result.get('end_call') is True and ready

    reply = str(result.get('reply') or 'कृपया दोबारा बताइए।')[:450]
    language = result.get('language') if result.get('language') in {'hi','te','en'} else 'hi'
    history.extend([{'role':'driver','text':body.transcript}, {'role':'AI','text':reply}])
    with connect() as db:
        current = db.execute('SELECT status FROM calls WHERE id=?',(call_id,)).fetchone()
        if not current or current['status'] != 'active':
            raise HTTPException(409, 'Call ended while processing')
        db.execute('UPDATE calls SET turns=?,facts=? WHERE id=?',
                   (json.dumps(history,ensure_ascii=False),json.dumps(new_facts,ensure_ascii=False),call_id))
        if end_call:
            db.execute('UPDATE calls SET status=?,ended_at=? WHERE id=?',
                       ('completed',utcnow(),call_id))
            if actor=='Raju':
                db.execute('UPDATE incidents SET location=?,issue=?,parcels=?,status=? WHERE id=1',
                           (new_facts.get('location'),new_facts.get('issue'),new_facts.get('parcels'),'awaiting_rescue'))
        db.commit()
    return {'reply':reply,'language':language,'facts':new_facts,'ready_to_close':ready,
            'end_call':end_call,'provider':provider,'route_match':route_result,
            'report':state() if end_call else None}


@router.post("/calls/{call_id}/end")
def end_call(call_id: int):
    with connect() as db:
        row = db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown call")
        if row["status"] == "active":
            db.execute("UPDATE calls SET status='incomplete',ended_at=? WHERE id=?", (utcnow(), call_id))
            db.commit()
    return {"ended": True, "status": "incomplete_if_unconfirmed"}


@router.get("/raju-app")
def raju_app():
    return state()
