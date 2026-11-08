from app.api.v11_route import router as route_router
"""Original V4 screenshot UI with inline mobile workflow, no overlay."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from app.api.v5_flow import router as flow_router
from app.api.v6_intelligence import router as intelligence_router
from app.api.v7_agent import router as agent_router

app = FastAPI(title="ResQ AI — Delivery Emergency Rescue")

from app.api.live_report import router as live_report_router
app.include_router(live_report_router)
app.include_router(route_router)
app.include_router(flow_router)
app.include_router(intelligence_router)
app.include_router(agent_router)
from app.api.v9_calls import router as v9_router
app.include_router(v9_router)
from app.api.gnani_voice_gateway import router as gnani_router
app.include_router(gnani_router)
ROOT = Path(__file__).resolve().parents[2]

@app.get("/")
def home():
    return FileResponse(ROOT / "frontend" / "index.html")

@app.get("/v4.js")
def script():
    return FileResponse(ROOT / "frontend" / "v10.js", media_type="application/javascript")
