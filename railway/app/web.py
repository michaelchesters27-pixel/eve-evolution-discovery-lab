from __future__ import annotations

from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app.main import app


STATIC_DIR = Path(__file__).resolve().parent / "static"

# The API and /health routes are already registered by app.main. Mount the
# operator UI last so same-origin /api/* requests go straight to FastAPI and
# no Netlify proxy/function is required.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="eve-frontend")
