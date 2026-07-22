import sys
import os
import tempfile

# 确保 backend/ 和项目根目录在 sys.path 中，兼容源码与发布运行方式。
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
sys.path.insert(0, _BACKEND_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from sqlalchemy import text
from shared.version import get_channel, get_version
from app.config import CORS_ORIGINS, DATA_DIR
from app.database import engine
from app.config import DATABASE_URL
from app.migrations import migration_status
from app.routers import auth as auth_router
from app.routers import users as users_router
from app.routers import scripts as scripts_router
from app.routers import runs as runs_router
from app.routers import audit as audit_router
from app.routers import dashboard as dashboard_router
from app.routers import issues as issues_router
from app.routers import environments as env_router
from app.routers import settings as settings_router
from app.routers import agents as agents_router
from app.routers import presets as presets_router
app = FastAPI(title="AutoScript Hub", version=get_version())

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=bool(CORS_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(scripts_router.router)
app.include_router(runs_router.router)
app.include_router(audit_router.router)
app.include_router(dashboard_router.router)
app.include_router(issues_router.router)
app.include_router(env_router.router)
app.include_router(settings_router.router)
app.include_router(agents_router.router)
app.include_router(presets_router.router)


def _initialize_app():
    from init_db import init
    init()


@app.on_event("startup")
def _start_scheduler():
    """Initialize storage/database, then start background scheduler."""
    _initialize_app()
    from app.scheduler import start_scheduler
    start_scheduler()


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": get_version(), "channel": get_channel()}


def _readiness_checks():
    checks = {}

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"

    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=DATA_DIR, prefix=".ready-", delete=True):
            pass
        checks["data_dir"] = "ok"
    except Exception as exc:
        checks["data_dir"] = f"error: {type(exc).__name__}"

    try:
        checks["migration"] = "ok" if migration_status(DATABASE_URL)["ready"] else "error: database migration is not at head"
    except Exception as exc:
        checks["migration"] = f"error: {type(exc).__name__}"
    return checks


@app.get("/api/health/ready")
def readiness_check():
    checks = _readiness_checks()
    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "version": get_version(),
            "channel": get_channel(),
            "checks": checks,
        },
    )


# Serve frontend static files (production mode)
_STATIC_DIR = os.path.join(_BACKEND_DIR, "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_STATIC_DIR, "assets")), name="assets")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve SPA - fallback to index.html for client-side routing."""
        if path == "api" or path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        file_path = os.path.join(_STATIC_DIR, path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    from app.config import BACKEND_HOST, BACKEND_PORT
    uvicorn.run(app, host=str(BACKEND_HOST), port=int(BACKEND_PORT))
