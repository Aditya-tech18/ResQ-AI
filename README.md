# ResQ AI

AI-assisted last-mile delivery exception handling and ResQ rescue workflows.
The repository includes a FastAPI backend, a local ResQ dashboard, and a
standalone simulated demo.

## Run locally

Use Python 3.12–3.14. From the repository root:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Set only the credentials needed for the features being exercised in
`backend/.env`. The deterministic/demo paths can run without external AI
credentials.

Start the ResQ dashboard from `backend/`:

```bash
python -m uvicorn app.api.v6_dashboard:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The standalone, simulated dashboard is also
available with `python demo/resq_dashboard.py` from `backend/` at
<http://127.0.0.1:8765>.

The general API is a separate app. Start it from `backend/` on a different
port if running both:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Its health check is at <http://127.0.0.1:8001/health> and API documentation is
at <http://127.0.0.1:8001/docs>.

## Tests and checks

From `backend/`, with the development dependencies installed:

```bash
python -m pytest -q
pip-audit .
```

Ruff is configured for the backend; the current codebase still has existing
lint findings. Run `ruff check app tests` to review them before a dedicated
style-cleanup pass.

## Security and demo scope

Never commit `.env` files or real credentials. The committed environment
template contains placeholders; `.gitignore` excludes local environment files,
databases, caches, and generated artifacts.

The ResQ dashboard is a local demo, not a production deployment. Its app
rejects non-loopback clients, but some demo report and context routes do not
have per-user authentication. Keep the server bound to `127.0.0.1`; do not
expose it through a public/shared network or a proxy. Add authenticated,
tenant-scoped access before deploying it. Dispatcher approval routes require
`RESQ_DISPATCHER_TOKEN`; configure a strong random token in the process
environment for those flows.

## Project layout

- `backend/app/api/` — FastAPI route handlers
- `backend/app/core/` — configuration, security, and logging
- `backend/app/models/` and `backend/app/db/` — persistence models and sessions
- `backend/app/services/` — application and integration workflows
- `backend/frontend/` — dashboard assets
- `backend/data/vizag_demo/` — labeled demo dataset
- `backend/tests/` — backend and security regression tests
