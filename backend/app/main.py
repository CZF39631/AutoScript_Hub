import sys
import os

# 确保 backend/ 在 sys.path 中，支持 PyCharm 直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routers import auth as auth_router
from app.routers import users as users_router
from app.routers import scripts as scripts_router
from app.routers import runs as runs_router
from app.routers import audit as audit_router
from app.routers import dashboard as dashboard_router
from app.routers import issues as issues_router
from app.routers import environments as env_router
from app.routers import settings as settings_router

app = FastAPI(title="AutoScript Hub", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


# Serve frontend static files (production mode)
_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_STATIC_DIR, "assets")), name="assets")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve SPA - fallback to index.html for client-side routing."""
        file_path = os.path.join(_STATIC_DIR, path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    from app.config import BACKEND_HOST, BACKEND_PORT
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
