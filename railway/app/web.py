from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.main import app


STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"
UI_BUILD = "77"


@app.middleware("http")
async def frontend_cache_policy(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.lower()
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def eve_frontend_index() -> HTMLResponse:
    html = INDEX_FILE.read_text(encoding="utf-8")
    html = html.replace(
        'src="live_trader_intelligence_meter.js"',
        f'src="live_trader_intelligence_meter.js?v={UI_BUILD}"',
    )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-EVE-UI-Build": UI_BUILD,
        },
    )


# The API and /health routes are already registered by app.main. Mount the
# operator UI last so same-origin /api/* requests go straight to FastAPI and
# no Netlify proxy/function is required.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="eve-frontend")
