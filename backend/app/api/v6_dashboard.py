"""Original V4 screenshot UI with inline mobile workflow, no overlay."""

import ipaddress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.gnani_voice_gateway import router as gnani_router
from app.api.live_report import router as live_report_router
from app.api.v5_flow import router as flow_router
from app.api.v6_intelligence import router as intelligence_router
from app.api.v7_agent import router as agent_router
from app.api.v9_calls import router as v9_router
from app.api.v11_route import router as route_router

app = FastAPI(title="ResQ AI — Delivery Emergency Rescue")


@app.middleware("http")
async def restrict_dashboard_to_loopback(request: Request, call_next):
    client = request.client
    try:
        is_loopback = client is not None and ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        is_loopback = False

    if not is_loopback:
        return JSONResponse(
            status_code=403,
            content={"detail": "The ResQ demo is available only from this machine."},
        )

    return await call_next(request)


app.include_router(live_report_router)
app.include_router(route_router)
app.include_router(flow_router)
app.include_router(intelligence_router)
app.include_router(agent_router)
app.include_router(v9_router)
app.include_router(gnani_router)

ROOT = Path(__file__).resolve().parents[2]


@app.get("/")
def home():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/v4.js")
def script():
    return FileResponse(
        ROOT / "frontend" / "v10.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/resq_hero_v22.css", include_in_schema=False)
def v22_css():
    return FileResponse(ROOT / "frontend" / "resq_hero_v22.css", media_type="text/css")


@app.get("/resq_hero_v22.js", include_in_schema=False)
def v22_js():
    return FileResponse(ROOT / "frontend" / "resq_hero_v22.js", media_type="application/javascript")
