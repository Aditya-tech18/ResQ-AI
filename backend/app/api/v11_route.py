"""ResQ route context and conservative parcel matching; no fabricated routing metrics."""
import json
import secrets
import datetime
import os
import sqlite3
from pathlib import Path
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/v11', tags=['ResQ route intelligence'])
DB = Path(os.getenv('RESQ_V11_DB', str(Path(__file__).resolve().parents[2] / 'data' / 'resq_v11.sqlite3')))

DEMO = [
 ('P001','MVP Colony','MVP Colony, Visakhapatnam'),
 ('P002','Seethammadhara','Seethammadhara, Visakhapatnam'),
 ('P003','Dwaraka Nagar','Dwaraka Nagar, Visakhapatnam'),
 ('P004','NAD Junction','NAD Junction, Visakhapatnam'),
 ('P005','Akkayyapalem','Akkayyapalem, Visakhapatnam'),
 ('P006','Gopalapatnam','Gopalapatnam, Visakhapatnam'),
]

def conn():
 DB.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(DB,timeout=10)
 db.row_factory=sqlite3.Row
 db.execute('CREATE TABLE IF NOT EXISTS incidents (id INTEGER PRIMARY KEY CHECK(id=1), driver TEXT NOT NULL, location TEXT NOT NULL, issue TEXT NOT NULL)')
 db.execute('CREATE TABLE IF NOT EXISTS parcels (id TEXT PRIMARY KEY, locality TEXT NOT NULL, address TEXT NOT NULL, status TEXT NOT NULL DEFAULT "pending", assigned_to TEXT)')
 db.execute('CREATE TABLE IF NOT EXISTS assignment_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, driver TEXT NOT NULL, parcel_ids TEXT NOT NULL, occurred_at TEXT NOT NULL)')
 db.commit()
 return db

class Incident(BaseModel):
 driver: str = Field(default='Raju', min_length=1, max_length=80)
 location: str = Field(min_length=3,max_length=240)
 issue: str = Field(default='Bike breakdown',min_length=3,max_length=240)
 parcels: list[dict[str,str]] = Field(min_length=1,max_length=100)

@router.post('/incident')
def incident(body: Incident, x_dispatcher_token: str | None = Header(default=None)):
 _require_dispatcher(x_dispatcher_token)
 ids=[p.get('id','') for p in body.parcels]
 if any(not p.get('id') or not p.get('address') or not p.get('locality') for p in body.parcels) or len(set(ids))!=len(ids):
  raise HTTPException(422,'Each parcel needs unique id, locality, address')
 with conn() as db:
  db.execute('BEGIN IMMEDIATE')
  if db.execute("SELECT COUNT(*) FROM parcels WHERE status != 'pending'").fetchone()[0]:
   raise HTTPException(409,'Cannot replace manifest containing assigned or picked-up parcels')
  db.execute('INSERT OR REPLACE INTO incidents(id,driver,location,issue) VALUES (1,?,?,?)',(body.driver,body.location,body.issue))
  db.execute('DELETE FROM parcels')
  db.executemany('INSERT INTO parcels(id,locality,address) VALUES (?,?,?)',[(p['id'],p['locality'],p['address']) for p in body.parcels])
 return {'ok':True,'parcels':len(body.parcels)}

def ensure_demo_manifest(location: str, issue: str, count: int):
 """Initialize synthetic parcels only when no matching real manifest exists.

 Never silently replace a user-supplied parcel manifest of the same count.
 """
 if not 1 <= count <= 100:
  raise HTTPException(422, 'Invalid parcel count')
 with conn() as db:
  existing=db.execute('SELECT COUNT(*) FROM parcels').fetchone()[0]
  if existing == count:
   db.execute('INSERT OR REPLACE INTO incidents(id,driver,location,issue) VALUES (1,?,?,?)',('Raju',location,issue))
   return {'source':'existing_manifest','count':count}
  if existing:
   # Old sample data or a real manifest with a different count must not be silently overwritten.
   raise HTTPException(409, f'Manifest has {existing} parcels but incident says {count}. Update /api/v11/incident with the correct parcel addresses.')
  examples=[{'id':p,'locality':l,'address':a} for p,l,a in DEMO]
  if count > len(examples):
   raise HTTPException(422,'Synthetic demo has 6 sample destinations. Provide a real manifest for more parcels.')
  db.execute('INSERT OR REPLACE INTO incidents(id,driver,location,issue) VALUES (1,?,?,?)',('Raju',location,issue))
  db.executemany('INSERT INTO parcels(id,locality,address) VALUES (?,?,?)',[(p['id'],p['locality'],p['address']) for p in examples[:count]])
 return {'source':'synthetic_demo','count':count}

@router.get('/manifest')
def manifest(x_dispatcher_token: str | None = Header(default=None)):
 _require_dispatcher(x_dispatcher_token)
 return context()

@router.post('/seed-demo')
def seed_demo(x_dispatcher_token: str | None = Header(default=None)):
 _require_dispatcher(x_dispatcher_token)
 return incident(Incident(driver='Raju',location='Gajuwaka Junction, Visakhapatnam',issue='Bike breakdown',parcels=[{'id':a,'locality':b,'address':c} for a,b,c in DEMO]), x_dispatcher_token=x_dispatcher_token)

@router.get('/context')
def context(x_dispatcher_token: str | None = Header(default=None)):
 with conn() as db:
  inc=db.execute('SELECT * FROM incidents WHERE id=1').fetchone()
  parcels=[dict(p) for p in db.execute('SELECT * FROM parcels ORDER BY id')]
 if not inc: raise HTTPException(404,'Create incident first; demo seed is opt-in')
 if x_dispatcher_token is None:
  return {'incident':{'driver':inc['driver'],'location':inc['location'],'issue':inc['issue']},'parcels':[{'id':p['id'],'locality':p['locality'],'status':p['status']} for p in parcels],'pending':sum(p['status']=='pending' for p in parcels)}
 _require_dispatcher(x_dispatcher_token)
 return {'incident':dict(inc),'parcels':parcels,'pending':sum(p['status']=='pending' for p in parcels)}

@router.get('/intro/{driver}')
def intro(driver:str):
 if not driver.strip() or len(driver)>80: raise HTTPException(422,'Invalid driver')
 c=context(x_dispatcher_token=None)
 loc=c['incident']['location']; count=c['pending']
 return {'driver':driver,'language':'hi','text':f'नमस्ते {driver} जी, मैं ResQ AI से बोल रही हूँ। राजू की बाइक {loc} के पास खराब हो गई है। उनके {count} पार्सल डिलीवर होने बाकी हैं। क्या आप कुछ डिलीवरी में मदद कर सकते हैं?', 'incident':c['incident'],'pending':count}

def normalize_locality(value: str) -> str:
 import unicodedata
 value=unicodedata.normalize('NFKC',value).casefold().strip()
 value=value.replace('dwarka','dwaraka').replace('mvp colony','mvp colony')
 value=value.replace('gopal pattnam','gopalapatnam').replace('gopal patnam','gopalapatnam')
 value=value.replace('गोपालपट्टनम','gopalapatnam').replace('द्वारका नगर','dwaraka nagar').replace('एमवीपी कॉलोनी','mvp colony')
 value=value.replace('एम वी पी कॉलोनी','mvp colony')
 return ''.join(ch for ch in value if ch.isalnum())

class RouteRequest(BaseModel):
 driver: str = Field(min_length=1,max_length=80)
 route_localities: list[str] = Field(min_length=1,max_length=12)
 capacity: int = Field(ge=0,le=100)
 accepted: bool
 eta_minutes: int | None = Field(default=None,ge=1,le=240)
 # Actual route detour measurements from a routing engine, keyed by parcel ID.
 # Never guess distances based on names alone.
 detour_km_by_parcel: dict[str,float] = Field(default_factory=dict)

@router.post('/match')
def match(req:RouteRequest):
 c=context(x_dispatcher_token=None)
 pending=[p for p in c['parcels'] if p['status']=='pending']
 localities={normalize_locality(x) for x in req.route_localities}
 possible=[p for p in pending if normalize_locality(p['locality']) in localities]
 # When detour metrics are unavailable, do not auto-assign; return candidates for dispatcher review.
 verified=[p for p in possible if p['id'] in req.detour_km_by_parcel and 0<=req.detour_km_by_parcel[p['id']]<=4]
 offered=verified[:req.capacity] if req.accepted else []
 return {'driver':req.driver,'route_localities':req.route_localities,'candidate_parcels':[p['id'] for p in possible], 'client_reported_detour_parcels':[p['id'] for p in verified], 'proposed_parcels':[p['id'] for p in offered], 'pickup_eta_minutes':req.eta_minutes, 'max_extra_detour_km':4,'approval':'PENDING', 'needs_routing_data':len(possible)>len(verified),'next_driver':None,'note':'Detour distances are client-supplied and not independently verified. Dispatcher must verify route before approval.'}

class Approve(BaseModel):
 driver:str=Field(min_length=1,max_length=80)
 parcel_ids:list[str]=Field(min_length=1,max_length=100)

@router.post('/approve')
def approve(req:Approve, x_dispatcher_token: str | None = Header(default=None)):
 import os, secrets
 token = os.getenv('RESQ_DISPATCHER_TOKEN','').strip()
 if not token:
  raise HTTPException(503,'Dispatcher approval disabled until RESQ_DISPATCHER_TOKEN is configured')
 if not x_dispatcher_token or not secrets.compare_digest(x_dispatcher_token,token):
  raise HTTPException(403,'Dispatcher authentication required')
 # Only a completed, consented call with confirmed ETA and matching candidate IDs
 # can be used as the basis for dispatcher approval.
 from app.api import v9_calls
 with v9_calls.connect() as call_db:
  call_rows=call_db.execute('SELECT * FROM calls WHERE actor=? AND status=? ORDER BY id DESC',(req.driver,'completed')).fetchall()
 valid=False
 for call in call_rows:
  facts=json.loads(call['facts'])
  if (facts.get('_v18_stage')=='completed' and facts.get('_v18_end_permission') is True
      and isinstance(facts.get('eta_minutes'),int)
      and set(req.parcel_ids).issubset(set(facts.get('route_candidate_ids') or []))):
   valid=True;break
 if not valid:raise HTTPException(409,'No consented completed call with ETA and these route candidates')
 if len(set(req.parcel_ids))!=len(req.parcel_ids):raise HTTPException(422,'Duplicate parcel IDs')
 with conn() as db:
  db.execute('BEGIN IMMEDIATE')
  rows=db.execute('SELECT id,status FROM parcels WHERE id IN ('+','.join('?'*len(req.parcel_ids))+')',req.parcel_ids).fetchall()
  if len(rows)!=len(req.parcel_ids) or any(row['status']!='pending' for row in rows):
   raise HTTPException(409,'One or more parcels unavailable')
  db.executemany('UPDATE parcels SET status="assigned",assigned_to=? WHERE id=?',[(req.driver,p) for p in req.parcel_ids])
  db.execute('INSERT INTO assignment_audit(event,driver,parcel_ids,occurred_at) VALUES (?,?,?,?)',('approved',req.driver,json.dumps(req.parcel_ids),datetime.datetime.now(datetime.timezone.utc).isoformat()))
 return {'approved':True,'driver':req.driver,'parcel_ids':req.parcel_ids}


def _require_dispatcher(x_dispatcher_token: str | None):
 token=os.getenv('RESQ_DISPATCHER_TOKEN','').strip()
 if not token: raise HTTPException(503,'Dispatcher authentication not configured')
 if not x_dispatcher_token or not secrets.compare_digest(x_dispatcher_token,token):
  raise HTTPException(403,'Dispatcher authentication required')

class PickupAcknowledgement(BaseModel):
 driver: str = Field(min_length=1,max_length=80)
 parcel_ids: list[str] = Field(min_length=1,max_length=100)

@router.post('/pickup-acknowledge')
def pickup_acknowledge(req: PickupAcknowledgement, x_dispatcher_token: str | None = Header(default=None)):
 """Dispatcher-authenticated recording of driver-confirmed physical pickup; not automatic delivery."""
 _require_dispatcher(x_dispatcher_token)
 if len(set(req.parcel_ids)) != len(req.parcel_ids): raise HTTPException(422,'Duplicate parcel IDs')
 with conn() as db:
  db.execute('BEGIN IMMEDIATE')
  rows=db.execute('SELECT id,status,assigned_to FROM parcels WHERE id IN ('+','.join('?'*len(req.parcel_ids))+')',req.parcel_ids).fetchall()
  if len(rows)!=len(req.parcel_ids) or any(r['status']!='assigned' or r['assigned_to']!=req.driver for r in rows):
   raise HTTPException(409,'Parcels must be assigned to this driver before pickup')
  db.executemany('UPDATE parcels SET status="picked_up" WHERE id=?',[(p,) for p in req.parcel_ids])
  db.execute('INSERT INTO assignment_audit(event,driver,parcel_ids,occurred_at) VALUES (?,?,?,?)',('pickup_acknowledged',req.driver,json.dumps(req.parcel_ids),datetime.datetime.now(datetime.timezone.utc).isoformat()))
 return {'acknowledged':True,'status':'picked_up','driver':req.driver,'parcel_ids':req.parcel_ids}

@router.get('/assignment-audit')
def assignment_audit(x_dispatcher_token: str | None = Header(default=None)):
 _require_dispatcher(x_dispatcher_token)
 with conn() as db:
  return {'events':[dict(r) for r in db.execute('SELECT * FROM assignment_audit ORDER BY id DESC LIMIT 100')]}
