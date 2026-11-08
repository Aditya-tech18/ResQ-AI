"""Demo-only spatial proximity. Coordinates are illustrative, not live geocoding.
Distance is straight-line to spoken route anchor(s), NOT road-route detour.
"""
from __future__ import annotations
import math, re, unicodedata
from fastapi import HTTPException
from app.api import v11_route

# Demo anchor points; update from verified routing/geocoding for production.
ANCHORS = {
 "mvp colony": (17.7420, 83.3310),
 "dwaraka nagar": (17.7218, 83.3043),
 "seethammadhara": (17.7410, 83.3110),
 "nad junction": (17.7440, 83.2500),
 "akkayyapalem": (17.7310, 83.2950),
 "gopalapatnam": (17.7470, 83.2240),
}
# Each parcel gets its own DEMO coordinate near the corresponding locality.
DEMO_PARCELS = {
 "P001": (17.7432, 83.3320), "P002": (17.7414, 83.3104),
 "P003": (17.7213, 83.3048), "P004": (17.7446, 83.2510),
 "P005": (17.7318, 83.2956), "P006": (17.7465, 83.2236),
}
ALIASES={
 "mvp colony": ("mvp colony","mvp","एमवीपी कॉलोनी","एम वी पी कॉलोनी"),
 "dwaraka nagar": ("dwaraka nagar","dwarka nagar","द्वारका नगर"),
 "seethammadhara": ("seethammadhara","सीतम्मधारा"),
 "nad junction": ("nad junction","एनएडी जंक्शन"),
 "akkayyapalem": ("akkayyapalem","अक्कय्यापालेम"),
 "gopalapatnam": ("gopalapatnam","gopal pattnam","gopal patnam","गोपालपट्टनम"),
}
def normalize(s):
 s=unicodedata.normalize('NFKC',s).casefold()
 return re.sub(r'[^\w\u0900-\u097f\u0c00-\u0c7f]+',' ',s).strip()
def route_from_speech(s):
 text=normalize(s); found=[]
 for canonical, aliases in ALIASES.items():
  if any(normalize(a) in text for a in aliases): found.append(canonical)
 return found

def haversine_km(a,b):
 lat1,lon1=map(math.radians,a);lat2,lon2=map(math.radians,b)
 x=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
 return 6371*2*math.asin(min(1,math.sqrt(x)))

def nearby(route_names, radius_km=2.0):
 """Return candidates within demo straight-line radius of spoken route anchors.
 No allocation, ETA, driving time or road detour inferred.
 """
 ctx=v11_route.context()
 anchors=[ANCHORS[n] for n in route_names if n in ANCHORS]
 if not anchors: return {'matched':[], 'route':route_names,'radius_km':radius_km,'measurement':'synthetic_straight_line'}
 matches=[]
 for parcel in ctx['parcels']:
  if parcel['status']!='pending':continue
  coord=DEMO_PARCELS.get(parcel['id'])
  if coord is None:continue # Unknown coordinates are not guessed.
  km=min(haversine_km(coord,anchor) for anchor in anchors)
  if km<=radius_km:
   matches.append({'id':parcel['id'],'locality':parcel['locality'],'distance_km':round(km,2)})
 return {'matched':sorted(matches,key=lambda p:p['distance_km']),'route':route_names,'radius_km':radius_km,'measurement':'synthetic_straight_line'}
