"""ResQ route context and conservative parcel matching; no fabricated routing metrics."""
import json
import os
import sqlite3
from pathlib import Path
from fastapi import APIRouter, HTTPException
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
 db.commit()
 return db

class Incident(BaseModel):
 driver: str = Field(default='Raju', min_length=1, max_length=80)
 location: str = Field(min_length=3,max_length=240)
 issue: str = Field(default='Bike breakdown',min_length=3,max_length=240)
 parcels: list[dict[str,str]] = Field(min_length=1,max_length=100)

@router.post('/incident')
def incident(body: Incident):
 ids=[p.get('id','') for p in body.parcels]
 if any(not p.get('id') or not p.get('address') or not p.get('locality') for p in body.parcels) or len(set(ids))!=len(ids):
  raise HTTPException(422,'Each parcel needs unique id, locality, address')
 with conn() as db:
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
def manifest():
 return context()

@router.post('/seed-demo')
def seed_demo():
 return incident(Incident(driver='Raju',location='Gajuwaka Junction, Visakhapatnam',issue='Bike breakdown',parcels=[{'id':a,'locality':b,'address':c} for a,b,c in DEMO]))

@router.get('/context')
def context():
 with conn() as db:
  inc=db.execute('SELECT * FROM incidents WHERE id=1').fetchone()
  parcels=[dict(p) for p in db.execute('SELECT * FROM parcels ORDER BY id')]
 if not inc: raise HTTPException(404,'Create incident first; demo seed is opt-in')
 return {'incident':dict(inc),'parcels':parcels,'pending':sum(p['status']=='pending' for p in parcels)}

@router.get('/intro/{driver}')
def intro(driver:str):
 if driver not in ('Suresh','Amit'): raise HTTPException(404,'Unknown driver')
 c=context()
 loc=c['incident']['location']; count=c['pending']
 return {'driver':driver,'language':'hi','text':f'नमस्ते {"सुरेश" if driver=="Suresh" else "अमित"} जी, मैं ResQ AI से बोल रही हूँ। राजू की बाइक {loc} के पास खराब हो गई है। उनके {count} पार्सल डिलीवर होने बाकी हैं। क्या आप कुछ डिलीवरी में मदद कर सकते हैं?', 'incident':c['incident'],'pending':count}

def normalize_locality(value: str) -> str:
 import unicodedata
 value=unicodedata.normalize('NFKC',value).casefold().strip()
 value=value.replace('dwarka','dwaraka').replace('mvp colony','mvp colony')
 value=value.replace('gopal pattnam','gopalapatnam').replace('gopal patnam','gopalapatnam')
 value=value.replace('गोपालपट्टनम','gopalapatnam').replace('द्वारका नगर','dwaraka nagar').replace('एमवीपी कॉलोनी','mvp colony')
 value=value.replace('एम वी पी कॉलोनी','mvp colony')
 return ''.join(ch for ch in value if ch.isalnum())

class RouteRequest(BaseModel):
 driver: str = Field(pattern='^(Suresh|Amit)$')
 route_localities: list[str] = Field(min_length=1,max_length=12)
 capacity: int = Field(ge=0,le=100)
 accepted: bool
 eta_minutes: int | None = Field(default=None,ge=1,le=240)
 # Actual route detour measurements from a routing engine, keyed by parcel ID.
 # Never guess distances based on names alone.
 detour_km_by_parcel: dict[str,float] = Field(default_factory=dict)

@router.post('/match')
def match(req:RouteRequest):
 c=context()
 pending=[p for p in c['parcels'] if p['status']=='pending']
 localities={normalize_locality(x) for x in req.route_localities}
 possible=[p for p in pending if normalize_locality(p['locality']) in localities]
 # When detour metrics are unavailable, do not auto-assign; return candidates for dispatcher review.
 verified=[p for p in possible if p['id'] in req.detour_km_by_parcel and 0<=req.detour_km_by_parcel[p['id']]<=4]
 offered=verified[:req.capacity] if req.accepted else []
 return {'driver':req.driver,'route_localities':req.route_localities,'candidate_parcels':[p['id'] for p in possible], 'verified_parcels':[p['id'] for p in verified], 'proposed_parcels':[p['id'] for p in offered], 'pickup_eta_minutes':req.eta_minutes, 'max_extra_detour_km':4,'approval':'PENDING', 'needs_routing_data':len(possible)>len(verified),'next_driver':'Amit' if req.driver=='Suresh' and (not req.accepted or not offered) else None,'note':'No allocation is committed. Dispatcher must approve verified route and handover.'}

class Approve(BaseModel):
 driver:str=Field(pattern='^(Suresh|Amit)$')
 parcel_ids:list[str]=Field(min_length=1,max_length=100)

@router.post('/approve')
def approve(req:Approve):
 if len(set(req.parcel_ids))!=len(req.parcel_ids):raise HTTPException(422,'Duplicate parcel IDs')
 with conn() as db:
  db.execute('BEGIN IMMEDIATE')
  rows=db.execute('SELECT id,status FROM parcels WHERE id IN ('+','.join('?'*len(req.parcel_ids))+')',req.parcel_ids).fetchall()
  if len(rows)!=len(req.parcel_ids) or any(row['status']!='pending' for row in rows):
   raise HTTPException(409,'One or more parcels unavailable')
  db.executemany('UPDATE parcels SET status="assigned",assigned_to=? WHERE id=?',[(req.driver,p) for p in req.parcel_ids])
 return {'approved':True,'driver':req.driver,'parcel_ids':req.parcel_ids}
