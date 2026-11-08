"""Standalone V5 dashboard; original screenshot HTML preserved."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from app.api.v5_flow import router

app = FastAPI(title='ResQ AI V5 Driver Rescue Demo')
app.include_router(router)
ROOT = Path(__file__).resolve().parents[2]

@app.get('/')
def home():
    return FileResponse(ROOT / 'frontend' / 'index.html')

@app.get('/v4.js')
def script():
    return FileResponse(ROOT / 'frontend' / 'v5.js', media_type='application/javascript')
